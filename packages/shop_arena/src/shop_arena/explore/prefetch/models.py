"""Typed result records and exception for the §5.9 prefetch step.

These models are persisted as ``prefetch.json`` next to the saved bodies
under ``run_dir/artifact/prefetch/``. Keeping them in their own module
lets stats / coverage / synthesize import the public types without
pulling in the ``httpx`` runner.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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
    """Summary returned by :func:`shop_arena.explore.prefetch.run`.

    Persisted as ``prefetch.json`` under ``dest_dir``.

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
