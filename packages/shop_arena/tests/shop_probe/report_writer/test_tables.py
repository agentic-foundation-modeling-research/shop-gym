"""Tests for `shop_probe.report_writer.tables` (T6.1 — spec §8.4 row 1).

Covers:

* Per-pair rows: one row per :class:`PairFidelity`, exactly three
  numeric cells (axes A/B/C), pair order preserved.
* Cohort-level intra-real control row appended last with empty axis-A
  and axis-B cells (spec §5.7 + §8.4 row 1).
* Numeric formatting:
  - ``coverage_gap_weighted`` carries an explicit sign so readers can
    tell which side the gap leans toward (spec §5.7).
  - Three-decimal fixed precision matches the CLI print convention.
* Missing axis-C measurements render as the em-dash placeholder rather
  than ``"None"`` or ``"0.0"`` (M3 pilot has no judge yet).
* Empty cohort still produces a well-formed table with the header,
  separator, and a control row.
* Output ends with a trailing newline so it concatenates cleanly into
  paper / report Markdown without manual editing.
"""

from __future__ import annotations

from shop_probe.fidelity import CohortFidelity, PairFidelity
from shop_probe.report_writer.tables import (
    CONTROL_ROW_LABEL,
    render_pair_fidelity_table,
)

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #

_SURFACE_RATIO_FIXTURE: dict[str, float] = {
    "distinct_templates": 0.5,
    "catalog_products": 0.25,
}
_COVERAGE_GAP_FIXTURE: dict[str, float] = {"site_shell": 0.2, "cart": 0.3}


def _pair_fidelity(
    *,
    pair_id: str = "pair_1",
    coverage_gap_weighted: float = 0.25,
    surface_ratio_geomean: float = 0.5,
    judge_accuracy_experimental: float | None = None,
    judge_n_pairs: int | None = None,
    judge_dropped: int | None = None,
) -> PairFidelity:
    return PairFidelity(
        pair_id=pair_id,
        coverage_gap=_COVERAGE_GAP_FIXTURE,
        coverage_gap_weighted=coverage_gap_weighted,
        surface_ratio=_SURFACE_RATIO_FIXTURE,
        surface_ratio_geomean=surface_ratio_geomean,
        judge_accuracy_experimental=judge_accuracy_experimental,
        judge_n_pairs=judge_n_pairs,
        judge_dropped=judge_dropped,
    )


def _cohort(
    *,
    pairs: tuple[PairFidelity, ...] = (),
    judge_accuracy_control: float | None = None,
) -> CohortFidelity:
    return CohortFidelity(
        pairs=pairs,
        judge_accuracy_control=judge_accuracy_control,
    )


# --------------------------------------------------------------------------- #
# Header + structure.
# --------------------------------------------------------------------------- #


def test_table_header_names_three_axes() -> None:
    out = render_pair_fidelity_table(_cohort(pairs=(_pair_fidelity(),)))
    header = out.splitlines()[0]
    assert "Pair" in header
    assert "Coverage gap (A)" in header
    assert "Surface ratio geomean (B)" in header
    assert "Judge accuracy experimental (C)" in header


def test_table_separator_is_markdown_alignment_row() -> None:
    out = render_pair_fidelity_table(_cohort(pairs=(_pair_fidelity(),)))
    separator = out.splitlines()[1]
    # Right-aligned numeric columns; first column is unaligned (label).
    assert separator == "|---|---:|---:|---:|"


def test_table_ends_with_trailing_newline() -> None:
    out = render_pair_fidelity_table(_cohort(pairs=(_pair_fidelity(),)))
    assert out.endswith("\n")


# --------------------------------------------------------------------------- #
# Per-pair rows.
# --------------------------------------------------------------------------- #


