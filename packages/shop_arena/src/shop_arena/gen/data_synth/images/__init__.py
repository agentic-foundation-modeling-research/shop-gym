"""Image-generation step + backends (spec §5.1, §5.3).

Public API:

* :class:`ImageBackend` / :class:`AsyncImageBackend` — protocols.
* :class:`PlaceholderBackend` — deterministic SVG (default).
* :class:`OpenAIImageBackend` — OpenAI-compatible photorealistic backend
  (selected by ``--image-backend openai``).
* :class:`GenImagesStep` — Phase 2 step.
* :func:`get_backend` — backend factory.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

from shop_arena.gen.data_synth.images._openai_backend import OpenAIImageBackend
from shop_arena.gen.data_synth.images._placeholder import PlaceholderBackend
from shop_arena.gen.data_synth.images._protocol import AsyncImageBackend, ImageBackend
from shop_arena.gen.data_synth.images._step import GenImagesStep, get_backend

__all__ = [
    "AsyncImageBackend",
    "GenImagesStep",
    "ImageBackend",
    "OpenAIImageBackend",
    "PlaceholderBackend",
    "get_backend",
]
