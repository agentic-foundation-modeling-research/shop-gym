"""``routes_200`` build-loop verifier (impl plan T4.1, spec §5.3 + §5.8).

Boots a transient dev server against the hydrogen tree under
``ctx.artifact_dir / "hydrogen"`` and asserts every route resolved by
the **task → buckets → routes** axis (spec §5.3) returns a 2xx HTTP
status. Applies to every ``gen_*`` task: each task id is run through
:func:`shop_gen.build.verifiers._task_routes.buckets_for_task` to
strip a trailing ``_redo_<n>`` suffix and reuse the base task's
bucket set; :func:`routes_for_buckets` then produces the route list.

The dev-server lifecycle is injected through the
:class:`~shop_gen.final_eval.playwright_smoke.DevServerFactory`
seam shared with ``visual_judge``:

* Production callers pass the ``pnpm dev`` runner (lands in T6.1).
* Tests inject a stub factory yielding an in-process HTTP server,
  exercising the verdict-rendering branches without needing Node.

Without a factory the verifier raises at instantiation rather than
silently advisory'ing — calling ``routes_200`` without a dev-server
backing is a wiring bug, not a runtime condition.

Module is import-safe: no I/O, no env reads, no side effects at
import time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import httpx

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_gen.build.verifiers._task_routes import (
    DEFAULT_CAPS,
    buckets_for_task,
    routes_for_buckets,
)
from shop_gen.final_eval.playwright_smoke import DevServerFactory

_NAME: Final[str] = "routes_200"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_DIRNAME: Final[str] = "hydrogen"
"""Path of the hydrogen tree relative to ``VerifierContext.artifact_dir``."""

_REQUEST_TIMEOUT_S: Final[float] = 10.0
"""Per-request HTTP timeout for the dev-server probes."""

_HTTP_OK_FLOOR: Final[int] = 200
"""Inclusive lower bound of the accepted status range (2xx)."""

_HTTP_OK_CEIL: Final[int] = 300
"""Exclusive upper bound of the accepted status range (2xx)."""


class Routes200Verifier:
    """Asserts every bucket route returns HTTP 2xx from a dev server.

    Attributes:
        name: ``"routes_200"`` — used as the per-verifier telemetry
            filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        data_dir: Path,
        dev_server_factory: DevServerFactory,
        request_timeout_s: float = _REQUEST_TIMEOUT_S,
    ) -> None:
        """Build the verifier with the bucket axis + dev-server seam.

        Args:
            data_dir: Directory containing the published
                ``collections.json`` / ``products.json`` /
                ``pages.json`` files. Forwarded to
                :func:`shop_gen.build.verifiers._task_routes.routes_for_buckets`
                so resolved routes carry real handles.
            dev_server_factory: Callable that boots a transient dev
                server. See
                :class:`~shop_gen.final_eval.playwright_smoke.DevServerFactory`.
            request_timeout_s: Per-request HTTP timeout. Defaults to
                :data:`_REQUEST_TIMEOUT_S`.
        """
        self._data_dir = data_dir
        self._dev_server_factory = dev_server_factory
        self._request_timeout_s = request_timeout_s

    def applies_to(self, task_id: str) -> bool:
        """Match every ``gen_*`` task (impl plan T4.1).

        Args:
            task_id: Selected task id.

        Returns:
            ``True`` iff ``task_id`` starts with ``gen_``.
        """
        return task_id.startswith("gen_")

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Boot a dev server and probe every bucket route for ``ctx.selected_task_id``.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` to locate
                the hydrogen tree; ``ctx.runtime`` is unused.

        Returns:
            ``PASS`` when every probed route returned a 2xx status (or
            when the resolved route list is empty — a no-op for tasks
            outside the bucket map).

            ``FAIL`` with one ``- /path: <status>`` bullet per non-2xx
            response otherwise.

            A missing hydrogen tree returns ``FAIL`` with explanatory
            feedback so the loop can recover.

            ``FAIL`` when the dev server cannot be reached (``httpx``
            connection error). The feedback embeds the raw error
            message so the next iteration's agent sees the cause.
        """
        buckets = buckets_for_task(ctx.selected_task_id)
        routes = routes_for_buckets(buckets, self._data_dir, caps=DEFAULT_CAPS)
        if not routes:
            # Unknown task id (no buckets) or buckets that produce no
            # routes against the current dataset — treat as PASS rather
            # than crashing. The bucket map controls applicability;
            # callers that want strict scoping pass a stricter
            # ``applicable_tasks`` higher up.
            return VerifierResult(
                verdict=Verdict.PASS,
                details={
                    "task_id": ctx.selected_task_id,
                    "buckets": sorted(buckets),
                    "routes": [],
                },
            )

        hydrogen_dir = ctx.artifact_dir / _HYDROGEN_DIRNAME
        if not hydrogen_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "routes_200 could not find the hydrogen tree at "
                    f"`{_HYDROGEN_DIRNAME}/`. Did `clone_template` run?"
                ),
                details={"hydrogen_dir": str(hydrogen_dir), "exists": False},
            )

        return self._probe_with_server(
            hydrogen_dir=hydrogen_dir,
            routes=routes,
            buckets=tuple(sorted(buckets)),
        )

    def _probe_with_server(
        self,
        *,
        hydrogen_dir: Path,
        routes: tuple[str, ...],
        buckets: tuple[str, ...],
    ) -> VerifierResult:
        """Drive the dev-server context manager and probe each route.

        Separated from :meth:`run` so the workspace-precondition
        branches above stay flat and easy to read.

        Args:
            hydrogen_dir: Filesystem path the dev server runs against.
            routes: Routes to probe, in deterministic sorted order.
            buckets: Sorted bucket names recorded in ``details`` for
                debugging.

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
                    if not _is_2xx(response.status_code):
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
                details={
                    "buckets": list(buckets),
                    "routes": list(routes),
                    "all_ok": True,
                },
            )
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=_render_failure_markdown(routes=routes, failures=failures),
            details={
                "buckets": list(buckets),
                "routes": list(routes),
                "failures": [{"route": route, "status": status} for route, status in failures],
            },
        )


def _is_2xx(status_code: int) -> bool:
    """Return ``True`` iff ``status_code`` falls in ``[200, 300)``."""
    return _HTTP_OK_FLOOR <= status_code < _HTTP_OK_CEIL


def _render_failure_markdown(
    *,
    routes: tuple[str, ...],
    failures: list[tuple[str, str]],
) -> str:
    """Render the failure feedback body."""
    lines = [
        f"`routes_200` failed: {len(failures)} of {len(routes)} probed "
        "route(s) did not return HTTP 2xx.",
        "",
        "Failures:",
    ]
    lines.extend(f"- `{route}` → {status}" for route, status in failures)
    return "\n".join(lines)


__all__ = ["Routes200Verifier"]
