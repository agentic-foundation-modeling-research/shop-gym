"""Phase 5 final-eval steps for the ``shop_gen`` pipeline.

Implements the post-build advisory quality check documented in
``docs/specs/shop_arena/shop_gen.md`` §5.5.5. v0.1 ships three
modules behind the impl plan T6.x tasks:

* :mod:`shop_gen.final_eval.playwright_smoke` — :func:`run_playwright_smoke`
  drives the spec-mandated smoke flow (home → collection → product →
  add-to-cart → checkout-redirect) against a freshly built hydrogen
  tree, captures screenshots at fixed viewports, and returns a
  structured :class:`SmokeReport`. Production wiring (a real
  ``pnpm dev`` driver + Playwright browser driver) lands alongside
  the M8 image-generation work; v0.1 ships protocol seams
  (:class:`DevServerFactory`, :class:`BrowserDriver`) so the loop
  can be exercised under stubs in CI.
* :mod:`shop_gen.final_eval.prompts` — :func:`load_quality_judge_prompt`
  returns the ``str.format()`` template the post-build LLM judge
  consumes (T6.2). The template carries the slots T6.3 fills in:
  ``{base_url}``, ``{capabilities}``, ``{screenshots_table}``,
  ``{failures_table}``.
* :mod:`shop_gen.final_eval.step` — :class:`FinalEvalStep` /
  :func:`run_final_eval` (T6.3) wire the smoke runner + LLM judge
  into one DAG step that writes ``<out_dir>/final_eval.json``. The
  step is **advisory** (spec §5.5.5): a ``fail`` verdict, an LLM
  transport error, or a missing capability document are recorded
  into the verdict file rather than re-raised so the run completes.

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
from shop_gen.final_eval.prompts import load_quality_judge_prompt
from shop_gen.final_eval.step import FinalEvalStep, SmokeRunner, run_final_eval

__all__ = [
    "DEFAULT_SMOKE_FLOW",
    "DEFAULT_VIEWPORTS",
    "BrowserDriver",
    "DevServerFactory",
    "FinalEvalStep",
    "Screenshot",
    "SmokeAction",
    "SmokeFailure",
    "SmokeFlow",
    "SmokeReport",
    "SmokeRunner",
    "SmokeStep",
    "Viewport",
    "load_quality_judge_prompt",
    "resolve_smoke_flow",
    "run_final_eval",
    "run_playwright_smoke",
]
