"""Per-shop page bundle for the v2 capture-judge tier (spec §5.3.3).

The bundle is a fixed 5-page snapshot — home, collection, product, cart,
search — captured once per axis-A run. Each page contributes a screenshot
and an aria-snapshot file under ``<evidence_root>/_bundle/<page>/``; the
:func:`shop_probe.agent.judge.run_capture_judge` call then reads the
slice each ``level: capture_judge`` rubric entry asks for.

This module is import-safe — it performs no I/O at import time.
"""

from __future__ import annotations

from shop_probe.capture.bundle import (
    PageBundle,
    PageCapture,
    capture_bundle,
)
from shop_probe.rubric.schema import PageRef

__all__ = [
    "PageBundle",
    "PageCapture",
    "PageRef",
    "capture_bundle",
]
