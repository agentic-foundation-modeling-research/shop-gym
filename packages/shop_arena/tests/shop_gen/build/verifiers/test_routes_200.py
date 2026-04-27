"""Unit tests for :class:`shop_gen.build.verifiers.routes_200.Routes200Verifier`.

Covers T5.4 + spec §5.5.3: boot a transient dev server (factory
seam), GET each configured route, fail on any non-200. Tests substitute
an in-process ``http.server`` via the :class:`DevServerFactory` seam so
no Node toolchain is required.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Final

import pytest

from harness.verifiers import Verdict, VerifierContext
from shop_gen.build.verifiers.routes_200 import (
    DevServerFactory,
    Routes200Verifier,
)

_TASK_ROUTES: Final[Mapping[str, Sequence[str]]] = {
    "gen_navigation": ("/",),
    "gen_homepage": ("/",),
    "gen_collections": ("/collections", "/collections/best-sellers"),
    "gen_product": ("/products/sample-handle",),
    "gen_info_pages": ("/pages/about",),
    "consolidate": ("/",),
}


class _MapHandler(BaseHTTPRequestHandler):
    """HTTP handler that maps paths to status codes from a class-level mapping."""

    # Filled in by `_threaded_server`. Named with a trailing underscore to
    # avoid shadowing ``BaseHTTPRequestHandler.responses`` (the stdlib's
    # status-code description table).
    path_status: Mapping[str, int]

    def do_GET(self) -> None:
        status = self.path_status.get(self.path)
        if status is None:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            self.wfile.write(b"unknown route")
            return
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — stdlib API
        del format, args  # silence the default access-log spam


@contextlib.contextmanager
def _threaded_server(responses: Mapping[str, int]) -> Iterator[str]:
    """Spin up an in-process HTTP server backing the given path → status map."""

    class _Handler(_MapHandler):
        pass

    _Handler.path_status = responses
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


def _factory(
    responses: Mapping[str, int],
    *,
    captured: list[Path] | None = None,
) -> DevServerFactory:
    """Build a :class:`DevServerFactory` returning :func:`_threaded_server`."""

    def _build(hydrogen_dir: Path) -> AbstractContextManager[str]:
        if captured is not None:
            captured.append(hydrogen_dir)
        return _threaded_server(responses)

    return _build


def _failing_factory(exc: BaseException) -> DevServerFactory:
    """Build a :class:`DevServerFactory` that raises on call."""

    def _build(hydrogen_dir: Path) -> AbstractContextManager[str]:
        del hydrogen_dir
        raise exc

    return _build


def test_name_and_applicability() -> None:
    verifier = Routes200Verifier(
        task_routes=_TASK_ROUTES,
        dev_server_factory=_factory({}),
    )
    assert verifier.name == "routes_200"
    assert verifier.applies_to("gen_homepage") is True
    assert verifier.applies_to("gen_collections") is True
    assert verifier.applies_to("consolidate") is True
    assert verifier.applies_to("gen_theme") is False
    assert verifier.applies_to("plan") is False


def test_constructor_rejects_empty_mapping() -> None:
    with pytest.raises(ValueError, match="at least one task"):
        Routes200Verifier(task_routes={}, dev_server_factory=_factory({}))


def test_passes_when_every_route_returns_200(
    make_ctx: Callable[..., VerifierContext],
    hydrogen_tree: Path,
) -> None:
    captured: list[Path] = []
    verifier = Routes200Verifier(
        task_routes=_TASK_ROUTES,
        dev_server_factory=_factory(
            {"/collections": 200, "/collections/best-sellers": 200},
            captured=captured,
        ),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_collections"))

    assert result.verdict is Verdict.PASS
    assert result.details["all_ok"] is True
    assert captured == [hydrogen_tree]


def test_fails_on_non_200_status(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    verifier = Routes200Verifier(
        task_routes=_TASK_ROUTES,
        dev_server_factory=_factory(
            {"/collections": 200, "/collections/best-sellers": 500},
        ),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_collections"))

    assert result.verdict is Verdict.FAIL
    assert result.details["routes"] == ["/collections", "/collections/best-sellers"]
    assert len(result.details["failures"]) == 1
    assert result.details["failures"][0]["route"] == "/collections/best-sellers"
    assert result.details["failures"][0]["status"] == "500"
    assert "/collections/best-sellers" in result.feedback
    assert "500" in result.feedback


def test_fails_on_unmapped_route_returning_404(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    verifier = Routes200Verifier(
        task_routes=_TASK_ROUTES,
        dev_server_factory=_factory({}),  # nothing mapped → 404
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))
    assert result.verdict is Verdict.FAIL
    assert "/" in result.feedback


def test_fails_when_factory_raises(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    verifier = Routes200Verifier(
        task_routes=_TASK_ROUTES,
        dev_server_factory=_failing_factory(RuntimeError("pnpm dev exit 1")),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))
    assert result.verdict is Verdict.FAIL
    assert "factory_construct" in result.details["phase"]
    assert "RuntimeError" in result.feedback


def test_passes_when_task_has_empty_route_list(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    """A configured task with no routes should be a PASS no-op."""
    verifier = Routes200Verifier(
        task_routes={"gen_homepage": ()},
        dev_server_factory=_factory({}),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))
    assert result.verdict is Verdict.PASS
    assert result.details == {"routes": [], "task_id": "gen_homepage"}


def test_fails_when_hydrogen_tree_missing(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
) -> None:
    app_dir = artifact_dir / "hydrogen" / "app"
    app_dir.rmdir()
    (artifact_dir / "hydrogen").rmdir()

    verifier = Routes200Verifier(
        task_routes={"gen_homepage": ("/",)},
        dev_server_factory=_factory({"/": 200}),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))
    assert result.verdict is Verdict.FAIL
    assert "could not find the hydrogen tree" in result.feedback


def test_unconfigured_task_is_skipped(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    """A task not in ``task_routes`` should not even cause ``applies_to`` to match."""
    verifier = Routes200Verifier(
        task_routes={"gen_homepage": ("/",)},
        dev_server_factory=_factory({"/": 200}),
    )
    assert verifier.applies_to("gen_theme") is False
