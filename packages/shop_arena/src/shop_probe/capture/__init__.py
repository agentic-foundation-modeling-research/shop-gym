"""Per-shop 5-page capture (one row per :data:`shop_probe.rubric.schema.PageType`).

Captures one screenshot + one aria-snapshot JSON per page under
``<bundle_root>/<page_type>/``. Used as the input to every family
runner: shape/space metrics read the files and compute mechanical
metrics; info/control slots hand them to a single-modality LLM judge.
"""

from __future__ import annotations

from shop_probe.capture.bundle import (
    PAGE_TYPES,
    PageBundle,
    PageCapture,
    capture_bundle,
    discover_sample_urls,
)

__all__ = [
    "PAGE_TYPES",
    "PageBundle",
    "PageCapture",
    "capture_bundle",
    "discover_sample_urls",
]
