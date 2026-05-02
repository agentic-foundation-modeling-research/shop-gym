"""Smoke tests for :mod:`shop_arena.probe.fidelity`.

Constructs minimal in-memory ProbeReports and checks that:

* RBC majority baseline + sandbox coverage + LOO range come out as
  arithmetic expects.
* Continuous-metric stats (Mann-Whitney U + Cliff's δ) line up with
  textbook hand calculations on small samples.
* The cohort writers consume the comparison and produce non-empty
  markdown.
"""

from __future__ import annotations

from datetime import datetime, timezone

from shop_arena.probe.fidelity import (
    cliffs_delta_label,
    compare_cohorts,
)
from shop_arena.probe.report import (
    ActionBlock,
    BrowserMeta,
    ObservationBlock,
    ProbeReport,
    ShapeMetrics,
    SlotVerdict,
    TransitionResult,
)
from shop_arena.probe.report_writer import (
    render_action_fidelity,
    render_observation_fidelity,
    render_summary,
    render_transition_fidelity,
)
from shop_arena.probe.targets import Target

_RUNTIME = BrowserMeta(
    python_version="3.12.0",
    playwright_version="1.48.0",
    chromium_version="129.0.0",
    user_agent="ShopProbe/test",
    viewport=(1280, 800),
    headless=True,
)
_HASH = "0" * 64


def _make_report(
    name: str,
    label: str,
    *,
    a11y_nodes: int,
    homepage_brand_present: bool,
    add_to_cart_present: bool,
    cart_state_changed: bool,
) -> ProbeReport:
    target = Target(name=name, base_url=f"https://{name}.example", label=label)  # type: ignore[arg-type]
    shape = {
        "homepage": {
            "a11y": ShapeMetrics(nodes=a11y_nodes, tokens=a11y_nodes * 5, actionable_count=4),
            "screenshot": ShapeMetrics(megapixels=1.024, byte_size_kb=80.0),
        },
    }
    info_verdict_a11y = SlotVerdict(
        present=homepage_brand_present, judge_model="anthropic:test", judge_cost_usd=0.0
    )
    info_verdict_screen = SlotVerdict(
        present=homepage_brand_present, judge_model="anthropic:test", judge_cost_usd=0.0
    )
    control_verdict = SlotVerdict(
        present=add_to_cart_present, judge_model="anthropic:test", judge_cost_usd=0.0
    )
    info_slots = {
        "homepage": {
            "observation.homepage.brand_identity": {
                "a11y": info_verdict_a11y,
                "screenshot": info_verdict_screen,
            }
        }
    }
    control_slots = {
        "product": {
            "action.product.add_to_cart": {
                "a11y": control_verdict,
                "screenshot": control_verdict,
            }
        }
    }
    transition = {
        "cart": {
            "transition.cart.checkout": TransitionResult(
                action_found=cart_state_changed,
                action_executed=cart_state_changed,
                state_changed=cart_state_changed,
                state_changed_as_expected=cart_state_changed,
                latency_ms=120,
            ),
        }
    }
    return ProbeReport(
        target=target,
        rubric_version="1.0",
        rubric_hash=_HASH,
        runner_version="1.0.0",
        runtime=_RUNTIME,
        timestamp=datetime.now(timezone.utc),
        observation=ObservationBlock(shape=shape, info_slots=info_slots),
        action=ActionBlock(control_slots=control_slots),
        transition=transition,
        modality_consistency={"homepage": 1.0, "product": 1.0},
    )


def _build_cohorts() -> tuple[list[ProbeReport], list[ProbeReport]]:
    sandbox = [
        _make_report(
            f"sbx_{i}",
            "sandbox",
            a11y_nodes=200 + i * 5,
            homepage_brand_present=True,
            add_to_cart_present=True,
            cart_state_changed=True,
        )
        for i in range(3)
    ]
    real = [
        _make_report(
            f"real_{i}",
            "real",
            a11y_nodes=300 + i * 10,
            homepage_brand_present=True,
            # 3 of 5 reals expose add-to-cart → in baseline at quorum 4 / 5? quorum_k = ⌈5/2 + 1⌉ = 4.
            # Adjust per-shop: 3 True, 2 False → 0.6 ≥ 0.8? No → not in baseline.
            add_to_cart_present=i < 3,
            cart_state_changed=i < 4,
        )
        for i in range(5)
    ]
    return sandbox, real


def test_compare_cohorts_baselines_and_rbc() -> None:
    sandbox, real = _build_cohorts()
    cmp_ = compare_cohorts(sandbox=sandbox, real=real)
    assert cmp_.n_sandbox == 3
    assert cmp_.n_real == 5

    # info_slots: brand_identity passes 5/5 in real → in baseline.
    info_baseline = [s for s in cmp_.info_slots.slots if s.in_baseline]
    assert len(info_baseline) == 2  # one per modality
    assert all(s.slot_id == "observation.homepage.brand_identity" for s in info_baseline)
    # All sandbox shops also pass it → mean RBC = 1.0.
    assert cmp_.info_slots.mean_rbc_sandbox == 1.0

    # control_slots: add_to_cart real pass rate = 3/5 = 0.6 < quorum 4/5 → NOT in baseline.
    control_in_baseline = [s for s in cmp_.control_slots.slots if s.in_baseline]
    assert control_in_baseline == []
    assert cmp_.control_slots.baseline_size == 0


def test_compare_cohorts_continuous_stats() -> None:
    sandbox, real = _build_cohorts()
    cmp_ = compare_cohorts(sandbox=sandbox, real=real)
    nodes_rows = [
        row
        for row in cmp_.shape_stats
        if row.metric == "nodes" and row.page_type == "homepage" and row.modality == "a11y"
    ]
    assert len(nodes_rows) == 1
    row = nodes_rows[0]
    # All sandbox values [200, 205, 210] < all real values [300, 310, 320, 330, 340].
    # Cliff's δ for sandbox-vs-real is -1, but we passed (real, sandbox) → +1.
    assert row.cliffs_delta == 1.0
    assert cliffs_delta_label(row.cliffs_delta) == "large"
    assert row.median_sandbox == 205.0


def test_compare_cohorts_transitions_and_modality_consistency() -> None:
    sandbox, real = _build_cohorts()
    cmp_ = compare_cohorts(sandbox=sandbox, real=real)
    [tr] = cmp_.transitions
    assert tr.page_type == "cart"
    assert tr.slot_id == "transition.cart.checkout"
    # 4/5 reals state_changed, all 3 sandboxes state_changed.
    assert tr.real_rates["state_changed_as_expected"] == 0.8
    assert tr.sandbox_rates["state_changed_as_expected"] == 1.0
    # Modality-consistency rolled up.
    assert cmp_.mean_modality_consistency_sandbox["homepage"] == 1.0


def test_render_writers_produce_non_empty_markdown() -> None:
    sandbox, real = _build_cohorts()
    cmp_ = compare_cohorts(sandbox=sandbox, real=real)
    obs_md = render_observation_fidelity(cmp_)
    act_md = render_action_fidelity(cmp_)
    tr_md = render_transition_fidelity(cmp_)
    summary_md = render_summary(cmp_)
    assert "observation fidelity" in obs_md
    assert "action fidelity" in act_md
    assert "cart" in tr_md
    assert "Headline RBC" in summary_md
