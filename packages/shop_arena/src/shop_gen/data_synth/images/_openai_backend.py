"""OpenAI-compatible image generation backend (spec §5.1).

One backend class covers the official OpenAI API and any drop-in
compatible vendor (e.g. an internal proxy) — selected purely via the
``OPENAI_API_KEY`` and ``OPENAI_BASE_URL`` environment variables, the
SDK's own conventions. No vendor-specific code lives in this repo.

The backend renders a prompt via :mod:`shop_gen.data_synth.images._prompts`,
checks the content-addressed cache (:mod:`._cache`) before issuing an
``images.generate`` call, retries transient failures with exponential
backoff, and persists the resulting PNG bytes back into the cache so
re-runs pay zero API cost.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path
from typing import Final

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from shop_gen.data_synth.images._cache import cache_get, cache_put, compute_cache_key
from shop_gen.data_synth.images._prompts import PROMPT_VERSION, render_image_prompt

_OPENAI_BACKEND_NAME: Final[str] = "openai"
_OPENAI_EXTENSION: Final[str] = ".png"

_DEFAULT_MODEL: Final[str] = "gpt-image-1"
_DEFAULT_SIZE: Final[str] = "1024x1024"
_DEFAULT_QUALITY: Final[str] = "medium"

_API_KEY_ENV: Final[str] = "OPENAI_API_KEY"
_BASE_URL_ENV: Final[str] = "OPENAI_BASE_URL"

_HTTP_TIMEOUT_S: Final[float] = 60.0
"""Per-call timeout passed to :class:`AsyncOpenAI` (spec §5.3)."""

_MAX_RETRIES: Final[int] = 2
"""Number of retries for transient failures (spec §5.3)."""

_BACKOFF_SECONDS: Final[tuple[float, ...]] = (1.0, 4.0)
"""Exponential-backoff delays between retries (spec §5.3)."""

_logger = logging.getLogger(__name__)

_TRANSIENT_ERRORS: Final[tuple[type[Exception], ...]] = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
"""Errors retried with exponential backoff (spec §5.3).

