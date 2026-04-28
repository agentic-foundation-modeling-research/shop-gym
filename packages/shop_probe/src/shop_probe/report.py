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

The ``surface: SurfaceMetrics`` field from spec §5.6 is populated when
axis B is run (see ``shop-probe run --axes A,B``). For axis-A-only runs
it stays ``None`` so the closed schema still validates.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shop_probe.surface.metrics import SurfaceMetrics
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

LikertDimension = Literal[
    "visual_coherence",
    "copy_realism",
    "error_plausibility",
]
"""Quality dimensions for the v1.1 Likert judge (spec §5.9).

The Likert judge (T7.2) scores each anonymized trajectory on three
orthogonal quality dimensions on a 1..5 scale. The dimensions are pinned
per spec §5.9 — adding new dimensions is a v1.2 / supplement workstream
that bumps the prompt template version.
"""

LIKERT_DIMENSIONS: tuple[LikertDimension, ...] = get_args(LikertDimension)
"""All :data:`LikertDimension` literals in declaration order."""

_LIKERT_SCORE_VALUES: tuple[int, ...] = (1, 2, 3, 4, 5)
"""Allowed Likert scores (inclusive 1..5 per spec §5.9)."""


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


class JudgeModelPin(BaseModel):
    """Pinned LLM judge model identity (spec §5.5 step 5 + guardrails).

    The spec §5.5 guardrails require pinning ``model + version + temperature``
    in the report metadata so reviewers can re-attribute every
    :class:`JudgeCall` to a specific model revision. v1 ships **one OpenAI
    flagship model** (e.g. ``gpt-5``) at ``temperature=0`` (spec §5.5 step 5).

    The model identity also enters the judge runtime via
    :class:`shop_probe.judge.llm.PinnedJudge` — the same value is embedded
    in the report header *and* threaded through every LLM call so the two
    cannot drift across a run.

    Attributes:
        provider: LLM provider identifier (e.g. ``"openai"``). Free-form
            string; the v1 cohort run pins ``"openai"``.
        model: Model family name (e.g. ``"gpt-5"``). Pinned per spec §5.5
            step 5.
        model_version: Specific model revision the call resolved to
            (e.g. ``"gpt-5-2025-09-01"``). Pinned per spec §5.5 guardrails
            so revisioned upgrades surface as a different report header.
        temperature: Sampling temperature. Spec §5.5 step 5 mandates
            ``0.0``; the schema accepts ``[0, 2]`` so v1.1 cross-judge
            sensitivity studies can re-use the same field without a
            schema bump.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    temperature: float = Field(ge=0.0, le=2.0)


class LikertCall(BaseModel):
    """One v1.1 Likert quality-judge invocation on one trajectory (spec §5.9).

    The Likert judge (T7.2) is a single-trajectory complement to the blinded
    pairwise judge (spec §5.5): each anonymized trajectory is scored on the
    three :data:`LikertDimension` axes on a 1..5 scale. Calls without an
    evidence citation are dropped before they ever reach the report — the
    spec §5.5 guardrail "calls without evidence are discarded" applies
    uniformly to every axis-C judge.

    The schema deliberately exposes one explicit field per dimension (rather
    than a ``dict[LikertDimension, int]``) so pyright in strict mode can pin
    each rating's ``[1, 5]`` constraint at the field level, and so future
    paper figures can pull a single column without re-keying a dict.

    Attributes:
        task_id: Identifier of the judge task from
            ``judge/tasks/v1.yaml`` (shared with the pairwise judge per
            spec §5.5 step 1).
        target_label: ``Target.label`` of the storefront the trajectory
            was recorded on. The Likert judge is per-trajectory rather
            than per-pair, so the target is named explicitly.
        visual_coherence: 1..5 score on the visual-coherence dimension
            (theme consistency, layout polish).
        copy_realism: 1..5 score on the copy-realism dimension
            (product copy, microcopy, error strings).
        error_plausibility: 1..5 score on the error-plausibility dimension
            (failure modes look like real-world Shopify failures).
        evidence_cited: ``True`` if the response included at least one
            screenshot/snapshot citation; calls without evidence are
            discarded per spec §5.5 guardrails before reaching the report.
        prompt_hash: Content hash of the Likert prompt template version
            used (spec §5.8).
        response_text: Full raw response text from the judge model
            (kept verbatim per spec §5.5 guardrails).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    visual_coherence: int = Field(ge=1, le=5)
    copy_realism: int = Field(ge=1, le=5)
    error_plausibility: int = Field(ge=1, le=5)
    evidence_cited: bool
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_text: str

    def score(self, dimension: LikertDimension) -> int:
        """Return this call's score on ``dimension`` (1..5)."""
        return int(getattr(self, dimension))


