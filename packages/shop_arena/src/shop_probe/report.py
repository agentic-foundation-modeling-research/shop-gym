"""Closed schemas for the ShopProbe ``ProbeReport`` artifact.

Implements the typed report contract documented in
``docs/specs/shop_arena/web_probe.md`` §5.6 and patched in
``docs/specs/shop_arena/web_probe_patch.md``:

* :class:`EvidenceRef` — one captured artifact (screenshot, DOM
  snapshot, a11y snapshot, HAR) plus the optional selector that
  drove the assertion (spec §5.3 evidence requirements).
* :class:`BrowserMeta` — pinned browser/runtime versions embedded in
  every report header for reproducibility (spec §5.3 + §5.8).
* :class:`ProbeResult` — outcome of one rubric leaf.
* :class:`CategoryScore` — per-category coverage rollup.
* :class:`JudgeCall` — one per-shop Turing-test classification call
  (``web_probe_patch.md``).
* :class:`ProbeReport` — closed JSON document emitted per target per run.

All models set ``extra="forbid"`` and ``frozen=True``: ``ProbeReport`` is
the public contract the paper figures read from, so unknown fields and
silent mutation are rejected. The module is import-safe — it performs
no I/O at import time.

The ``surface: SurfaceMetrics`` field from spec §5.6 is populated when
axis B is run (see ``shop-probe run --axes A,B``). For axis-A-only runs
it stays ``None`` so the closed schema still validates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shop_probe.surface.metrics import SurfaceMetrics
from shop_probe.targets import Target

EvidenceKind = Literal["screenshot", "dom_snapshot", "a11y_snapshot", "har"]
"""Captured artifact type (spec §5.3, §5.5, §5.8).

* ``screenshot`` — PNG capture of the viewport.
* ``dom_snapshot`` — serialized DOM (HTML or structural fingerprint).
* ``a11y_snapshot`` — accessibility-tree snapshot.
* ``har`` — full HAR network capture for the crawl/probe run.
"""

JudgePrediction = Literal["sandbox", "real", "abstain"]
"""Per-shop Turing-test classifier output (``web_probe_patch.md``).

The judge sees the evidence for a single shop and predicts whether the
shop is ``sandbox`` or ``real`` (or abstains)."""


class EvidenceRef(BaseModel):
    """Pointer to one captured artifact emitted by a probe or crawl.

    Spec §5.3 mandates structured evidence: screenshot path, DOM-snapshot
    path, and the CSS/role selector used to assert. v1 normalizes those
    into a single ``EvidenceRef`` row; the storage path is relative to
    the report's evidence root so reports remain relocatable.

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

    Reproducibility contract from spec §5.3 + §5.8: every report records
    the exact Python / Playwright / Chromium versions, the pinned UA,
    the fixed viewport, and the headless flag so reviewers can re-run
    against the same harness configuration.

    Attributes:
        python_version: ``sys.version`` short form, e.g. ``"3.11.9"``.
        playwright_version: Playwright Python distribution version.
        chromium_version: Browser binary version reported by Playwright.
        user_agent: Pinned UA string the probe context advertises.
        viewport: ``(width, height)`` viewport in CSS pixels. Spec §5.3
            pins this at ``(1280, 800)`` for v1.
        headless: Whether the probe context ran headless. Spec §5.3
            mandates ``True`` for v1 reproducibility.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_version: str = Field(min_length=1)
    playwright_version: str = Field(min_length=1)
    chromium_version: str = Field(min_length=1)
    user_agent: str = Field(min_length=1)
    viewport: tuple[int, int]
    headless: bool


class ProbeResult(BaseModel):
    """Outcome of one rubric-leaf probe (spec §5.6).

    A ``passed`` value of ``None`` encodes "not_applicable" — the probe
    ran but the storefront does not exercise the relevant capability
    surface (e.g. an i18n probe on a single-locale shop). Per spec §5.3
    each result carries structured evidence so reviewers can audit
    individual decisions.

    Attributes:
        id: Rubric entry id this result is keyed against (matches
            :attr:`shop_probe.rubric.RubricEntry.id`).
        passed: ``True`` if the probe asserted successfully, ``False``
            on a clean failure, ``None`` for "not applicable".
        evidence: All artifacts the probe captured. May be empty for
            trivially-failing probes that timed out before capture.
        notes: Optional free-form note (failure reason, observed value).
        duration_ms: Wall-clock duration of the probe call, in
            milliseconds. Used for runtime budgeting + flake debugging.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    passed: bool | None
    evidence: tuple[EvidenceRef, ...] = ()
    notes: str | None = None
    duration_ms: int = Field(ge=0)


class CategoryScore(BaseModel):
    """Per-category capability-coverage rollup (spec §5.3 + §5.6).

    ``coverage = weight_passed / weight_total`` when ``weight_total > 0``.
    Categories with no applicable probes (``weight_total == 0``) report
    ``coverage = 0.0`` and are flagged downstream by the report writer.

    Attributes:
        category: Rubric category name (free-form string in the schema;
            v1 categories are listed in spec §5.3 and enforced by
            :class:`shop_probe.rubric.RubricEntry`).
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


