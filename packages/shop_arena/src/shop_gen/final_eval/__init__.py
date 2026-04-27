"""Phase 5 final-eval steps for the ``shop_gen`` pipeline.

Implements the post-build advisory quality check documented in
``docs/specs/shop_arena/shop_gen.md`` §5.5.5. v0.1 lands incrementally
behind the impl plan T6.x tasks; today the playwright smoke runner
ships:

* :mod:`shop_gen.final_eval.playwright_smoke` — :func:`run_playwright_smoke`
  drives the spec-mandated smoke flow (home → collection → product →
  add-to-cart → checkout-redirect) against a freshly built hydrogen
  tree, captures screenshots at fixed viewports, and returns a
  structured :class:`SmokeReport`. The module ships protocol seams
  (:class:`DevServerFactory`, :class:`BrowserDriver`) so the loop can
  be exercised under stubs in CI; production wiring lands alongside
  the LLM judge (T6.2) and the ``final_eval`` step (T6.3).

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_gen.final_eval.playwright_smoke import (
    DEFAULT_SMOKE_FLOW,
    DEFAULT_VIEWPORTS,
    BrowserDriver,
    DevServerFactory,
    Screenshot,
    SmokeAction,
    SmokeFailure,
    SmokeFlow,
    SmokeReport,
    SmokeStep,
    Viewport,
    resolve_smoke_flow,
    run_playwright_smoke,
)

__all__ = [
    "DEFAULT_SMOKE_FLOW",
    "DEFAULT_VIEWPORTS",
    "BrowserDriver",
    "DevServerFactory",
    "Screenshot",
    "SmokeAction",
    "SmokeFailure",
    "SmokeFlow",
    "SmokeReport",
    "SmokeStep",
    "Viewport",
    "resolve_smoke_flow",
    "run_playwright_smoke",
]