def test_one_row_per_pair_in_input_order() -> None:
    pairs = (
        _pair_fidelity(pair_id="pair_1"),
        _pair_fidelity(pair_id="pair_2"),
        _pair_fidelity(pair_id="pair_3"),
    )
    out = render_pair_fidelity_table(_cohort(pairs=pairs))
    body = out.splitlines()[2:-1]  # drop header, separator, control row.
    assert len(body) == len(pairs)
    assert "| pair_1 " in body[0]
    assert "| pair_2 " in body[1]
    assert "| pair_3 " in body[2]


def test_pair_row_carries_three_numeric_cells() -> None:
    out = render_pair_fidelity_table(
        _cohort(
            pairs=(
                _pair_fidelity(
                    coverage_gap_weighted=0.25,
                    surface_ratio_geomean=0.5,
                    judge_accuracy_experimental=0.51,
                    judge_n_pairs=10,
                    judge_dropped=0,
                ),
            ),
        ),
    )
    row = out.splitlines()[2]
    # Pipe-separated fields (drop leading + trailing empty splits).
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells == ["pair_1", "+0.250", "0.500", "0.510"]


def test_coverage_gap_carries_explicit_sign_in_both_directions() -> None:
    out = render_pair_fidelity_table(
        _cohort(
            pairs=(
                _pair_fidelity(pair_id="pair_pos", coverage_gap_weighted=0.123),
                _pair_fidelity(pair_id="pair_neg", coverage_gap_weighted=-0.456),
                _pair_fidelity(pair_id="pair_par", coverage_gap_weighted=0.0),
            ),
        ),
    )
    rows = out.splitlines()[2:5]
    assert "+0.123" in rows[0]
    assert "-0.456" in rows[1]
    # +0.000 (parity), not "0.000" — explicit sign is the spec §5.7 contract.
    assert "+0.000" in rows[2]


def test_missing_judge_accuracy_renders_as_em_dash() -> None:
    out = render_pair_fidelity_table(
        _cohort(pairs=(_pair_fidelity(judge_accuracy_experimental=None),)),
    )
    row = out.splitlines()[2]
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[-1] == "—"
    # Sanity: the placeholder must not be the string "None" or "0.000".
    assert "None" not in row
    assert "0.000" not in row


# --------------------------------------------------------------------------- #
# Control row.
# --------------------------------------------------------------------------- #


def test_control_row_is_appended_last() -> None:
    out = render_pair_fidelity_table(
        _cohort(
            pairs=(_pair_fidelity(pair_id="pair_1"),),
            judge_accuracy_control=0.5,
        ),
    )
    last_row = out.rstrip("\n").splitlines()[-1]
    assert CONTROL_ROW_LABEL in last_row


def test_control_row_axis_a_and_b_cells_are_empty() -> None:
    out = render_pair_fidelity_table(
        _cohort(judge_accuracy_control=0.5),
    )
    last_row = out.rstrip("\n").splitlines()[-1]
    cells = [c.strip() for c in last_row.strip("|").split("|")]
    # [label, axis A, axis B, axis C].
    assert cells[0] == CONTROL_ROW_LABEL
    assert cells[1] == "—"
    assert cells[2] == "—"
    assert cells[3] == "0.500"


def test_control_row_judge_accuracy_renders_as_em_dash_when_unset() -> None:
    out = render_pair_fidelity_table(_cohort())
    last_row = out.rstrip("\n").splitlines()[-1]
    cells = [c.strip() for c in last_row.strip("|").split("|")]
    assert cells == [CONTROL_ROW_LABEL, "—", "—", "—"]


# --------------------------------------------------------------------------- #
# Empty cohort (M3 pilot fallback).
# --------------------------------------------------------------------------- #


def test_empty_cohort_still_produces_header_and_control_row() -> None:
    out = render_pair_fidelity_table(_cohort())
    lines = out.rstrip("\n").splitlines()
    # Header + separator + control row (no pair rows).
    assert len(lines) == 3  # noqa: PLR2004
    assert "Pair" in lines[0]
    assert lines[1] == "|---|---:|---:|---:|"
    assert CONTROL_ROW_LABEL in lines[2]