class JudgeCall(BaseModel):
    """One per-shop Turing-test classification call (``web_probe_patch.md``).

    The judge is shown the evidence for a single shop and predicts whether
    the shop is ``sandbox`` or ``real`` (or abstains). Group-level
    accuracy is computed at stage 2 — counting calls whose
    ``predicted_label == report.target.label``.

    Attributes:
        predicted_label: Judge's classification. ``"abstain"`` calls are
            scored as not-correct; the absolute count is preserved on the
            :class:`ProbeReport` so reviewers can reconcile drop rates.
        prompt_hash: Content hash of the prompt template version used
            (spec §5.8 reproducibility).
        response: Full raw response text from the judge model
            (kept verbatim for audit).
        latency_ms: Wall-clock duration of the LLM call, in milliseconds.
        cost_usd: Estimated USD cost for the call. ``0.0`` is permitted
            for stub/test wiring.
        model_id: Pinned model identifier used for the call (e.g.
            ``"gpt-5-2025-09-01"``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    predicted_label: JudgePrediction
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    response: str
    latency_ms: float = Field(ge=0.0)
    cost_usd: float = Field(ge=0.0)
    model_id: str = Field(min_length=1)


class ProbeReport(BaseModel):
    """Closed report emitted per target per run (spec §5.6).

    This is the public contract paper figures read from. ``extra="forbid"``
    + ``frozen=True`` mean any schema drift surfaces immediately at
    validation time rather than as a silent figure regression.

    Three groups of fields:

    * **Header** (``target`` … ``timestamp``) — what was measured, by
      which rubric+runner+browser combination, and when.
    * **Axis A** (``probe_results`` … ``coverage_weighted``) — per-leaf
      results, per-category rollup, and the four headline coverage
      numbers per spec §5.3.
    * **Axis B** (``surface``) — crawl-derived surface-area metrics
      (spec §5.4); ``None`` on axis-A-only runs.
    * **Axis C + stability** (``judge_calls`` … ``flake_rate_per_probe``)
      — per-shop judge calls (empty on axis-A-only runs) and the rerun
      index + per-probe flake rate from N=3 reruns (spec §5.8).

    Attributes:
        target: The storefront under test (see :class:`Target`).
        rubric_version: Rubric version string, e.g. ``"v1"`` (spec §5.8).
        rubric_hash: SHA-256 hex digest of the rubric YAML bytes.
        runner_version: ``shop_probe`` runner version that produced
            the report.
        runtime: Pinned browser/runtime versions (see
            :class:`BrowserMeta`).
        timestamp: When the run started; should be timezone-aware in
            production reports for paper reproducibility.
        probe_results: One :class:`ProbeResult` per rubric leaf executed.
        categories: Per-category coverage rollups (spec §5.3 formula).
        coverage_core: Weighted coverage over ``level == "core"`` probes.
        coverage_modern: Weighted coverage over ``level == "modern"``
            probes.
        coverage_advanced: Weighted coverage over ``level == "advanced"``
            probes (always 0 in v1 — advanced probes ship in v1.1).
        coverage_weighted: Weighted-mean coverage across categories.
        surface: Crawl-derived axis-B surface-area metrics
            (:class:`shop_probe.surface.metrics.SurfaceMetrics`); ``None``
            on axis-A-only runs.
        judge_calls: Axis-C per-shop classification calls; empty on
            axis-A/B-only runs.
        rerun_index: 1-indexed run number within the rerun group
            (spec §5.8).
        flake_rate_per_probe: ``probe_id -> flake_rate ∈ [0, 1]`` from
            the rerun group; populated by the aggregation step.
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

    # Axis B — surface area (None for axis-A-only runs, spec §5.6)
    surface: SurfaceMetrics | None = None

    # Axis C — empty on axis-A/B-only runs (web_probe_patch.md)
    judge_calls: tuple[JudgeCall, ...] = ()

    # Stability (spec §5.8)
    rerun_index: int = Field(ge=1)
    flake_rate_per_probe: dict[str, float] = Field(default_factory=dict)