``BadRequestError`` (content policy / shape errors) is deliberately
omitted — those failures are deterministic and the prompt or model
config needs to change.
"""


class OpenAIImageBackend:
    """Async OpenAI-compatible image-generation backend (spec §5.1).

    Construct with ``client=AsyncOpenAI(...)`` for tests or any
    custom-configured client; otherwise the backend builds a default
    client at first use that reads :data:`_API_KEY_ENV` and (optionally)
    :data:`_BASE_URL_ENV` from the environment.

    Attributes:
        name: Backend identifier (matches
            :data:`shop_gen.config.ImageBackend` literal).
        extension: PNG (``.png``).
        model: Forwarded to ``images.generate(model=...)``.
        size: Forwarded to ``images.generate(size=...)``.
        quality: Forwarded to ``images.generate(quality=...)``.
        prompt_version: Integer version of the prompt template, baked
            into the cache key so a template / brand-safety edit busts
            every cache entry on the next run.
    """

    name: str = _OPENAI_BACKEND_NAME
    extension: str = _OPENAI_EXTENSION

    def __init__(
        self,
        *,
        out_dir: Path,
        model: str = _DEFAULT_MODEL,
        size: str = _DEFAULT_SIZE,
        quality: str = _DEFAULT_QUALITY,
        client: AsyncOpenAI | None = None,
        prompt_version: int = PROMPT_VERSION,
    ) -> None:
        """Build the backend.

        Args:
            out_dir: Run workspace; the cache lives at
                ``<out_dir>/.shop_gen/image_cache/``.
            model: OpenAI-compatible model id (e.g. ``gpt-image-1``).
            size: Canvas size string forwarded to the API.
            quality: Quality tier (``low`` / ``medium`` / ``high`` /
                ``auto``). Forwarded to the API.
            client: Pre-built :class:`AsyncOpenAI` client. ``None``
                (default) defers construction until :meth:`render_async`
                is first called, at which point the env vars are read.
            prompt_version: Integer version of the prompt template.
        """
        self._out_dir = out_dir
        self.model = model
        self.size = size
        self.quality = quality
        self.prompt_version = prompt_version
        self._client = client
        self.last_render_was_cache_hit: bool = False

    async def render_async(
        self,
        *,
        handle: str,
        index: int,
        title: str,
        category: str,
        width: int,
        height: int,
    ) -> bytes:
        """Render one product image as PNG bytes (spec §5.1).

        Resolves the cache first. On miss issues ``images.generate``
        with exponential-backoff retries on transient failures and
        persists the response bytes back into the cache before returning.

        Args:
            handle: Product handle.
            index: 0-indexed image slot within the product.
            title: Product display title.
            category: Category label.
            width: Unused (passed for protocol compatibility); the
                actual canvas comes from :attr:`size`.
            height: Unused.

        Returns:
            Raw PNG bytes ready for ``Path.write_bytes``.

        Raises:
            BadRequestError: The model rejected the prompt (content
                policy / shape error). Not retried.
            RuntimeError: Every retry attempt failed.
        """
        del width, height
        prompt = render_image_prompt(title=title, category=category)
        key = compute_cache_key(
            prompt=prompt,
            model=self.model,
            size=self.size,
            quality=self.quality,
            prompt_version=self.prompt_version,
        )
        cached = cache_get(self._out_dir, key, extension=self.extension)
        if cached is not None:
            self.last_render_was_cache_hit = True
            return cached

        self.last_render_was_cache_hit = False
        client = self._ensure_client()
        payload = await _generate_with_retry(
            client=client,
            model=self.model,
            prompt=prompt,
            size=self.size,
            quality=self.quality,
            handle=handle,
            index=index,
        )
        cache_put(self._out_dir, key, payload, extension=self.extension)
        return payload

    def _ensure_client(self) -> AsyncOpenAI:
        """Return the cached :class:`AsyncOpenAI` or build one from env."""
        if self._client is not None:
            return self._client
        api_key = os.environ.get(_API_KEY_ENV)
        if not api_key:
            raise EnvironmentError(
                f"{_OPENAI_BACKEND_NAME!r} image backend requires {_API_KEY_ENV} "
                "in the environment",
            )
        base_url = os.environ.get(_BASE_URL_ENV)
        kwargs: dict[str, object] = {"api_key": api_key, "timeout": _HTTP_TIMEOUT_S}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncOpenAI(**kwargs)  # type: ignore[arg-type]
        self._client = client
        return client


async def _generate_with_retry(
    *,
    client: AsyncOpenAI,
    model: str,
    prompt: str,
    size: str,
    quality: str,
    handle: str,
    index: int,
) -> bytes:
    """Issue ``images.generate`` with bounded exponential-backoff retries."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.images.generate(
                model=model,
                prompt=prompt,
                size=size,  # type: ignore[arg-type]
                quality=quality,  # type: ignore[arg-type]
                n=1,
            )
            return _decode_first_image(response, handle=handle, index=index)
        except BadRequestError as exc:
            raise RuntimeError(
                f"openai image backend rejected prompt for {handle!r} index {index}: {exc}",
            ) from exc
        except _TRANSIENT_ERRORS as exc:
            last_exc = exc
            if attempt >= _MAX_RETRIES:
                break
            delay = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
            _logger.warning(
                "openai image backend transient error for %r index %d (attempt %d/%d): %s; "
                "retrying in %.1fs",
                handle,
                index,
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(
        f"openai image backend failed for {handle!r} index {index} after "
        f"{_MAX_RETRIES + 1} attempts: {last_exc}",
    ) from last_exc


def _decode_first_image(response: object, *, handle: str, index: int) -> bytes:
    """Decode ``response.data[0].b64_json`` into raw PNG bytes."""
    data = getattr(response, "data", None)
    if not data:
        raise RuntimeError(
            f"openai image backend returned an empty 'data' for {handle!r} index {index}",
        )
    first = data[0]
    b64 = getattr(first, "b64_json", None)
    if not isinstance(b64, str) or not b64:
        raise RuntimeError(
            f"openai image backend returned no b64_json for {handle!r} index {index}",
        )
    return base64.b64decode(b64)


__all__ = ["OpenAIImageBackend"]
