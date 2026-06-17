"""Unit tests for :class:`shop_arena.gen.build.verifiers.routes_200.Routes200Verifier`.

Covers impl plan T4.1 + spec §5.3 / §5.8: every ``gen_*`` task resolves
through ``buckets_for_task`` → ``routes_for_buckets`` (the same module
``visual_judge`` consumes), the verifier hits each resolved route, and
asserts every response is 2xx. Tests substitute an in-process
``http.server`` via the
:class:`~shop_arena.gen.final_eval.playwright_smoke.DevServerFactory` seam so
no Node toolchain is required.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from harness.verifiers import Verdict, VerifierContext
from shop_arena.gen.build.verifiers._task_routes import (
    buckets_for_task,
    routes_for_buckets,
)
from shop_arena.gen.build.verifiers.routes_200 import Routes200Verifier
from shop_arena.gen.final_eval.playwright_smoke import DevServerFactory

# --------------------------------------------------------------------------- #
# Fixtures + stub HTTP server
# --------------------------------------------------------------------------- #


class _MapHandler(BaseHTTPRequestHandler):
    """HTTP handler that maps paths to status codes from a class-level mapping.

    The ``self.path`` value includes any query string (``/search?q=foo``);
    matching is done against the full string so test fixtures can
    distinguish between routes that share a prefix.
    """

    path_status: Mapping[str, int]
    path_body: Mapping[str, str]

    def do_GET(self) -> None:
        status = self.path_status.get(self.path)
        if status is None:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            self.wfile.write(b"unknown route")
            return
        self.send_response(status)
        self.end_headers()
        body = self.path_body.get(self.path, "ok")
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- stdlib API
        del format, args  # silence default access-log spam


@contextlib.contextmanager
def _threaded_server(
    responses: Mapping[str, int],
    *,
    bodies: Mapping[str, str] | None = None,
) -> Iterator[str]:
    """Spin up an in-process HTTP server backing the given path → status map."""

    class _Handler(_MapHandler):
        pass

    _Handler.path_status = responses
    _Handler.path_body = bodies or {}
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
    bodies: Mapping[str, str] | None = None,
    captured: list[Path] | None = None,
) -> DevServerFactory:
    """Build a :class:`DevServerFactory` returning :func:`_threaded_server`."""

    def _build(hydrogen_dir: Path) -> AbstractContextManager[str]:
        if captured is not None:
            captured.append(hydrogen_dir)
        return _threaded_server(responses, bodies=bodies)

    return _build


def _failing_factory(exc: BaseException) -> DevServerFactory:
    """Build a :class:`DevServerFactory` that raises on call."""

    def _build(hydrogen_dir: Path) -> AbstractContextManager[str]:
        del hydrogen_dir
        raise exc

    return _build


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Build a fixture data dir backing ``buckets_for_task`` resolution.

    Seeds the three JSON files the bucket axis reads. The handles are
    deterministic so tests can assert against the resulting URLs.
    """
    target = tmp_path / "data"
    target.mkdir()
    (target / "collections.json").write_text(
        json.dumps(
            [
                {
                    "handle": "best-sellers",
                    "title": "Best sellers",
                    "product_handles": ["sample-handle"],
                },
            ],
        ),
        encoding="utf-8",
    )
    (target / "products.json").write_text(
        json.dumps(
            [{"handle": "sample-handle", "title": "Sample Widget"}],
        ),
        encoding="utf-8",
    )
    (target / "pages.json").write_text(
        json.dumps([{"handle": "about"}]),
        encoding="utf-8",
    )
    return target


# --------------------------------------------------------------------------- #
# Identity / applicability
# --------------------------------------------------------------------------- #


def test_name_matches_spec(data_dir: Path) -> None:
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({}),
    )
    assert verifier.name == "routes_200"


def test_applies_to_every_gen_star_task(data_dir: Path) -> None:
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({}),
    )
    for task_id in (
        "gen_homepage",
        "gen_navigation",
        "gen_collections",
        "gen_product",
        "gen_cart_search",
        "gen_info_pages",
        "gen_homepage_redo_3",
        "gen_theme",  # gen_* but unmapped — applies_to True; run() PASSes no-op.
    ):
        assert verifier.applies_to(task_id) is True, f"missing {task_id}"


def test_does_not_apply_to_non_gen_tasks(data_dir: Path) -> None:
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({}),
    )
    assert verifier.applies_to("plan") is False
    assert verifier.applies_to("visual_fix") is False


# --------------------------------------------------------------------------- #
# Healthy fixture path — every probed route returns 2xx
# --------------------------------------------------------------------------- #


def test_passes_when_every_route_returns_2xx(
    make_ctx: Callable[..., VerifierContext],
    hydrogen_tree: Path,
    data_dir: Path,
) -> None:
    captured: list[Path] = []
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({"/": 200}, captured=captured),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))

    assert result.verdict is Verdict.PASS
    assert result.details["all_ok"] is True
    assert result.details["routes"] == ["/"]
    assert result.details["buckets"] == ["homepage"]
    assert captured == [hydrogen_tree]


