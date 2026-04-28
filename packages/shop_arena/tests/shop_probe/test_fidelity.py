"""Tests for `shop_probe.fidelity` (T3.1 acceptance — spec §5.7).

Covers:

* Per-pair coverage gap (per-category + weighted) computed correctly
  from synthetic A+B reports.
* Surface ratio per-metric and geometric mean — including the
  parity-on-zero shortcut and the rejected ``source==0,sandbox>0`` case.
* ``sandbox_in_real_envelope`` over a small real-shop population.
* Cohort-level ``real_shop_population`` envelope.
* Judge fields default to ``None`` until M4 (T3.1 explicit requirement).
* JSON round-trip + ``extra="forbid"`` on both schemas.
* Pair-identity guards (kind / pair_id / surface=None / category mismatch).
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shop_probe.fidelity import (
    CohortFidelity,
    PairFidelity,
    compute_cohort_fidelity,
    compute_pair_fidelity,
)
from shop_probe.report import (
    BrowserMeta,
    CategoryScore,
    JudgeCall,
    JudgePick,
    JudgeTruth,
    ProbeReport,
)
from shop_probe.surface.metrics import SurfaceMetrics
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #

_RUBRIC_HASH: str = "a" * 64
_TIMESTAMP: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _surface(**overrides: float) -> SurfaceMetrics:
    base: dict[str, float] = {
        "distinct_templates": 5,
        "routes_crawled": 50,
        "interactables_per_template_median": 30.0,
        "interactables_per_template_p95": 90.0,
        "forms_total": 4,
        "form_fields_total": 20,
        "catalog_products": 100,
        "catalog_collections": 12,
        "catalog_variants": 250,
        "filter_x_sort_state_space": 64,
        "median_dom_kb_gz": 80.0,
        "accessibility_nodes_per_template_median": 400.0,
    }
    base.update(overrides)
    return SurfaceMetrics.model_validate(base)


def _categories(values: dict[str, float]) -> tuple[CategoryScore, ...]:
    return tuple(
        CategoryScore(
            category=name,
            weight_passed=cov * 10.0,
            weight_total=10.0,
            coverage=cov,
        )
        for name, cov in values.items()
    )


def _report(
    *,
    label: str,
    kind: str,
    pair_id: str | None,
    coverages: dict[str, float],
    coverage_weighted: float,
    surface: SurfaceMetrics | None,
) -> ProbeReport:
    target = Target(label=label, base_url="http://localhost:4000", kind=kind, pair_id=pair_id)  # type: ignore[arg-type]
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        probe_results=(),
        categories=_categories(coverages),
        coverage_core=coverage_weighted,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=coverage_weighted,
        surface=surface,
        judge_calls=(),
        rerun_index=1,
        flake_rate_per_probe={},
    )


def _sandbox_report(**overrides: object) -> ProbeReport:
    base: dict[str, object] = {
        "label": "sandbox/hardware",
        "kind": "sandbox",
        "pair_id": "pair_1",
        "coverages": {"site_shell": 0.7, "cart": 0.5},
        "coverage_weighted": 0.6,
        "surface": _surface(distinct_templates=4, catalog_products=50),
    }
    base.update(overrides)
    return _report(**base)  # type: ignore[arg-type]


def _source_report(**overrides: object) -> ProbeReport:
    base: dict[str, object] = {
        "label": "source/hardware",
        "kind": "source",
        "pair_id": "pair_1",
        "coverages": {"site_shell": 0.9, "cart": 0.8},
        "coverage_weighted": 0.85,
        "surface": _surface(distinct_templates=8, catalog_products=200),
    }
    base.update(overrides)
    return _report(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Coverage gap.
# --------------------------------------------------------------------------- #


def test_coverage_gap_is_source_minus_sandbox_per_category() -> None:
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
    )
    # site_shell: 0.9 - 0.7 = 0.2; cart: 0.8 - 0.5 = 0.3.
    assert fidelity.coverage_gap == pytest.approx({"site_shell": 0.2, "cart": 0.3})
    # weighted: 0.85 - 0.6 = 0.25.
    assert fidelity.coverage_gap_weighted == pytest.approx(0.25)


def test_coverage_gap_weighted_is_zero_at_parity() -> None:
    sandbox = _sandbox_report(coverages={"a": 0.5}, coverage_weighted=0.5)
    source = _source_report(coverages={"a": 0.5}, coverage_weighted=0.5)
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=sandbox,
        source_report=source,
    )
    assert fidelity.coverage_gap_weighted == pytest.approx(0.0)
    assert fidelity.coverage_gap == pytest.approx({"a": 0.0})


def test_coverage_gap_rejects_category_mismatch() -> None:
    sandbox = _sandbox_report(coverages={"site_shell": 0.7})
    source = _source_report(coverages={"cart": 0.8})
    with pytest.raises(ValueError, match="category mismatch"):
        compute_pair_fidelity(
            pair_id="pair_1",
            sandbox_report=sandbox,
            source_report=source,
        )


# --------------------------------------------------------------------------- #
# Surface ratio + geomean.
# --------------------------------------------------------------------------- #


def test_surface_ratio_is_sandbox_over_source_per_metric() -> None:
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(
            surface=_surface(distinct_templates=4, catalog_products=50),
        ),
        source_report=_source_report(
            surface=_surface(distinct_templates=8, catalog_products=200),
        ),
    )
    assert fidelity.surface_ratio["distinct_templates"] == pytest.approx(0.5)
    assert fidelity.surface_ratio["catalog_products"] == pytest.approx(0.25)
    # All other metrics equal in the fixture → ratio 1.0.
    assert fidelity.surface_ratio["forms_total"] == pytest.approx(1.0)


def test_surface_ratio_geomean_matches_manual_geomean() -> None:
    sandbox = _sandbox_report(
        surface=_surface(distinct_templates=4, catalog_products=50),
    )
    source = _source_report(
        surface=_surface(distinct_templates=8, catalog_products=200),
    )
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=sandbox,
        source_report=source,
    )
    ratios = list(fidelity.surface_ratio.values())
    expected = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
    assert fidelity.surface_ratio_geomean == pytest.approx(expected)
    # Sanity: with two ratios at 0.5/0.25 and the rest at 1.0, geomean
    # should be > 0 and < 1.
    assert 0.0 < fidelity.surface_ratio_geomean < 1.0


def test_surface_ratio_treats_both_zero_as_parity() -> None:
    # `forms_total` is allowed to be 0 in v1; both sides at 0 → ratio 1.0.
    sandbox = _sandbox_report(surface=_surface(forms_total=0))
    source = _source_report(surface=_surface(forms_total=0))
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=sandbox,
        source_report=source,
    )
    assert fidelity.surface_ratio["forms_total"] == pytest.approx(1.0)


def test_surface_ratio_rejects_source_zero_with_sandbox_positive() -> None:
    sandbox = _sandbox_report(surface=_surface(forms_total=3))
    source = _source_report(surface=_surface(forms_total=0))
    with pytest.raises(ValueError, match="surface_ratio"):
        compute_pair_fidelity(
            pair_id="pair_1",
            sandbox_report=sandbox,
            source_report=source,
        )


def test_surface_ratio_geomean_collapses_to_zero_when_any_ratio_is_zero() -> None:
    # source > 0, sandbox = 0 → ratio = 0 → geomean = 0.
    sandbox = _sandbox_report(surface=_surface(catalog_products=0))
    source = _source_report(surface=_surface(catalog_products=200))
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=sandbox,
        source_report=source,
    )
    assert fidelity.surface_ratio["catalog_products"] == pytest.approx(0.0)
    assert fidelity.surface_ratio_geomean == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Real-shop envelope.
# --------------------------------------------------------------------------- #


def test_sandbox_in_real_envelope_empty_when_no_population() -> None:
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
    )
    assert fidelity.sandbox_in_real_envelope == {}


def test_sandbox_in_real_envelope_flags_per_metric_inclusion() -> None:
    sandbox_metrics = _surface(distinct_templates=5, catalog_products=100)
    sandbox = _sandbox_report(surface=sandbox_metrics)
    source = _source_report(surface=_surface(distinct_templates=10, catalog_products=300))
    population = (
        _surface(distinct_templates=3, catalog_products=80),
        _surface(distinct_templates=8, catalog_products=400),
    )
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=sandbox,
        source_report=source,
        real_population=population,
    )
    # 5 ∈ [3, 8] → True; 100 ∈ [80, 400] → True.
    assert fidelity.sandbox_in_real_envelope["distinct_templates"] is True
    assert fidelity.sandbox_in_real_envelope["catalog_products"] is True


def test_sandbox_in_real_envelope_marks_outliers_false() -> None:
    sandbox = _sandbox_report(surface=_surface(distinct_templates=20))
    source = _source_report(surface=_surface(distinct_templates=10))
    population = (
        _surface(distinct_templates=3),
        _surface(distinct_templates=8),
    )
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=sandbox,
        source_report=source,
        real_population=population,
    )
    # 20 ∉ [3, 8] → False.
    assert fidelity.sandbox_in_real_envelope["distinct_templates"] is False


# --------------------------------------------------------------------------- #
# Pair-identity guards.
# --------------------------------------------------------------------------- #


def test_compute_pair_fidelity_rejects_wrong_sandbox_kind() -> None:
    sandbox = _sandbox_report().model_copy(
        update={
            "target": Target(
                label="oops",
                base_url="http://localhost",
                kind="source",
                pair_id="pair_1",
            )
        },
    )
    source = _source_report()
    with pytest.raises(ValueError, match=r"sandbox_report\.target\.kind"):
        compute_pair_fidelity(
            pair_id="pair_1",
            sandbox_report=sandbox,
            source_report=source,
        )


def test_compute_pair_fidelity_rejects_wrong_source_kind() -> None:
    sandbox = _sandbox_report()
    source = _source_report().model_copy(
        update={
            "target": Target(
                label="oops",
                base_url="http://localhost",
                kind="sandbox",
                pair_id="pair_1",
            )
        },
    )
    with pytest.raises(ValueError, match=r"source_report\.target\.kind"):
        compute_pair_fidelity(
            pair_id="pair_1",
            sandbox_report=sandbox,
            source_report=source,
        )


def test_compute_pair_fidelity_rejects_pair_id_mismatch() -> None:
    sandbox = _sandbox_report(pair_id="pair_other")
    source = _source_report()
    with pytest.raises(ValueError, match=r"sandbox_report\.target\.pair_id"):
        compute_pair_fidelity(
            pair_id="pair_1",
            sandbox_report=sandbox,
            source_report=source,
        )


def test_compute_pair_fidelity_rejects_axis_a_only_runs() -> None:
    sandbox = _sandbox_report(surface=None)
    source = _source_report()
    with pytest.raises(ValueError, match="surface metrics"):
        compute_pair_fidelity(
            pair_id="pair_1",
            sandbox_report=sandbox,
            source_report=source,
        )


# --------------------------------------------------------------------------- #
# Judge fields default to None until M4 (T3.1 explicit requirement).
# --------------------------------------------------------------------------- #


def test_pair_fidelity_judge_fields_default_to_none() -> None:
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
    )
    assert fidelity.judge_accuracy_experimental is None
    assert fidelity.judge_n_pairs is None
    assert fidelity.judge_dropped is None


def test_cohort_fidelity_judge_fields_default_to_none() -> None:
    cohort = compute_cohort_fidelity(pairs=())
    assert cohort.judge_accuracy_control is None
    assert cohort.judge_indistinguishability_gap is None
    assert cohort.real_shop_population == {}


# --------------------------------------------------------------------------- #
# Cohort aggregation.
# --------------------------------------------------------------------------- #


def test_compute_cohort_fidelity_aggregates_pairs_and_envelope() -> None:
    pair = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
    )
    population = (
        _surface(distinct_templates=3, catalog_products=80),
        _surface(distinct_templates=8, catalog_products=400),
        _surface(distinct_templates=5, catalog_products=200),
    )
    cohort = compute_cohort_fidelity(pairs=(pair,), real_population=population)
    assert cohort.pairs == (pair,)
    assert cohort.real_shop_population["distinct_templates"] == (3.0, 8.0)
    assert cohort.real_shop_population["catalog_products"] == (80.0, 400.0)
    # Every metric should be present in the envelope.
    assert set(cohort.real_shop_population) == set(SurfaceMetrics.model_fields)


# --------------------------------------------------------------------------- #
# JSON round-trip + extra="forbid".
# --------------------------------------------------------------------------- #


def test_pair_fidelity_json_round_trip() -> None:
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
    )
    payload = fidelity.model_dump_json()
    assert PairFidelity.model_validate_json(payload) == fidelity


def test_cohort_fidelity_json_round_trip() -> None:
    pair = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
    )
    cohort = compute_cohort_fidelity(
        pairs=(pair,),
        real_population=(_surface(), _surface(distinct_templates=10)),
    )
    payload = cohort.model_dump_json()
    # Tuples in the population dict become 2-element JSON arrays.
    parsed = json.loads(payload)
    assert parsed["real_shop_population"]["distinct_templates"] == [5.0, 10.0]
    assert CohortFidelity.model_validate_json(payload) == cohort


def test_pair_fidelity_rejects_unknown_field() -> None:
    payload = {
        "pair_id": "pair_1",
        "coverage_gap": {"site_shell": 0.0},
        "coverage_gap_weighted": 0.0,
        "surface_ratio": {"forms_total": 1.0},
        "surface_ratio_geomean": 1.0,
        "sandbox_in_real_envelope": {},
        "fidelity_score": 0.95,  # not in the schema
    }
    with pytest.raises(ValidationError, match="fidelity_score"):
        PairFidelity.model_validate(payload)


def test_cohort_fidelity_rejects_unknown_field() -> None:
    payload = {
        "pairs": [],
        "real_shop_population": {},
        "judge_model": "gpt-5",  # belongs in BrowserMeta-equivalent, not here
    }
    with pytest.raises(ValidationError, match="judge_model"):
        CohortFidelity.model_validate(payload)


def test_pair_fidelity_rejects_coverage_gap_weighted_out_of_range() -> None:
    with pytest.raises(ValidationError):
        PairFidelity(
            pair_id="pair_1",
            coverage_gap={},
            coverage_gap_weighted=1.5,
            surface_ratio={},
            surface_ratio_geomean=1.0,
        )


# --------------------------------------------------------------------------- #
# T5.3 — axis-C judge accuracy wired through fidelity (spec §5.5 step 7, §7 M5).
# --------------------------------------------------------------------------- #


def _judge_call(
    *,
    pick: JudgePick = "A",
    truth: JudgeTruth = "A",
    swap_consistent: bool = True,
    evidence_cited: bool = True,
) -> JudgeCall:
    return JudgeCall(
        task_id="t",
        pair_label=("a", "b"),
        judge_pick=pick,
        truth=truth,
        swap_consistent=swap_consistent,
        evidence_cited=evidence_cited,
        confidence=0.5,
        prompt_hash="0" * 64,
        response_text="{}",
    )


def test_compute_pair_fidelity_populates_experimental_judge_fields() -> None:
    """T5.3 — ``judge_accuracy_experimental`` is reported per pair."""
    calls = (
        _judge_call(pick="A", truth="A"),
        _judge_call(pick="A", truth="A"),
        _judge_call(pick="B", truth="A"),
    )
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
        experimental_judge_calls=calls,
    )
    assert fidelity.judge_accuracy_experimental == pytest.approx(2.0 / 3.0)
    assert fidelity.judge_n_pairs == 3  # noqa: PLR2004
    assert fidelity.judge_dropped == 0


def test_compute_pair_fidelity_drops_swap_inconsistent_calls() -> None:
    """Spec §5.5 step 6: swap-inconsistent calls drop out of the denominator."""
    calls = (
        _judge_call(pick="A", truth="A"),
        _judge_call(pick="B", truth="A", swap_consistent=False),
    )
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
        experimental_judge_calls=calls,
    )
    assert fidelity.judge_accuracy_experimental == pytest.approx(1.0)
    assert fidelity.judge_n_pairs == 2  # noqa: PLR2004
    assert fidelity.judge_dropped == 1


def test_compute_pair_fidelity_empty_judge_calls_keeps_n_pairs_zero() -> None:
    """An empty axis-C invocation reports zero kept calls and ``None`` accuracy."""
    fidelity = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
        experimental_judge_calls=(),
    )
    assert fidelity.judge_accuracy_experimental is None
    assert fidelity.judge_n_pairs == 0
    assert fidelity.judge_dropped == 0


def test_compute_cohort_fidelity_reports_control_accuracy_and_gap() -> None:
    """T5.3 — ``judge_accuracy_control`` and indistinguishability gap are reported."""
    pair = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
        experimental_judge_calls=(
            _judge_call(pick="A", truth="A"),
            _judge_call(pick="A", truth="A"),
            _judge_call(pick="A", truth="A"),
        ),
    )
    control_calls = (
        _judge_call(pick="A", truth="A"),
        _judge_call(pick="B", truth="A"),
    )
    cohort = compute_cohort_fidelity(
        pairs=(pair,),
        control_judge_calls=control_calls,
    )
    assert cohort.judge_accuracy_control == pytest.approx(0.5)
    # Gap = mean(experimental) - control = 1.0 - 0.5 = 0.5.
    assert cohort.judge_indistinguishability_gap == pytest.approx(0.5)


def test_compute_cohort_fidelity_skips_gap_when_any_pair_missing_experimental() -> None:
    """Mixed M3-pilot + M5 pairs leave the cohort gap unset (avoid lying)."""
    pair_with = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
        experimental_judge_calls=(_judge_call(pick="A", truth="A"),),
    )
    pair_without = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
    )
    cohort = compute_cohort_fidelity(
        pairs=(pair_with, pair_without),
        control_judge_calls=(_judge_call(pick="A", truth="A"),),
    )
    assert cohort.judge_accuracy_control == pytest.approx(1.0)
    assert cohort.judge_indistinguishability_gap is None


def test_compute_cohort_fidelity_skips_gap_when_control_all_dropped() -> None:
    """All-dropped control population → control accuracy is undefined; gap follows."""
    pair = compute_pair_fidelity(
        pair_id="pair_1",
        sandbox_report=_sandbox_report(),
        source_report=_source_report(),
        experimental_judge_calls=(_judge_call(pick="A", truth="A"),),
    )
    cohort = compute_cohort_fidelity(
        pairs=(pair,),
        control_judge_calls=(_judge_call(pick="A", truth="A", swap_consistent=False),),
    )
    assert cohort.judge_accuracy_control is None
    assert cohort.judge_indistinguishability_gap is None
