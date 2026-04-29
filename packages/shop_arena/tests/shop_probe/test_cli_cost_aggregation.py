"""Tests for v1.3 cost projection + aggregation in ``shop_probe.cli``.

Covers impl plan T6.2:

* ``_build_probe_result`` copies ``judge_cost_usd`` / ``judge_model`` /
  ``agent_cost_usd`` / ``agent_model`` from :attr:`ProbeOutcome.extra`.
* Deterministic outcomes (empty ``extra``) leave the four fields ``None``.
* ``_aggregate_cost_totals`` sums per-probe costs into the report rollup,
  and returns ``None`` when no probe carried the field — distinguishing
  "v1.1 cohort" from "v1.3 cohort with $0 calls".
"""

from __future__ import annotations

import pytest

from shop_probe.cli import _aggregate_cost_totals, _build_probe_result
from shop_probe.probes._runner import ProbeOutcome
from shop_probe.report import ProbeResult


def test_build_probe_result_copies_v1_3_cost_fields_from_extra() -> None:
    outcome = ProbeOutcome(
        passed=True,
        duration_ms=87_412,
        extra={
            "judge_cost_usd": 0.0123,
            "judge_model": "claude-opus-4-7",
            "agent_cost_usd": 0.2456,
            "agent_model": "claude-opus-4-7",
        },
    )
    result = _build_probe_result("collection.sort.changes_order", outcome)
    assert result.judge_cost_usd == pytest.approx(0.0123)
    assert result.judge_model == "claude-opus-4-7"
    assert result.agent_cost_usd == pytest.approx(0.2456)
    assert result.agent_model == "claude-opus-4-7"


def test_build_probe_result_deterministic_outcome_keeps_costs_none() -> None:
    outcome = ProbeOutcome(passed=True, duration_ms=412)
    result = _build_probe_result("site_shell.header.sticky", outcome)
    assert result.judge_cost_usd is None
    assert result.judge_model is None
    assert result.agent_cost_usd is None
    assert result.agent_model is None


def test_build_probe_result_partial_extra_only_judge() -> None:
    """Judge-only ``extra`` (current runner) leaves agent fields ``None``."""
    outcome = ProbeOutcome(
        passed=True,
        duration_ms=100,
        extra={
            "judge_cost_usd": 0.01,
            "judge_model": "claude-opus-4-7",
        },
    )
    result = _build_probe_result("p", outcome)
    assert result.judge_cost_usd == pytest.approx(0.01)
    assert result.judge_model == "claude-opus-4-7"
    assert result.agent_cost_usd is None
    assert result.agent_model is None


def test_build_probe_result_ignores_malformed_extra_values() -> None:
    """Non-numeric / empty values are silently dropped to ``None``."""
    outcome = ProbeOutcome(
        passed=True,
        duration_ms=100,
        extra={
            "judge_cost_usd": "not-a-number",  # type: ignore[dict-item]
            "judge_model": "",
            "agent_cost_usd": True,  # type: ignore[dict-item] — bool rejected
        },
    )
    result = _build_probe_result("p", outcome)
    assert result.judge_cost_usd is None
    assert result.judge_model is None
    assert result.agent_cost_usd is None


def _result(
    probe_id: str,
    *,
    judge_cost_usd: float | None = None,
    agent_cost_usd: float | None = None,
) -> ProbeResult:
    return ProbeResult(
        id=probe_id,
        passed=True,
        duration_ms=10,
        judge_cost_usd=judge_cost_usd,
        agent_cost_usd=agent_cost_usd,
    )


def test_aggregate_cost_totals_sums_per_probe_costs() -> None:
    results = [
        _result("a", judge_cost_usd=0.01, agent_cost_usd=0.25),
        _result("b", judge_cost_usd=0.02, agent_cost_usd=0.30),
        _result("c"),  # deterministic — contributes nothing
    ]
    judge_total, agent_total = _aggregate_cost_totals(results)
    assert judge_total == pytest.approx(0.03)
    assert agent_total == pytest.approx(0.55)


def test_aggregate_cost_totals_no_v1_3_results_returns_none() -> None:
    """v1.1 cohort: every probe is deterministic, so totals stay ``None``."""
    results = [_result("a"), _result("b")]
    judge_total, agent_total = _aggregate_cost_totals(results)
    assert judge_total is None
    assert agent_total is None


def test_aggregate_cost_totals_zero_cost_v1_3_run_is_distinct_from_none() -> None:
    """All-zero v1.3 calls roll up to ``0.0``, not ``None``."""
    results = [
        _result("a", judge_cost_usd=0.0, agent_cost_usd=0.0),
        _result("b", judge_cost_usd=0.0, agent_cost_usd=0.0),
    ]
    judge_total, agent_total = _aggregate_cost_totals(results)
    assert judge_total == 0.0
    assert agent_total == 0.0