class LikertDistribution(BaseModel):
    """Per-dimension Likert score distribution aggregated over calls (spec §5.9).

    The T7.2 check from ``docs/impl/web_probe_implementation.md`` reads:

        Check: per-dimension Likert distributions in the report.

    Each :class:`ProbeReport` carries one :class:`LikertDistribution` per
    :data:`LikertDimension` so paper figures can pull a per-dimension
    histogram + mean from a versioned report without recomputing from raw
    calls. Empty distributions (``n_calls == 0``) are valid and report
    ``mean=None``; that is the on-axis-A/B-only / no-likert-run case.

    Attributes:
        dimension: The :data:`LikertDimension` this distribution scores.
        n_calls: Number of :class:`LikertCall` rows that contributed to
            this distribution.
        counts: Histogram from score (``1..5``) to count. Keys outside
            ``{1, 2, 3, 4, 5}`` are rejected; counts must sum to
            ``n_calls``.
        mean: Arithmetic mean of the contributing scores in ``[1, 5]``.
            ``None`` iff ``n_calls == 0``; the empty mean is undefined and
            reported as missing rather than as ``0.0``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: LikertDimension
    n_calls: int = Field(ge=0)
    counts: dict[int, int] = Field(default_factory=lambda: {})
    mean: float | None = Field(default=None, ge=1.0, le=5.0)

    @model_validator(mode="after")
    def _check_distribution_shape(self) -> LikertDistribution:
        """Reject distributions whose ``counts``/``mean`` disagree with ``n_calls``."""
        for score in self.counts:
            if score not in _LIKERT_SCORE_VALUES:
                msg = (
                    f"LikertDistribution: invalid score key {score!r} in counts; "
                    f"allowed scores are {list(_LIKERT_SCORE_VALUES)}"
                )
                raise ValueError(msg)
        for score, count in self.counts.items():
            if count < 0:
                msg = f"LikertDistribution: negative count {count} for score {score}"
                raise ValueError(msg)
        total = sum(self.counts.values())
        if total != self.n_calls:
            msg = f"LikertDistribution: counts sum {total} disagrees with n_calls={self.n_calls}"
            raise ValueError(msg)
        if self.n_calls == 0 and self.mean is not None:
            msg = "LikertDistribution: n_calls == 0 requires mean=None"
            raise ValueError(msg)
        if self.n_calls > 0 and self.mean is None:
            msg = "LikertDistribution: n_calls > 0 requires mean to be set"
            raise ValueError(msg)
        return self


def aggregate_likert_distributions(
    calls: Iterable[LikertCall],
) -> tuple[LikertDistribution, ...]:
    """Aggregate :class:`LikertCall` rows into one distribution per dimension.

    Returns one :class:`LikertDistribution` per :data:`LikertDimension` in
    declaration order so the report row order is stable across runs.
    Empty input produces three empty (``n_calls == 0``) distributions — the
    schema accepts them and the report serializes them deterministically.

    Args:
        calls: All :class:`LikertCall` rows for one report (post-discard —
            parse-error and no-evidence calls are filtered upstream by
            :class:`shop_probe.judge.likert.LikertJudge`).

    Returns:
        One :class:`LikertDistribution` per :data:`LikertDimension`.
    """
    materialized = tuple(calls)
    out: list[LikertDistribution] = []
    for dimension in LIKERT_DIMENSIONS:
        counts: dict[int, int] = dict.fromkeys(_LIKERT_SCORE_VALUES, 0)
        total = 0
        for call in materialized:
            score = call.score(dimension)
            counts[score] += 1
            total += score
        n = len(materialized)
        mean = total / n if n > 0 else None
        out.append(
            LikertDistribution(
                dimension=dimension,
                n_calls=n,
                counts={s: c for s, c in counts.items() if c > 0},
                mean=mean,
            )
        )
    return tuple(out)


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
      — pairwise-judge calls (empty for unpaired or axis-A-only runs)
      and the rerun index + per-probe flake rate from N=3 reruns
      (spec §5.8).

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
        judge_calls: Axis-C pairwise judge calls; empty for unpaired
            targets or axis-A-only runs.
        judge_model: Pinned LLM judge model + version + temperature
            (spec §5.5 guardrails). Required when ``judge_calls`` *or*
            ``likert_calls`` are non-empty so every reported call traces
            to a pinned model; ``None`` on axis-A/B-only runs.
        likert_calls: v1.1 Likert quality-judge calls (spec §5.9, T7.2);
            empty on axis-A/B-only runs and on cohorts that opt out of
            the Likert supplement.
        likert_distributions: Per-dimension Likert score distributions
            aggregated from :attr:`likert_calls` (spec §5.9, T7.2).
            Carries one :class:`LikertDistribution` per
            :data:`LikertDimension` so paper figures can pull a histogram
            without recomputing from raw calls.
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

    # Axis C — empty for unpaired / axis-A-only runs (spec §5.6)
    judge_calls: tuple[JudgeCall, ...] = ()
    judge_model: JudgeModelPin | None = None

    # v1.1 Likert quality judge (spec §5.9, T7.2) — empty on axis-A/B-only runs.
    likert_calls: tuple[LikertCall, ...] = ()
    likert_distributions: tuple[LikertDistribution, ...] = ()

    # Stability (spec §5.8)
    rerun_index: int = Field(ge=1)
    flake_rate_per_probe: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_judge_model_pinned(self) -> ProbeReport:
        """Reject reports that emit judge calls without a pinned model."""
        if (self.judge_calls or self.likert_calls) and self.judge_model is None:
            msg = (
                "ProbeReport has judge_calls/likert_calls but no judge_model; "
                "spec §5.5 guardrails require a pinned model + version + "
                "temperature whenever the report carries axis-C calls"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_likert_distribution_shape(self) -> ProbeReport:
        """Reject Likert rows whose distribution shape is internally inconsistent."""
        if not self.likert_distributions:
            if self.likert_calls:
                msg = (
                    "ProbeReport has likert_calls but no likert_distributions; "
                    "call shop_probe.report.aggregate_likert_distributions() first"
                )
                raise ValueError(msg)
            return self
        seen: set[LikertDimension] = set()
        for dist in self.likert_distributions:
            if dist.dimension in seen:
                msg = f"ProbeReport has duplicate likert distribution for {dist.dimension!r}"
                raise ValueError(msg)
            seen.add(dist.dimension)
        if seen != set(LIKERT_DIMENSIONS):
            missing = sorted(set(LIKERT_DIMENSIONS) - seen)
            msg = f"ProbeReport likert_distributions missing dimension(s): {missing}"
            raise ValueError(msg)
        expected_n = len(self.likert_calls)
        for dist in self.likert_distributions:
            if dist.n_calls != expected_n:
                msg = (
                    f"ProbeReport likert_distributions[{dist.dimension!r}].n_calls="
                    f"{dist.n_calls} disagrees with len(likert_calls)={expected_n}"
                )
                raise ValueError(msg)
        return self
