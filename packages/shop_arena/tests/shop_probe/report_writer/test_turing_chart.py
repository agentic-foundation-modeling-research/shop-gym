"""Tests for `shop_probe.report_writer.turing_chart` (T6.4 — spec §8.4 row 4).

Covers:

* SVG envelope: ``render_turing_chart_svg`` returns a self-contained
  SVG document starting with ``<svg ...>`` and ending with ``</svg>\\n``.
* Determinism: the same inputs + ``bootstrap_seed`` produce
  byte-identical output across calls (paper figures must be reproducible
  from versioned reports — T6.4 acceptance check).
* One row per pair, in input order, plus the cohort-level intra-real
  control row appended last (spec §8.4 row 4 + tables convention).
* Spec §5.5 guardrails are applied: swap-inconsistent + no-evidence
  calls are dropped from both numerator and denominator before the
  point-estimate is computed.
* Reference markings:
  - vertical dashed line at ``acc = 0.5`` (naive target);
  - vertical solid line at the control accuracy;
  - shaded ``[control - ε, control + ε]`` band across every row.
* Per-row annotation reports the point estimate, the 95% bootstrap CI,
  and (for pair rows) the signed delta vs. control plus a ``✓``/``✗``
  marker that flips at exactly ``|Δ| > ε``.
* Validation: empty ``pairs``, empty/all-dropped ``control_calls``,
  pairs with no surviving calls, duplicate ``pair_id``, out-of-range
  ``epsilon``, and non-positive ``bootstrap_iters`` all raise
  ``ValueError``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import pytest

from shop_probe.report import JudgeCall
from shop_probe.report_writer.turing_chart import (
    PairTuringData,
    render_turing_chart_svg,
)

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #

_PROMPT_HASH: str = "a" * 64


def _call(
    *,
    pick: str,
    truth: str,
    swap_consistent: bool = True,
    evidence_cited: bool = True,
    task_id: str = "task_01",
    pair_label: tuple[str, str] = ("A_traj", "B_traj"),
) -> JudgeCall:
    return JudgeCall(
        task_id=task_id,
        pair_label=pair_label,
        judge_pick=pick,  # type: ignore[arg-type]
        truth=truth,  # type: ignore[arg-type]
        swap_consistent=swap_consistent,
        evidence_cited=evidence_cited,
        confidence=0.9,
        prompt_hash=_PROMPT_HASH,
        response_text="ok",
    )


def _calls(spec: Sequence[tuple[str, str]]) -> tuple[JudgeCall, ...]:
    """Build kept calls from ``(pick, truth)`` tuples."""
    return tuple(_call(pick=pick, truth=truth) for pick, truth in spec)


def _bal_correct(n_correct: int, n_incorrect: int) -> tuple[JudgeCall, ...]:
    """``n_correct`` calls with pick==truth, ``n_incorrect`` with pick!=truth."""
    return (
        *(_call(pick="A", truth="A") for _ in range(n_correct)),
        *(_call(pick="A", truth="B") for _ in range(n_incorrect)),
    )


# --------------------------------------------------------------------------- #
# SVG envelope.
# --------------------------------------------------------------------------- #


def test_output_is_self_contained_svg_document() -> None:
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_1", judge_calls=_bal_correct(5, 5)),),
        control_calls=_bal_correct(5, 5),
        bootstrap_iters=50,
    )
    assert out.startswith("<svg ")
    assert 'xmlns="http://www.w3.org/2000/svg"' in out
    assert out.endswith("</svg>\n")


def test_output_is_deterministic_across_calls() -> None:
    pairs = (PairTuringData(pair_id="pair_1", judge_calls=_bal_correct(7, 3)),)
    control = _bal_correct(5, 5)
    first = render_turing_chart_svg(
        pairs=pairs, control_calls=control, bootstrap_iters=64, bootstrap_seed=7
    )
    second = render_turing_chart_svg(
        pairs=pairs, control_calls=control, bootstrap_iters=64, bootstrap_seed=7
    )
    assert first == second


def test_different_seeds_produce_different_ci_widths() -> None:
    pairs = (PairTuringData(pair_id="pair_1", judge_calls=_bal_correct(7, 3)),)
    control = _bal_correct(5, 5)
    a = render_turing_chart_svg(
        pairs=pairs, control_calls=control, bootstrap_iters=64, bootstrap_seed=1
    )
    b = render_turing_chart_svg(
        pairs=pairs, control_calls=control, bootstrap_iters=64, bootstrap_seed=2
    )
    assert a != b


# --------------------------------------------------------------------------- #
# Row layout.
# --------------------------------------------------------------------------- #


def test_one_row_per_pair_in_input_order_plus_control_last() -> None:
    pairs = (
        PairTuringData(pair_id="pair_1", judge_calls=_bal_correct(5, 5)),
        PairTuringData(pair_id="pair_2", judge_calls=_bal_correct(6, 4)),
        PairTuringData(pair_id="pair_3", judge_calls=_bal_correct(4, 6)),
    )
    out = render_turing_chart_svg(pairs=pairs, control_calls=_bal_correct(5, 5), bootstrap_iters=50)
    labels = re.findall(r'<g class="row" data-label="([^"]+)"', out)
    assert labels == ["pair_1", "pair_2", "pair_3", "intra-real control"]


def test_control_row_is_flagged_via_data_attribute() -> None:
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_1", judge_calls=_bal_correct(5, 5)),),
        control_calls=_bal_correct(5, 5),
        bootstrap_iters=50,
    )
    rows = re.findall(
        r'<g class="row" data-label="([^"]+)" data-control="(true|false)"',
        out,
    )
    assert rows == [
        ("pair_1", "false"),
        ("intra-real control", "true"),
    ]


# --------------------------------------------------------------------------- #
# Spec §5.5 guardrails — swap-inconsistent / no-evidence calls dropped.
# --------------------------------------------------------------------------- #


def test_point_estimate_drops_swap_inconsistent_and_no_evidence() -> None:
    # Kept: 4 correct, 1 incorrect → acc = 0.8.
    # Dropped: every flavor of disqualified call (inverted picks); none of
    # them should leak into the numerator or denominator.
    calls: tuple[JudgeCall, ...] = (
        _call(pick="A", truth="A"),
        _call(pick="A", truth="A"),
        _call(pick="A", truth="A"),
        _call(pick="A", truth="A"),
        _call(pick="A", truth="B"),
        # swap-inconsistent — must be dropped.
        _call(pick="A", truth="B", swap_consistent=False),
        _call(pick="A", truth="B", swap_consistent=False),
        # no-evidence — must be dropped.
        _call(pick="A", truth="B", evidence_cited=False),
    )
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=calls),),
        control_calls=_bal_correct(5, 5),
        bootstrap_iters=50,
    )
    # The pair row's annotation must report acc=0.800 — not 0.500
    # (which is what you'd get if dropped calls were counted as wrong).
    pair_row = _slice_row(out, "pair_x")
    assert "acc=0.800" in pair_row
    assert "acc=0.500" not in pair_row


def test_abstain_calls_count_against_accuracy() -> None:
    # 3 correct + 2 abstain (truth="A", pick="abstain" → not correct).
    calls: tuple[JudgeCall, ...] = (
        _call(pick="A", truth="A"),
        _call(pick="A", truth="A"),
        _call(pick="A", truth="A"),
        _call(pick="abstain", truth="A"),
        _call(pick="abstain", truth="A"),
    )
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=calls),),
        control_calls=_bal_correct(5, 5),
        bootstrap_iters=50,
    )
    pair_row = _slice_row(out, "pair_x")
    assert "acc=0.600" in pair_row


# --------------------------------------------------------------------------- #
# Reference markings: ε-band, naive 0.5, control line.
# --------------------------------------------------------------------------- #


def test_epsilon_band_is_shaded_rectangle_centered_on_control() -> None:
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
        control_calls=_bal_correct(5, 5),
        epsilon=0.1,
        bootstrap_iters=50,
    )
    band = _slice_group(out, "epsilon-band")
    assert 'data-epsilon="0.100"' in band
    rect = re.search(r'<rect [^/]*x="([\d.]+)"[^/]*width="([\d.]+)"', band)
    assert rect is not None
    x = float(rect.group(1))
    width = float(rect.group(2))
    # control = 0.5 ± 0.1 spans 0.2 of the [0, 1] axis.
    assert width == pytest.approx(0.2 * (760 - 16 - 196 - 188), rel=1e-3)
    # band starts at control - ε = 0.4.
    assert x == pytest.approx(16 + 196 + 0.4 * (760 - 16 - 196 - 188), rel=1e-3)


def test_naive_reference_line_is_dashed_at_05() -> None:
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
        control_calls=_bal_correct(5, 5),
        bootstrap_iters=50,
    )
    block = _slice_group(out, "reference-naive")
    assert 'data-value="0.500"' in block
    assert 'stroke-dasharray="4 3"' in block


def test_control_reference_line_is_solid() -> None:
    # Control acc = 7/10 = 0.7 to make the value distinguishable from
    # the naive 0.5 line.
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
        control_calls=_bal_correct(7, 3),
        bootstrap_iters=50,
    )
    block = _slice_group(out, "reference-control")
    assert 'data-value="0.700"' in block
    assert "stroke-dasharray" not in block


# --------------------------------------------------------------------------- #
# Per-row annotations.
# --------------------------------------------------------------------------- #


def test_pair_row_reports_signed_delta_with_within_marker() -> None:
    # Pair acc = 0.5, control acc = 0.5, ε = 0.1 → |Δ| = 0 ≤ ε → ✓.
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
        control_calls=_bal_correct(5, 5),
        epsilon=0.1,
        bootstrap_iters=50,
    )
    row = _slice_row(out, "pair_x")
    assert "Δ=+0.000" in row
    assert "✓" in row


def test_pair_row_marks_breach_when_delta_exceeds_epsilon() -> None:
    # Pair acc = 0.9, control acc = 0.5, ε = 0.1 → |Δ| = 0.4 > ε → ✗.
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(9, 1)),),
        control_calls=_bal_correct(5, 5),
        epsilon=0.1,
        bootstrap_iters=50,
    )
    row = _slice_row(out, "pair_x")
    assert "Δ=+0.400" in row
    assert "✗" in row


def test_control_row_does_not_render_a_delta_annotation() -> None:
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
        control_calls=_bal_correct(5, 5),
        epsilon=0.1,
        bootstrap_iters=50,
    )
    control_row = _slice_row(out, "intra-real control")
    assert "Δ=" not in control_row
    assert "✓" not in control_row
    assert "✗" not in control_row


def test_row_annotation_includes_bootstrap_ci_brackets() -> None:
    out = render_turing_chart_svg(
        pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
        control_calls=_bal_correct(5, 5),
        bootstrap_iters=50,
    )
    row = _slice_row(out, "pair_x")
    # ``acc=0.500 [lo, hi]`` with both lo and hi formatted to 3 decimals.
    assert re.search(r"acc=0\.500 \[\d\.\d{3}, \d\.\d{3}\]", row) is not None


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #


def test_empty_pairs_raises() -> None:
    with pytest.raises(ValueError, match="pairs must be non-empty"):
        render_turing_chart_svg(pairs=(), control_calls=_bal_correct(5, 5))


def test_empty_control_calls_raises() -> None:
    with pytest.raises(ValueError, match="control_calls has no surviving"):
        render_turing_chart_svg(
            pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
            control_calls=(),
        )


def test_pair_with_all_calls_dropped_raises() -> None:
    dropped = (
        _call(pick="A", truth="A", swap_consistent=False),
        _call(pick="A", truth="B", evidence_cited=False),
    )
    with pytest.raises(ValueError, match="pair 'pair_x' has no surviving"):
        render_turing_chart_svg(
            pairs=(PairTuringData(pair_id="pair_x", judge_calls=dropped),),
            control_calls=_bal_correct(5, 5),
        )


def test_duplicate_pair_id_raises() -> None:
    pair = PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5))
    with pytest.raises(ValueError, match="duplicate pair_id 'pair_x'"):
        render_turing_chart_svg(
            pairs=(pair, pair),
            control_calls=_bal_correct(5, 5),
        )


@pytest.mark.parametrize("epsilon", [0.0, -0.1, 1.0, 1.5])
def test_epsilon_out_of_range_raises(epsilon: float) -> None:
    with pytest.raises(ValueError, match=r"epsilon must be in \(0, 1\)"):
        render_turing_chart_svg(
            pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
            control_calls=_bal_correct(5, 5),
            epsilon=epsilon,
        )


def test_bootstrap_iters_below_one_raises() -> None:
    with pytest.raises(ValueError, match="bootstrap_iters must be ≥ 1"):
        render_turing_chart_svg(
            pairs=(PairTuringData(pair_id="pair_x", judge_calls=_bal_correct(5, 5)),),
            control_calls=_bal_correct(5, 5),
            bootstrap_iters=0,
        )


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _slice_group(svg: str, css_class: str) -> str:
    """Return the substring of ``svg`` containing ``<g class="…">``."""
    match = re.search(
        rf'<g class="{re.escape(css_class)}"[\s\S]*?</g>',
        svg,
    )
    assert match is not None, f"group {css_class!r} not found in svg"
    return match.group(0)


def _slice_row(svg: str, label: str) -> str:
    """Return the substring of ``svg`` for the row whose ``data-label`` matches.

    Walks ``<g`` / ``</g>`` pairs with a depth counter so nested groups
    inside the row (e.g. the error-bar group) don't truncate the slice.
    """
    start_pat = re.compile(rf'<g class="row" data-label="{re.escape(label)}"')
    start = start_pat.search(svg)
    assert start is not None, f"row with label={label!r} not found in svg"
    depth = 0
    pos = start.start()
    token_re = re.compile(r"<g\b|</g>")
    for m in token_re.finditer(svg, pos):
        if m.group(0) == "</g>":
            depth -= 1
            if depth == 0:
                return svg[pos : m.end()]
        else:
            depth += 1
    raise AssertionError(f"unterminated row group for label={label!r}")
