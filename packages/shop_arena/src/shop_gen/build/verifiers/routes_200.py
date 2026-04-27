"""``routes_200`` build-loop verifier (spec §5.5.3).

Boots a transient dev server against the hydrogen tree under
``ctx.artifact_dir / "hydrogen"`` and asserts every configured route
returns HTTP 200. Applicable tasks (``gen_navigation``, ``gen_homepage``,
``gen_collections``, ``gen_product``, ``gen_info_pages``, and
``consolidate``) each map to a list of route paths the verifier hits
sequentially.

The dev-server lifecycle is injected through the
:class:`DevServerFactory` seam:

* Production callers pass the default factory (T5.6 wires it up; v0.1
  does not ship a working ``pnpm dev`` driver here — the spec
  explicitly defers the live integration to the loop driver).
* Tests inject a stub factory that yields an in-process HTTP server,
  exercising the verdict-rendering branches without needing Node.

Without a factory the verifier raises at instantiation rather than
silently advisory'ing — calling ``routes_200`` without a dev-server
backing is a wiring bug, not a runtime condition.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

import httpx

from harness.verifiers import Verdict, VerifierContext, VerifierResult

_NAME: Final[str] = "routes_200"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_DIR: Final[str] = "hydrogen"
"""Path of the hydrogen tree relative to ``VerifierContext.artifact_dir``."""

_REQUEST_TIMEOUT_S: Final[float] = 10.0
"""Per-request HTTP timeout for the dev-server probes."""

_HTTP_OK: Final[int] = 200
"""HTTP success status code (matches the spec table requirement)."""


@runtime_checkable
class DevServerFactory(Protocol):
    """Callable that boots a transient dev server and yields its base URL.

    The returned context manager owns the subprocess lifecycle: it
    starts the server on entry, yields ``http://127.0.0.1:<port>`` once
    the server is reachable, and tears the process down on exit
    (including on exception).

    Implementations are free to use the existing
    :func:`shop_gen.build.sidecar.sidecar_lifecycle` helper, a custom
    ``pnpm dev`` driver, or — for tests — a Python ``http.server``
    spun up in a thread.
    """

    def __call__(self, hydrogen_dir: Path) -> AbstractContextManager[str]:
        """Start a dev server bound to ``hydrogen_dir`` and yield ``base_url``.

        Args:
            hydrogen_dir: Filesystem path the dev server should be
                rooted at (typically the freshly built hydrogen tree).

        Returns:
            A context manager whose ``__enter__`` returns
            ``"http://127.0.0.1:<port>"``.
        """
        ...


class Routes200Verifier:
    """Asserts every configured route returns HTTP 200 from a dev server.

    Attributes:
        name: ``"routes_200"`` — used as the per-verifier telemetry
            filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        task_routes: Mapping[str, Sequence[str]],
        dev_server_factory: DevServerFactory,
        request_timeout_s: float = _REQUEST_TIMEOUT_S,
    ) -> None:
        """Build the verifier with the per-task route map + dev-server seam.

        Args:
            task_routes: Mapping from task id to the list of route
                paths to probe (each path starts with ``/``). Typical
                v0.1 mapping wires every "page-shaped" task plus
                ``consolidate`` per spec §5.5.3 + §5.5.4. Empty
                sequences are allowed: the verifier returns ``PASS``
                without booting a dev server when no routes are
                configured for a task.
            dev_server_factory: Callable that boots a transient dev
                server. See :class:`DevServerFactory`.
            request_timeout_s: Per-request HTTP timeout. Defaults to
                :data:`_REQUEST_TIMEOUT_S`.

        Raises:
            ValueError: ``task_routes`` is empty (a routes_200
                verifier with no applicable tasks is a wiring bug).
        """
        if not task_routes:
            raise ValueError(
                "Routes200Verifier requires at least one task in `task_routes`; "
                "got an empty mapping.",
            )
        self._task_routes: dict[str, tuple[str, ...]] = {
            task_id: tuple(routes) for task_id, routes in task_routes.items()
        }
        self._dev_server_factory = dev_server_factory
        self._request_timeout_s = request_timeout_s

    def applies_to(self, task_id: str) -> bool:
        """Match every task id present in ``task_routes`` (spec §5.5.3).

        Args:
            task_id: Selected task id.

        Returns:
            ``True`` iff ``task_id`` was configured at construction.
        """
        return task_id in self._task_routes

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Boot a dev server and probe every configured route for ``ctx.selected_task_id``.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` to locate
                the hydrogen tree; ``ctx.runtime`` is unused.

        Returns:
            ``PASS`` when every probed route returned HTTP 200.
            ``FAIL`` with one ``- /path: <status>`` bullet per
            non-200 response otherwise.

            A missing hydrogen tree returns ``FAIL`` with explanatory
            feedback so the loop can recover.

            ``FAIL`` when the dev server cannot be reached (``httpx``
            connection error). The feedback embeds the raw error
            message so the next iteration's agent sees the cause.
        """
        routes = self._task_routes.get(ctx.selected_task_id, ())
        if not routes:
            # Configured task with an empty route list — treat as PASS
            # rather than crashing. The spec is silent on this corner
            # but a no-op verdict is the least surprising default.
            return VerifierResult(
                verdict=Verdict.PASS,
                details={"routes": [], "task_id": ctx.selected_task_id},
            )

        hydrogen_dir = ctx.artifact_dir / _HYDROGEN_DIR
        if not hydrogen_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "routes_200 could not find the hydrogen tree at "
                    f"`{_HYDROGEN_DIR}/`. Did `clone_template` run?"
                ),
                details={"hydrogen_dir": str(hydrogen_dir), "exists": False},
            )

        return self._probe_with_server(hydrogen_dir=hydrogen_dir, routes=routes)

    def _probe_with_server(
        self,
        *,
        hydrogen_dir: Path,
        routes: tuple[str, ...],
    ) -> VerifierResult:
        """Drive the dev-server context manager and probe each route.

        Separated from :meth:`run` so the workspace-precondition
        branches above stay flat and easy to read.

        Args:
            hydrogen_dir: Filesystem path the dev server runs against.
            routes: Routes to probe, in source order.

        Returns:
            See :meth:`run` for the verdict mapping.
        """
        try:
            cm = self._dev_server_factory(hydrogen_dir)
        except Exception as exc:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"routes_200 failed to start the dev server: {type(exc).__name__}: {exc}"
                ),
                details={"phase": "factory_construct", "error": str(exc)},
            )

        failures: list[tuple[str, str]] = []
        try:
            with (
                cm as base_url,
                httpx.Client(
                    base_url=base_url,
                    timeout=self._request_timeout_s,
                ) as client,
            ):
                for route in routes:
                    try:
                        response = client.get(route)
                    except httpx.HTTPError as exc:
                        failures.append((route, f"error: {exc}"))
                        continue
                    if response.status_code != _HTTP_OK:
                        failures.append((route, str(response.status_code)))
        except Exception as exc:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(f"routes_200 dev server lifecycle raised {type(exc).__name__}: {exc}"),
                details={"phase": "dev_server", "error": str(exc)},
            )

        if not failures:
            return VerifierResult(
                verdict=Verdict.PASS,
                details={"routes": list(routes), "all_ok": True},
            )
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=_render_failure_markdown(routes=routes, failures=failures),
            details={
                "routes": list(routes),
                "failures": [{"route": route, "status": status} for route, status in failures],
            },
        )


def _render_failure_markdown(
    *,
    routes: tuple[str, ...],
    failures: list[tuple[str, str]],
) -> str:
    """Render the failure feedback body."""
    lines = [
        f"`routes_200` failed: {len(failures)} of {len(routes)} probed "
        "route(s) did not return HTTP 200.",
        "",
        "Failures:",
    ]
    lines.extend(f"- `{route}` → {status}" for route, status in failures)
    return "\n".join(lines)


__all__ = ["DevServerFactory", "Routes200Verifier"]
