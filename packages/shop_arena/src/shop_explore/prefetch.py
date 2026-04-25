"""Deterministic HTTP prefetch step for ``shop_explore``.

Implements §5.9 of the ShopExplore spec
(``docs/specs/shop_arena/shop_explore.md``): a small, fixed-URL HTTP
fetch that seeds the harness ``run_dir/artifact/prefetch/`` with enough
storefront context for the planner to reason about coverage.

No LLM. No browsing. No crawler. The agents do all further interaction
with the shop through the playwright skill.

Public surface:

* :class:`PrefetchEntry` — per-URL outcome record.
* :class:`PrefetchResult` — summary written to ``prefetch.json``.
* :class:`ShopUnreachableError` — raised on bot-block / fatal index.
* :func:`run` — fetch a storefront into ``dest_dir``.

Bot-block detection (spec §5.9): if ``robots.txt`` disallows ``*`` on
``/``, or ``/`` returns 403/429/503, or ``/`` body matches a Cloudflare
challenge marker, :func:`run` raises :class:`ShopUnreachableError`
before fetching the rest of the URL list. Network errors on
``robots.txt`` or ``/`` are also fatal; errors on subsequent URLs are
recorded in :class:`PrefetchResult` but do not abort the run.
"""

from __future__ import annotations

import json
import time
import urllib.robotparser
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict

from shop_explore._version import __version__

DEFAULT_USER_AGENT = f"ShopExplore/{__version__} (+https://github.com/Shopify/shop-gym)"
"""Default User-Agent sent on every prefetch request (spec §5.9)."""

DEFAULT_RATE_LIMIT_MS = 500
"""Minimum gap between requests, in milliseconds (spec §5.9)."""

DEFAULT_TIMEOUT_SECONDS = 30.0
"""Per-request timeout (not the global run timeout)."""

_BOT_BLOCK_STATUS = frozenset({403, 429, 503})
"""HTTP statuses on ``/`` treated as bot-block signals."""

_CLOUDFLARE_MARKERS: tuple[str, ...] = (
    "cf-browser-verification",
    "__cf_chl_",
    "Just a moment...",
    "Checking your browser before accessing",
    "Attention Required! | Cloudflare",
    "cf-challenge-running",
)
"""Substring markers that indicate a Cloudflare interstitial."""

# Ordered list of (relative path, dest filename). The first two entries
# (robots.txt, then "/") are the gating fetches; everything afterwards
# is best-effort. ``dest filename`` is relative to ``dest_dir`` and may
# contain a single subdirectory level (``policies/`` or ``pages/``).
_FETCH_PLAN: tuple[tuple[str, str], ...] = (
    ("/robots.txt", "robots.txt"),
    ("/", "index.html"),
    ("/sitemap.xml", "sitemap.xml"),
    ("/products.json?limit=50", "products.json"),
    ("/collections.json?limit=50", "collections.json"),
    ("/search/suggest.json?q=a&resources[type]=product", "search_suggest.json"),
    ("/cart.js", "cart.js"),
    ("/cart", "cart.html"),
    ("/search", "search.html"),
    ("/policies/refund-policy", "policies/refund-policy.html"),
    ("/policies/privacy-policy", "policies/privacy-policy.html"),
    ("/policies/terms-of-service", "policies/terms-of-service.html"),
    ("/policies/shipping-policy", "policies/shipping-policy.html"),
    ("/pages/about", "pages/about.html"),
    ("/pages/contact", "pages/contact.html"),
    ("/pages/faq", "pages/faq.html"),
)


class ShopUnreachableError(RuntimeError):
    """Raised when the storefront is bot-blocked or its index is fatal.

    Attributes:
        reason: One of ``"robots_disallow"``, ``"http_status"``,
            ``"cloudflare_challenge"``, ``"network_error"``.
        detail: Human-readable detail (URL, status, marker, etc.).
    """

    def __init__(self, reason: str, *, detail: str) -> None:
        super().__init__(f"shop unreachable ({reason}): {detail}")
        self.reason = reason
        self.detail = detail


class PrefetchEntry(BaseModel):
    """Per-URL outcome record persisted in ``prefetch.json``.

    Attributes:
        url: Absolute URL that was fetched.
        path: The relative path component (e.g. ``"/products.json"``).
        status: HTTP status, or ``None`` on transport-level failure.
        content_type: ``Content-Type`` response header, if any.
        bytes: Body length actually written to disk (``0`` on failure).
        saved_to: Filename relative to ``dest_dir``, or ``None`` if the
            response was not persisted.
        error: Short error string when the fetch failed, else ``None``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    path: str
    status: int | None
    content_type: str | None
    bytes: int
    saved_to: str | None
    error: str | None = None


class PrefetchResult(BaseModel):
    """Summary returned by :func:`run` and persisted as ``prefetch.json``.

    Attributes:
        base_url: The storefront base URL the run was anchored at.
        user_agent: User-Agent header used for every request.
        started_at: ISO-8601 UTC timestamp of the first request.
        finished_at: ISO-8601 UTC timestamp after the last request.
        entries: One :class:`PrefetchEntry` per URL attempted, in fetch
            order.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    user_agent: str
    started_at: str
    finished_at: str
    entries: tuple[PrefetchEntry, ...]