def test_passes_when_response_is_2xx_other_than_200(
    make_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """The verifier accepts the entire 2xx range, not just 200."""
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({"/": 204}),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))
    assert result.verdict is Verdict.PASS


def test_passes_when_collection_routes_are_healthy(
    make_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """A multi-route bucket (gen_collections → /collections + handle URL)."""
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory(
            {"/collections": 200, "/collections/best-sellers": 200},
        ),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_collections"))
    assert result.verdict is Verdict.PASS
    assert "/collections" in result.details["routes"]
    assert "/collections/best-sellers" in result.details["routes"]


# --------------------------------------------------------------------------- #
# Failure paths
# --------------------------------------------------------------------------- #


def test_fails_on_non_2xx_status(
    make_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory(
            {"/collections": 200, "/collections/best-sellers": 500},
        ),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_collections"))

    assert result.verdict is Verdict.FAIL
    assert len(result.details["failures"]) == 1
    failure = result.details["failures"][0]
    assert failure["route"] == "/collections/best-sellers"
    assert failure["status"] == "500"
    assert "/collections/best-sellers" in result.feedback
    assert "500" in result.feedback


def test_fails_on_404_route(
    make_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({}),  # nothing mapped → 404
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))
    assert result.verdict is Verdict.FAIL
    assert "/" in result.feedback
    assert "404" in result.feedback


def test_fails_on_rendered_internal_link_404(
    make_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """Rendered same-origin anchors are probed, catching generated dead links."""
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory(
            {"/": 200, "/collections/best-sellers": 200},
            bodies={
                "/": (
                    '<a href="/collections/best-sellers">Best sellers</a>'
                    '<a href="/blogs/guides">Guides</a>'
                    '<a href="mailto:help@example.test">Email</a>'
                    '<a href="#main-content">Skip</a>'
                    '<a href="/assets/app.css">Asset</a>'
                ),
            },
        ),
    )

    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))

    assert result.verdict is Verdict.FAIL
    assert result.details["links_checked"] == 2
    assert result.details["failures"] == [
        {
            "type": "link",
            "route": "/blogs/guides",
            "status": "404",
            "source_routes": ["/"],
        },
    ]
    assert "Rendered internal-link failures" in result.feedback
    assert "/blogs/guides" in result.feedback
    assert "linked from `/`" in result.feedback


def test_fails_when_factory_raises(
    make_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_failing_factory(RuntimeError("pnpm dev exit 1")),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))
    assert result.verdict is Verdict.FAIL
    assert result.details["phase"] == "factory_construct"
    assert "RuntimeError" in result.feedback


def test_fails_when_hydrogen_tree_missing(
    make_ctx: Callable[..., VerifierContext],
    artifact_dir: Path,
    data_dir: Path,
) -> None:
    app_dir = artifact_dir / "hydrogen" / "app"
    app_dir.rmdir()
    (artifact_dir / "hydrogen").rmdir()

    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({"/": 200}),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_homepage"))
    assert result.verdict is Verdict.FAIL
    assert "could not find the hydrogen tree" in result.feedback


# --------------------------------------------------------------------------- #
# Bucket axis integration — shared `_task_routes` module
# --------------------------------------------------------------------------- #


def test_unmapped_gen_task_passes_as_no_op(
    make_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """A ``gen_*`` task with no bucket mapping resolves to zero routes.

    The verifier returns PASS without booting a dev server — the empty
    route list is the bucket map's contract, not a wiring bug.
    """
    factory_calls: list[Path] = []
    verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({}, captured=factory_calls),
    )
    result = verifier.run(make_ctx(selected_task_id="gen_theme"))
    assert result.verdict is Verdict.PASS
    assert result.details["routes"] == []
    assert result.details["buckets"] == []
    assert factory_calls == []  # dev server never booted.


def test_redo_task_id_resolves_to_same_routes_as_base(
    make_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """``gen_homepage_redo_3`` strips the suffix and reuses the base routes."""
    base_verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({"/": 200}),
    )
    redo_verifier = Routes200Verifier(
        data_dir=data_dir,
        dev_server_factory=_factory({"/": 200}),
    )

    base_result = base_verifier.run(make_ctx(selected_task_id="gen_homepage"))
    redo_result = redo_verifier.run(
        make_ctx(selected_task_id="gen_homepage_redo_3"),
    )

    assert base_result.verdict is Verdict.PASS
    assert redo_result.verdict is Verdict.PASS
    assert base_result.details["routes"] == redo_result.details["routes"] == ["/"]
    assert base_result.details["buckets"] == redo_result.details["buckets"]


def test_consumes_same_task_routes_module_as_visual_judge(data_dir: Path) -> None:
    """Verifier ``details.routes`` matches ``routes_for_buckets`` directly.

    Locks in the shared bucket-axis module: any future divergence
    between ``visual_judge`` and ``routes_200`` would have to reach
    through ``_task_routes`` and so would surface here.
    """
    expected = routes_for_buckets(
        buckets_for_task("gen_collections"),
        data_dir,
    )
    # Spec §5.3 layer 2: gen_collections resolves to /collections plus
    # the first capped collection's handle.
    assert "/collections" in expected
    assert any(route.startswith("/collections/") for route in expected)
