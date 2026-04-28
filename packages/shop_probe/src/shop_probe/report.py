"""Closed schemas for the ShopProbe ``ProbeReport`` artifact.

Implements the typed report contract documented in
``docs/specs/shop_arena/web_probe.md`` §5.6 (and runtime/metadata
requirements from §5.3, §5.5, §5.8):

* :class:`EvidenceRef` — one captured artifact (screenshot, DOM
  snapshot, a11y snapshot, HAR) plus the optional selector that
  drove the assertion (spec §5.3 evidence requirements).
* :class:`BrowserMeta` — pinned browser/runtime versions embedded in
  every report header for reproducibility (spec §5.3 + §5.8).
* :class:`ProbeResult` — outcome of one rubric leaf.
* :class:`CategoryScore` — per-category coverage rollup.
* :class:`JudgeCall` — one blinded pairwise-judge invocation (spec §5.5).
* :class:`ProbeReport` — closed JSON document emitted per target per run.

All models set ``extra="forbid"`` and ``frozen=True``: ``ProbeReport`` is
the public contract the paper figures read from, so unknown fields and
silent mutation are rejected. The module is import-safe — it performs
no I/O at import time.

The ``surface: SurfaceMetrics`` field from spec §5.6 is added when
axis B is wired in T2.3 (spec §7 M2). T1.5 lands the axis-A and
axis-C surface area of the schema only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shop_probe.targets import Target

EvidenceKind = Literal["screenshot", "dom_snapshot", "a11y_snapshot", "har"]
"""Captured artifact type (spec §5.3, §5.5, §5.8).

* ``screenshot`` — PNG capture of the viewport.
* ``dom_snapshot`` — serialized DOM (HTML or structural fingerprint).
* ``a11y_snapshot`` — accessibility-tree snapshot.
* ``har`` — full HAR network capture for the crawl/probe run.
"""

JudgePick = Literal["A", "B", "abstain"]
"""Judge response on a pairwise call (spec §5.5 step 5)."""

JudgeTruth = Literal["A", "B"]
"""Designated truth slot used to score a pairwise call (spec §5.5 step 7).

For experimental ``(sandbox, source)`` pairs this is the position holding
the source. For control ``(real_a, real_b)`` pairs neither is "synthetic",
so ``truth`` is the **designated** real position and the resulting
``judge_accuracy_control`` is the noise floor (spec §5.2 + §5.5 step 7).
"""


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
    """One blinded pairwise-judge invocation (spec §5.5 + §5.6).

    The judge is presented with an anonymized ``(A, B)`` trajectory pair
    and asked to identify which is from the real storefront. ``truth``
    is the designated correct slot (the source for experimental pairs;
    a designated real for control pairs — see :data:`JudgeTruth`).
    ``swap_consistent`` records whether the judge's pick survives the
    A/B-swap re-run from spec §5.5 step 6; swap-inconsistent calls are
    aggregated separately and excluded from the headline score.

    Attributes:
        task_id: Identifier of the judge task from
            ``judge/tasks/v1.yaml`` (spec §5.5 step 1).
        pair_label: ``(label_a, label_b)`` of the two trajectories the
            judge saw, in presentation order.
        judge_pick: ``"A"``, ``"B"``, or ``"abstain"`` (spec §5.5 step 5
            requires evidence-cited abstention for unsupported claims).
        truth: Designated correct slot (see :data:`JudgeTruth`).
        swap_consistent: ``True`` if the judge's pick survived the A/B
            swap from spec §5.5 step 6.
        evidence_cited: ``True`` if the response included at least one
            screenshot/snapshot citation; calls without evidence are
            discarded per spec §5.5 guardrails.
        confidence: Self-reported judge confidence in ``[0, 1]``.
        prompt_hash: Content hash of the prompt template version used,
            for reproducibility (spec §5.8).
        response_text: Full raw response text from the judge model
            (kept verbatim per spec §5.5 guardrails).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    pair_label: tuple[str, str]
    judge_pick: JudgePick
    truth: JudgeTruth
    swap_consistent: bool
    evidence_cited: bool
    confidence: float = Field(ge=0.0, le=1.0)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_text: str


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
    * **Axis C + stability** (``judge_calls`` … ``flake_rate_per_probe``)
      — pairwise-judge calls (empty for unpaired or axis-A-only runs)
      and the rerun index + per-probe flake rate from N=3 reruns
      (spec §5.8).

    Per spec §5.6 the schema also carries a ``surface: SurfaceMetrics``
    field for axis B; that field is wired in T2.3 (spec §7 M2) once
    :class:`shop_probe.surface.metrics.SurfaceMetrics` lands in T2.1.

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
        judge_calls: Axis-C pairwise judge calls; empty for unpaired
            targets or axis-A-only runs.
        rerun_index: 1-indexed run number within the N=3 rerun group
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

    # Axis C — empty for unpaired / axis-A-only runs (spec §5.6)
    judge_calls: tuple[JudgeCall, ...] = ()

    # Stability (spec §5.8)
    rerun_index: int = Field(ge=1)
    flake_rate_per_probe: dict[str, float] = Field(default_factory=dict)
