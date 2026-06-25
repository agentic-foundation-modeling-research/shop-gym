"""``routes_200`` build-loop verifier (impl plan T4.1, spec §5.3 + §5.8).

Boots a transient dev server against the hydrogen tree under
``ctx.artifact_dir / "hydrogen"`` and asserts every route resolved by
the **task → buckets → routes** axis (spec §5.3) returns a 2xx HTTP
status. For every successful HTML route response, it also extracts
rendered same-origin ``<a href>`` targets and probes those internal
links. This catches generated dead navigation, footer, and CTA links
without encoding shop-specific labels or handles into the verifier.

Applies to every ``gen_*`` task: each task id is run through
:func:`shop_arena.gen.build.verifiers._task_routes.buckets_for_task` to
strip a trailing ``_redo_<n>`` suffix and reuse the base task's
bucket set; :func:`routes_for_buckets` then produces the route list.

The dev-server lifecycle is injected through the
:class:`~shop_arena.gen.final_eval.playwright_smoke.DevServerFactory`
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

from html.parser import HTMLParser
from pathlib import Path
from typing import Final
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_arena.gen.build.verifiers._task_routes import (
    DEFAULT_CAPS,
    buckets_for_task,
    routes_for_buckets,
)
from shop_arena.gen.final_eval.playwright_smoke import DevServerFactory

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

_SKIPPED_LINK_SCHEMES: Final[frozenset[str]] = frozenset(
    {"blob", "data", "javascript", "mailto", "tel"},
)
"""Non-navigation ``href`` schemes ignored by rendered-link checks."""

_SKIPPED_LINK_PREFIXES: Final[tuple[str, ...]] = (
    "/__manifest",
    "/assets/",
    "/favicon",
)
"""Internal paths that are static/framework assets, not storefront routes."""

_SKIPPED_LINK_EXTENSIONS: Final[tuple[str, ...]] = (
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".png",
    ".svg",
    ".webp",
    ".xml",
)
"""Static file extensions skipped by rendered-link checks."""


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
        app_dir: Path = Path(_HYDROGEN_DIRNAME),
        request_timeout_s: float = _REQUEST_TIMEOUT_S,
    ) -> None:
        """Build the verifier with the bucket axis + dev-server seam.

        Args:
            data_dir: Directory containing the published
                ``collections.json`` / ``products.json`` /
                ``pages.json`` files. Forwarded to
                :func:`shop_arena.gen.build.verifiers._task_routes.routes_for_buckets`
                so resolved routes carry real handles.
            dev_server_factory: Callable that boots a transient dev
                server. See
                :class:`~shop_arena.gen.final_eval.playwright_smoke.DevServerFactory`.
            app_dir: Storefront app directory relative to
                ``VerifierContext.artifact_dir``. Defaults to
                ``hydrogen`` for backward compatibility.
            request_timeout_s: Per-request HTTP timeout. Defaults to
                :data:`_REQUEST_TIMEOUT_S`.
        """
        self._data_dir = data_dir
        self._dev_server_factory = dev_server_factory
        self._app_dir = app_dir
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

            ``FAIL`` with one bullet per non-2xx route or rendered
            internal-link response otherwise.

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

        app_dir = ctx.artifact_dir / self._app_dir
        if not app_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    "routes_200 could not find the hydrogen tree at "
                    f"`{self._app_dir.as_posix()}/`. Did `clone_template` run?"
                ),
                details={"hydrogen_dir": str(app_dir), "exists": False},
            )

        return self._probe_with_server(
            hydrogen_dir=app_dir,
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

        route_failures: list[tuple[str, str]] = []
        route_responses: list[tuple[str, httpx.Response]] = []
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
                        route_failures.append((route, f"error: {exc}"))
                        continue
                    if not _is_2xx(response.status_code):
                        route_failures.append((route, str(response.status_code)))
                        continue
                    route_responses.append((route, response))

                link_failures = _probe_rendered_internal_links(
                    client=client,
                    route_responses=route_responses,
                )
        except Exception as exc:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(f"routes_200 dev server lifecycle raised {type(exc).__name__}: {exc}"),
                details={"phase": "dev_server", "error": str(exc)},
            )

        if not route_failures and not link_failures:
            links_checked = len(_rendered_internal_link_map(route_responses))
            return VerifierResult(
                verdict=Verdict.PASS,
                details={
                    "buckets": list(buckets),
                    "routes": list(routes),
                    "links_checked": links_checked,
                    "all_ok": True,
                },
            )
        failures: list[dict[str, object]] = [
            {"type": "route", "route": route, "status": status}
            for route, status in route_failures
        ]
        failures.extend(
            {
                "type": "link",
                "route": failure.route,
                "status": failure.status,
                "source_routes": list(failure.source_routes),
            }
            for failure in link_failures
        )
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=_render_failure_markdown(
                routes=routes,
                route_failures=route_failures,
                link_failures=link_failures,
            ),
            details={
                "buckets": list(buckets),
                "routes": list(routes),
                "links_checked": len(_rendered_internal_link_map(route_responses)),
                "failures": failures,
            },
        )


def _is_2xx(status_code: int) -> bool:
    """Return ``True`` iff ``status_code`` falls in ``[200, 300)``."""
    return _HTTP_OK_FLOOR <= status_code < _HTTP_OK_CEIL


def _render_failure_markdown(
    *,
    routes: tuple[str, ...],
    route_failures: list[tuple[str, str]],
    link_failures: list[_LinkFailure],
) -> str:
    """Render the failure feedback body."""
    total_failures = len(route_failures) + len(link_failures)
    lines = [
        f"`routes_200` failed: {total_failures} rendered route/link "
        "probe(s) did not return HTTP 2xx.",
        "",
    ]
    if route_failures:
        lines.append(f"Route failures ({len(route_failures)} of {len(routes)} routes):")
        lines.extend(f"- `{route}` → {status}" for route, status in route_failures)
    if link_failures:
        if route_failures:
            lines.append("")
        lines.append(f"Rendered internal-link failures ({len(link_failures)}):")
        lines.extend(
            "- `{route}` → {status} (linked from {sources})".format(
                route=failure.route,
                status=failure.status,
                sources=", ".join(f"`{source}`" for source in failure.source_routes),
            )
            for failure in link_failures
        )
    return "\n".join(lines)


class _AnchorHrefParser(HTMLParser):
    """Extract ``href`` values from rendered HTML anchors."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record every non-empty anchor ``href``."""
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value)
                return