def run(
    url: str,
    *,
    dest_dir: Path,
    user_agent: str = DEFAULT_USER_AGENT,
    rate_limit_ms: int = DEFAULT_RATE_LIMIT_MS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> PrefetchResult:
    """Fetch the spec §5.9 URL list into ``dest_dir``.

    Writes each successful response body verbatim under ``dest_dir`` per
    the layout in §5.4, plus a ``prefetch.json`` summary describing what
    was attempted and the outcome of each request.

    Args:
        url: Storefront base URL. Must include scheme + host.
        dest_dir: Directory to seed with the prefetch artifacts. Created
            if missing; subdirectories ``policies/`` and ``pages/`` are
            created on demand.
        user_agent: ``User-Agent`` header to send on every request.
        rate_limit_ms: Minimum gap between requests, in milliseconds.
            Must be ``>= 0``.
        timeout: Per-request timeout in seconds.
        client: Optional pre-configured ``httpx.Client``. When provided,
            the caller owns its lifecycle; ``user_agent`` and ``timeout``
            are still applied per request via overrides. Mainly used by
            tests.

    Returns:
        A :class:`PrefetchResult` summarizing every URL attempted.

    Raises:
        ShopUnreachableError: If ``robots.txt`` disallows ``*`` on ``/``,
            ``/`` returns 403/429/503 / non-2xx, ``/`` body matches a
            Cloudflare challenge marker, or a transport-level error
            occurs while fetching ``robots.txt`` or ``/``.
        ValueError: If ``rate_limit_ms`` is negative.
    """
    if rate_limit_ms < 0:
        raise ValueError(f"rate_limit_ms must be >= 0, got {rate_limit_ms}")

    base_root = _normalize_base(url)
    dest_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(UTC).isoformat()
    entries: list[PrefetchEntry] = []
    pacer = _RatePacer(rate_limit_ms / 1000.0)

    owns_client = client is None
    http_client = client or httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": user_agent},
    )

    try:
        for index, (path, filename) in enumerate(_FETCH_PLAN):
            pacer.wait()
            absolute = base_root + path
            entry = _fetch_one(
                http_client,
                absolute=absolute,
                path=path,
                filename=filename,
                dest_dir=dest_dir,
                user_agent=user_agent,
                timeout=timeout,
            )
            entries.append(entry)

            # Gate on the first two requests: robots.txt and "/".
            if index == 0:
                _enforce_robots(entry, dest_dir=dest_dir, base_root=base_root)
            elif index == 1:
                _enforce_index(entry, dest_dir=dest_dir)
    finally:
        if owns_client:
            http_client.close()

    finished_at = datetime.now(UTC).isoformat()
    result = PrefetchResult(
        base_url=base_root,
        user_agent=user_agent,
        started_at=started_at,
        finished_at=finished_at,
        entries=tuple(entries),
    )
    (dest_dir / "prefetch.json").write_text(
        json.dumps(result.model_dump(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


class _RatePacer:
    """Sleep just enough between calls to honor a minimum gap."""

    def __init__(self, min_gap_seconds: float) -> None:
        self._min_gap = min_gap_seconds
        self._last: float | None = None

    def wait(self) -> None:
        if self._min_gap <= 0:
            return
        now = time.monotonic()
        if self._last is not None:
            elapsed = now - self._last
            remaining = self._min_gap - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last = time.monotonic()


def _normalize_base(url: str) -> str:
    """Return scheme://host, stripping any path/query/fragment."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"url must include scheme and host, got: {url!r}")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _fetch_one(
    client: httpx.Client,
    *,
    absolute: str,
    path: str,
    filename: str,
    dest_dir: Path,
    user_agent: str,
    timeout: float,
) -> PrefetchEntry:
    """Issue one request and persist the body. Never raises."""
    try:
        response = client.get(
            absolute,
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        return PrefetchEntry(
            url=absolute,
            path=path,
            status=None,
            content_type=None,
            bytes=0,
            saved_to=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    body = response.content
    saved_to: str | None = None
    if response.status_code == HTTPStatus.OK and body:
        target = dest_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        saved_to = filename

    return PrefetchEntry(
        url=absolute,
        path=path,
        status=response.status_code,
        content_type=response.headers.get("content-type"),
        bytes=len(body),
        saved_to=saved_to,
    )


def _enforce_robots(entry: PrefetchEntry, *, dest_dir: Path, base_root: str) -> None:
    """Abort if ``robots.txt`` disallows ``*`` on ``/``.

    A missing or 4xx/5xx ``robots.txt`` is treated as "no rules"
    (RFC 9309 §2.3) and does *not* block the run; a transport failure
    *does* block it because we cannot tell whether the host is reachable.
    """
    if entry.error is not None:
        raise ShopUnreachableError("network_error", detail=f"robots.txt: {entry.error}")
    if entry.status != HTTPStatus.OK or entry.saved_to is None:
        return
    text = (dest_dir / entry.saved_to).read_text(encoding="utf-8", errors="replace")
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    if not parser.can_fetch("*", base_root + "/"):
        raise ShopUnreachableError(
            "robots_disallow",
            detail="robots.txt forbids User-Agent '*' on /",
        )


def _enforce_index(entry: PrefetchEntry, *, dest_dir: Path) -> None:
    """Abort if the storefront homepage looks bot-blocked or fatal."""
    if entry.error is not None:
        raise ShopUnreachableError("network_error", detail=f"/: {entry.error}")
    if entry.status in _BOT_BLOCK_STATUS:
        raise ShopUnreachableError(
            "http_status",
            detail=f"/ returned HTTP {entry.status}",
        )
    if entry.status is None or entry.status >= HTTPStatus.BAD_REQUEST.value:
        raise ShopUnreachableError(
            "http_status",
            detail=f"/ returned HTTP {entry.status}",
        )
    if entry.saved_to is None:
        return
    body = (dest_dir / entry.saved_to).read_bytes()
    text = body.decode("utf-8", errors="replace")
    for marker in _CLOUDFLARE_MARKERS:
        if marker in text:
            raise ShopUnreachableError(
                "cloudflare_challenge",
                detail=f"/ contains Cloudflare marker {marker!r}",
            )
