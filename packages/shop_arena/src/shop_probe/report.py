"""Closed schemas for the ShopProbe ``ProbeReport`` artifact.

* :class:`EvidenceRef` — one captured artifact (screenshot, DOM
  snapshot, a11y snapshot, HAR) plus the optional selector that
  drove the assertion.
* :class:`BrowserMeta` — pinned browser/runtime versions embedded in
  every report header for reproducibility.
* :class:`ProbeResult` — outcome of one rubric leaf.
* :class:`CategoryScore` — per-category coverage rollup.
* :class:`ProbeReport` — closed JSON document emitted per target per run.

All models set ``extra="forbid"`` and ``frozen=True``: ``ProbeReport`` is
the public contract figures read from, so unknown fields and silent
mutation are rejected. The module is import-safe — it performs no I/O at
import time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shop_probe.surface.metrics import SurfaceMetrics
from shop_probe.targets import Target

EvidenceKind = Literal["screenshot", "dom_snapshot", "a11y_snapshot", "har"]
"""Captured artifact type."""


class EvidenceRef(BaseModel):
    """Pointer to one captured artifact emitted by a probe.

    Attributes:
        kind: Artifact type (see :data:`EvidenceKind`).
        path: Relative path to the artifact within the report's
            ``evidence/`` subtree.
        selector: Optional CSS / ARIA-role selector the probe used to
            assert against; ``None`` when the evidence is not anchored
            to a single locator (e.g. full-page HAR).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EvidenceKind
    path: str = Field(min_length=1)
    selector: str | None = None


class BrowserMeta(BaseModel):
    """Pinned browser/runtime versions embedded in every report header.

    Attributes:
        python_version: ``sys.version`` short form, e.g. ``"3.11.9"``.
        playwright_version: Playwright Python distribution version.
        chromium_version: Browser binary version reported by Playwright.
        user_agent: Pinned UA string the probe context advertises.
        viewport: ``(width, height)`` viewport in CSS pixels.
        headless: Whether the probe context ran headless.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_version: str = Field(min_length=1)
    playwright_version: str = Field(min_length=1)
    chromium_version: str = Field(min_length=1)
    user_agent: str = Field(min_length=1)
    viewport: tuple[int, int]
    headless: bool


class ProbeResult(BaseModel):
    """Outcome of one rubric-leaf probe.

    A ``passed`` value of ``None`` encodes "not_applicable" — the probe
    ran but the storefront does not exercise the relevant capability
    surface.

    Attributes:
        id: Rubric entry id this result is keyed against.
        passed: ``True`` if the probe asserted successfully, ``False``
            on a clean failure, ``None`` for "not applicable".
        evidence: All artifacts the probe captured.
        notes: Optional free-form note (failure reason, observed value).
        duration_ms: Wall-clock duration of the probe call, in
            milliseconds.
        judge_cost_usd: USD cost of the capture-judge call for this
            probe (``None`` for deterministic probes that issue no
            judge call).
        judge_model: Pinned model id of the capture-judge that decided
            this probe (``None`` for deterministic probes).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    passed: bool | None
    evidence: tuple[EvidenceRef, ...] = ()
    notes: str | None = None
    duration_ms: int = Field(ge=0)
    judge_cost_usd: float | None = Field(default=None, ge=0.0)
    judge_model: str | None = Field(default=None, min_length=1)


class CategoryScore(BaseModel):
    """Per-category capability-coverage rollup.

    ``coverage = weight_passed / weight_total`` when ``weight_total > 0``.
    Categories with no applicable probes (``weight_total == 0``) report
    ``coverage = 0.0``.

    Attributes:
        category: Rubric category name.
        weight_passed: Sum of weights over probes that passed.
        weight_total: Sum of weights over all applicable probes.
        coverage: Convenience field equal to
            ``weight_passed / weight_total`` (0..1), pinned in the
            report so figure code does not recompute.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str = Field(min_length=1)
    weight_passed: float = Field(ge=0.0)
    weight_total: float = Field(ge=0.0)
    coverage: float = Field(ge=0.0, le=1.0)


class ProbeReport(BaseModel):
    """Closed report emitted per target per run.

    This is the public contract figures read from. ``extra="forbid"``
    + ``frozen=True`` mean any schema drift surfaces immediately at
    validation time rather than as a silent figure regression.

    Attributes:
        target: The storefront under test (see :class:`Target`).
        rubric_version: Rubric version string, e.g. ``"v2"``.
        rubric_hash: SHA-256 hex digest of the rubric YAML bytes.
        runner_version: ``shop_probe`` runner version that produced
            the report.
        runtime: Pinned browser/runtime versions (see
            :class:`BrowserMeta`).
        timestamp: When the run started (timezone-aware).
        probe_results: One :class:`ProbeResult` per rubric leaf executed.
        categories: Per-category coverage rollups.
        coverage_core: Weighted coverage over ``level == "core"`` probes.
        coverage_modern: Weighted coverage over ``level == "modern"``
            probes.
        coverage_advanced: Weighted coverage over ``level == "advanced"``
            and ``level == "capture_judge"`` probes.
        coverage_weighted: Weighted-mean coverage across categories.
        surface: Crawl-derived axis-B surface-area metrics
            (:class:`shop_probe.surface.metrics.SurfaceMetrics`); ``None``
            on axis-A-only runs.
        total_judge_cost_usd: Sum of ``judge_cost_usd`` across all
            probe results that recorded one (``None`` when no probe
            issued a judge call).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Header
    target: Target
    rubric_version: str = Field(min_length=1)
    rubric_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_version: str = Field(min_length=1)
    runtime: BrowserMeta
    timestamp: datetime

    # Axis A — capability coverage
    probe_results: tuple[ProbeResult, ...] = ()
    categories: tuple[CategoryScore, ...] = ()
    coverage_core: float = Field(ge=0.0, le=1.0)
    coverage_modern: float = Field(ge=0.0, le=1.0)
    coverage_advanced: float = Field(ge=0.0, le=1.0)
    coverage_weighted: float = Field(ge=0.0, le=1.0)

    # Axis B — surface area (None for axis-A-only runs)
    surface: SurfaceMetrics | None = None

    # Capture-judge cost rollup
    total_judge_cost_usd: float | None = Field(default=None, ge=0.0)
