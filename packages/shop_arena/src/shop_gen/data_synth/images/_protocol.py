"""Image-backend protocols for the ``gen_images`` step (spec §5.1).

Two protocols share a single ``render`` argument shape:

* :class:`ImageBackend` — synchronous; the placeholder backend implements it.
* :class:`AsyncImageBackend` — asynchronous; the OpenAI backend implements
  it so :class:`~shop_gen.data_synth.images._step.GenImagesStep` can fan
  out concurrent ``images.generate`` calls behind a bounded semaphore.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ImageBackend(Protocol):
    """Synchronous pluggable image-generation backend (spec §5.1).

    Backends produce raw bytes for one product image. They are stateless
    and side-effect-free — :class:`GenImagesStep` owns the filesystem
    write so backends remain trivially unit-testable.

    Attributes:
        name: Backend identifier (matches
            :data:`shop_gen.config.ImageBackend` literal values).
        extension: File extension (with leading dot, e.g. ``".svg"``).
    """

    name: str
    extension: str

    def render(
        self,
        *,
        handle: str,
        index: int,
        title: str,
        category: str,
        width: int,
        height: int,
    ) -> bytes:
        """Render one product image as raw bytes."""
        ...


@runtime_checkable
class AsyncImageBackend(Protocol):
    """Asynchronous pluggable image-generation backend (spec §5.1).

    Mirrors :class:`ImageBackend` for backends whose calls benefit from
    bounded async concurrency. The step ``await``s :meth:`render_async`
    inside an :class:`asyncio.Semaphore`-gated coroutine so the in-flight
    cap is enforced regardless of backend latency variance.
    """

    name: str
    extension: str

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
        """Render one product image as raw bytes."""
        ...


__all__ = ["AsyncImageBackend", "ImageBackend"]