class _LinkFailure:
    """A rendered internal link that did not resolve successfully."""

    def __init__(
        self,
        *,
        route: str,
        status: str,
        source_routes: tuple[str, ...],
    ) -> None:
        self.route = route
        self.status = status
        self.source_routes = source_routes


def _probe_rendered_internal_links(
    *,
    client: httpx.Client,
    route_responses: list[tuple[str, httpx.Response]],
) -> list[_LinkFailure]:
    """Probe every unique internal anchor rendered by the successful routes."""
    link_sources = _rendered_internal_link_map(route_responses)
    failures: list[_LinkFailure] = []
    for link, sources in sorted(link_sources.items()):
        try:
            response = client.get(link, follow_redirects=True)
        except httpx.HTTPError as exc:
            failures.append(
                _LinkFailure(
                    route=link,
                    status=f"error: {exc}",
                    source_routes=sources,
                ),
            )
            continue
        if not _is_2xx(response.status_code):
            failures.append(
                _LinkFailure(
                    route=link,
                    status=str(response.status_code),
                    source_routes=sources,
                ),
            )
    return failures


def _rendered_internal_link_map(
    route_responses: list[tuple[str, httpx.Response]],
) -> dict[str, tuple[str, ...]]:
    """Return internal rendered links mapped to the routes that emitted them."""
    link_sources: dict[str, set[str]] = {}
    for source_route, response in route_responses:
        for href in _extract_internal_links(response):
            link_sources.setdefault(href, set()).add(source_route)
    return {
        link: tuple(sorted(sources))
        for link, sources in sorted(link_sources.items())
    }


def _extract_internal_links(response: httpx.Response) -> tuple[str, ...]:
    """Extract normalized same-origin route links from a rendered HTML response."""
    parser = _AnchorHrefParser()
    parser.feed(response.text)
    links: set[str] = set()
    for href in parser.hrefs:
        normalized = _normalize_internal_href(href=href, page_url=str(response.url))
        if normalized is not None:
            links.add(normalized)
    return tuple(sorted(links))


def _normalize_internal_href(*, href: str, page_url: str) -> str | None:
    """Return a route path for a same-origin anchor ``href`` or ``None``."""
    stripped = href.strip()
    if not stripped or stripped == "#" or stripped.startswith("#"):
        return None
    parsed_page = urlparse(page_url)
    parsed = urlparse(urljoin(page_url, stripped))
    if parsed.scheme in _SKIPPED_LINK_SCHEMES:
        return None
    if (parsed.scheme, parsed.netloc) != (parsed_page.scheme, parsed_page.netloc):
        return None
    path = parsed.path or "/"
    if _should_skip_internal_path(path):
        return None
    return urlunparse(("", "", path, "", parsed.query, ""))


def _should_skip_internal_path(path: str) -> bool:
    """Return ``True`` for same-origin hrefs that are not storefront routes."""
    if any(path.startswith(prefix) for prefix in _SKIPPED_LINK_PREFIXES):
        return True
    return path.endswith(_SKIPPED_LINK_EXTENSIONS)


__all__ = ["Routes200Verifier"]
