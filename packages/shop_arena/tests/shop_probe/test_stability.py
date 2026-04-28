"""Tests for `shop_probe.stability` (T5.2 — spec §5.8).

Covers the rerun-aggregation contract:

* Per-probe flake rate is ``0.0`` when every run agrees and ``≥ 1/3``
  when at least one run disagrees on ``passed`` for ``N=3`` reruns.
* ``passed=None`` ("not_applicable") is treated as a distinct outcome
  so a probe that flips between applicable and not-applicable still
  flakes (spec §5.8).
* :func:`consolidate_rerun_group` stamps the aggregated
  ``flake_rate_per_probe`` onto the canonical (lowest-``rerun_index``)
  report and leaves all other fields unchanged.
* Mismatched rerun groups (different target, rubric, or runner pin)
  are rejected up front via :class:`RerunGroupError`.
* :func:`exceeds_flake_gate` defaults to spec §5.8's 1% threshold and
  reports the violating probe ids so the M5 acceptance script can fail
  loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shop_probe.report import (
    BrowserMeta,
    ProbeReport,
    ProbeResult,
)
from shop_probe.stability import (
    FLAKE_RATE_GATE,
    RerunGroupError,
    aggregate_flake_rates,
    consolidate_rerun_group,
    exceeds_flake_gate,
)
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

_TARGET: Target = Target(
    label="sandbox/1",
    base_url="http://localhost:4000",
    kind="sandbox",
    pair_id="pair_1",
)
_RUBRIC_HASH: str = "a" * 64
_OTHER_TARGET: Target = Target(
    label="sandbox/2",
    base_url="http://localhost:4001",
    kind="sandbox",
    pair_id="pair_2",
)


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.0 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _build_report(
    *,
    rerun_index: int,
    results: tuple[ProbeResult, ...],
    target: Target = _TARGET,
    rubric_hash: str = _RUBRIC_HASH,
    runner_version: str = "0.0.0",
    timestamp: datetime | None = None,
) -> ProbeReport:
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=rubric_hash,
        runner_version=runner_version,
        runtime=_browser_meta(),
        timestamp=timestamp or datetime(2026, 1, 15, 12, rerun_index, 0, tzinfo=UTC),
        probe_results=results,
        coverage_core=1.0,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=1.0,
        rerun_index=rerun_index,
    )


def _result(probe_id: str, passed: bool | None) -> ProbeResult:
    return ProbeResult(id=probe_id, passed=passed, duration_ms=10)


# --------------------------------------------------------------------------- #
# aggregate_flake_rates
# --------------------------------------------------------------------------- #


def test_aggregate_flake_rates_zero_when_every_run_agrees() -> None:
    """All three runs returned the same outcome → flake rate is 0."""
    runs = tuple(
        _build_report(
            rerun_index=i,
            results=(_result("a.b", passed=True), _result("c.d", passed=False)),
        )
        for i in (1, 2, 3)
    )
    rates = aggregate_flake_rates(runs)
    assert rates == {"a.b": 0.0, "c.d": 0.0}


def test_aggregate_flake_rates_minority_disagreement_with_three_runs() -> None:
    """One outlier in three runs → ``1/3`` flake rate for that probe."""
    runs = (
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=2, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=3, results=(_result("a.b", passed=False),)),
    )
    rates = aggregate_flake_rates(runs)
    assert rates["a.b"] == pytest.approx(1.0 / 3.0)


def test_aggregate_flake_rates_treats_none_as_third_outcome() -> None:
    """``passed=None`` is a distinct outcome from True/False (spec §5.8)."""
    runs = (
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=2, results=(_result("a.b", passed=False),)),
        _build_report(rerun_index=3, results=(_result("a.b", passed=None),)),
    )
    rates = aggregate_flake_rates(runs)
    # All three outcomes distinct → modal_count = 1 → flake = 1 - 1/3 = 2/3.
    assert rates["a.b"] == pytest.approx(2.0 / 3.0)


def test_aggregate_flake_rates_missing_probe_counts_as_drift() -> None:
    """A probe missing from one run flakes against the runs that saw it."""
    runs = (
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=2, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=3, results=()),
    )
    rates = aggregate_flake_rates(runs)
    # Two ``True`` plus one missing-sentinel → modal_count = 2 → 1/3 flake.
    assert rates["a.b"] == pytest.approx(1.0 / 3.0)


def test_aggregate_flake_rates_keys_are_sorted_union_of_probes() -> None:
    """Keys are the alphabetically-sorted union across the rerun group."""
    runs = (
        _build_report(rerun_index=1, results=(_result("z.y", passed=True),)),
        _build_report(
            rerun_index=2,
            results=(_result("a.a", passed=True), _result("z.y", passed=True)),
        ),
        _build_report(rerun_index=3, results=(_result("a.a", passed=True),)),
    )
    rates = aggregate_flake_rates(runs)
    assert list(rates.keys()) == ["a.a", "z.y"]


def test_aggregate_flake_rates_is_order_independent() -> None:
    """Permuting the input does not change the per-probe flake rate."""
    runs = [
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=2, results=(_result("a.b", passed=False),)),
        _build_report(rerun_index=3, results=(_result("a.b", passed=True),)),
    ]
    forward = aggregate_flake_rates(tuple(runs))
    reverse = aggregate_flake_rates(tuple(reversed(runs)))
    assert forward == reverse


def test_aggregate_flake_rates_rejects_empty_input() -> None:
    with pytest.raises(RerunGroupError, match="at least one report"):
        aggregate_flake_rates(())


def test_aggregate_flake_rates_rejects_mismatched_targets() -> None:
    runs = (
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(
            rerun_index=2,
            results=(_result("a.b", passed=True),),
            target=_OTHER_TARGET,
        ),
    )
    with pytest.raises(RerunGroupError, match="rerun group mismatch"):
        aggregate_flake_rates(runs)


def test_aggregate_flake_rates_rejects_mismatched_rubric_hash() -> None:
    runs = (
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(
            rerun_index=2,
            results=(_result("a.b", passed=True),),
            rubric_hash="b" * 64,
        ),
    )
    with pytest.raises(RerunGroupError, match="rerun group mismatch"):
        aggregate_flake_rates(runs)


def test_aggregate_flake_rates_rejects_mismatched_runner_version() -> None:
    runs = (
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(
            rerun_index=2,
            results=(_result("a.b", passed=True),),
            runner_version="9.9.9",
        ),
    )
    with pytest.raises(RerunGroupError, match="rerun group mismatch"):
        aggregate_flake_rates(runs)


# --------------------------------------------------------------------------- #
# consolidate_rerun_group
# --------------------------------------------------------------------------- #


def test_consolidate_picks_lowest_rerun_index_and_stamps_flake() -> None:
    """The canonical row is the smallest-``rerun_index`` report."""
    runs = (
        _build_report(rerun_index=2, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=1, results=(_result("a.b", passed=False),)),
        _build_report(rerun_index=3, results=(_result("a.b", passed=True),)),
    )
    consolidated = consolidate_rerun_group(runs)
    assert consolidated.rerun_index == 1
    # Canonical row was the False outcome — its probe_results carry over.
    (result,) = consolidated.probe_results
    assert result.passed is False
    # And flake_rate is stamped from the full N=3 group: 2 True vs 1 False
    # → modal_count = 2 → flake = 1/3.
    assert consolidated.flake_rate_per_probe["a.b"] == pytest.approx(1.0 / 3.0)


def test_consolidate_preserves_other_report_fields() -> None:
    """``model_copy`` only updates ``flake_rate_per_probe``."""
    runs = (
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=2, results=(_result("a.b", passed=True),)),
    )
    consolidated = consolidate_rerun_group(runs)
    canonical = runs[0]
    assert consolidated.target == canonical.target
    assert consolidated.rubric_version == canonical.rubric_version
    assert consolidated.rubric_hash == canonical.rubric_hash
    assert consolidated.runner_version == canonical.runner_version
    assert consolidated.timestamp == canonical.timestamp
    assert consolidated.probe_results == canonical.probe_results
    assert consolidated.coverage_weighted == canonical.coverage_weighted


def test_consolidate_round_trips_through_json() -> None:
    """Stamped flake rate survives JSON serialization (paper figures read JSON)."""
    runs = (
        _build_report(rerun_index=1, results=(_result("a.b", passed=True),)),
        _build_report(rerun_index=2, results=(_result("a.b", passed=False),)),
    )
    consolidated = consolidate_rerun_group(runs)
    reloaded = ProbeReport.model_validate_json(consolidated.model_dump_json())
    assert reloaded == consolidated
    assert reloaded.flake_rate_per_probe["a.b"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# exceeds_flake_gate
# --------------------------------------------------------------------------- #


def test_exceeds_flake_gate_returns_empty_when_clean() -> None:
    assert exceeds_flake_gate({"a.b": 0.0, "c.d": 0.0}) == ()


def test_exceeds_flake_gate_default_is_one_percent() -> None:
    """Spec §5.8 paper-claim gate is 1% per probe."""
    assert pytest.approx(0.01) == FLAKE_RATE_GATE


def test_exceeds_flake_gate_lists_violators_sorted() -> None:
    rates = {"a.b": 0.0, "c.d": 1.0 / 3.0, "e.f": 2.0 / 3.0}
    assert exceeds_flake_gate(rates) == ("c.d", "e.f")


def test_exceeds_flake_gate_respects_custom_gate() -> None:
    rates = {"a.b": 0.5, "c.d": 0.34}
    # gate=0.4 → only "a.b" exceeds.
    assert exceeds_flake_gate(rates, gate=0.4) == ("a.b",)
