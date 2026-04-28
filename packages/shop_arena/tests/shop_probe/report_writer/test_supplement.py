"""Tests for `shop_probe.report_writer.supplement` (T7.5 — spec §5.9).

Covers:

* Header row names every emitted column (3 axis-A + 4 axis-B numerics
  alongside the environment label).
* One row per :class:`ProbeReport`, sorted by ``target.label`` so the
  rendered table is byte-stable across runs regardless of input order
  (T7.5 acceptance check).
* Numeric formatting:
  - Coverage cells render at three decimals (matches `tables.py`).
  - ``interactables_per_template_p95`` renders at one decimal (the only
    float-valued axis-B cell).
* Axis-B cells render as the em-dash placeholder when ``surface is
  None`` (axis-A-only baseline reports).
* Empty input still produces a header + separator pair so the
  supplement file is never silently absent.
* Output ends with a trailing newline so it concatenates cleanly into
  paper / report Markdown without manual editing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from shop_probe.report import BrowserMeta, ProbeReport
from shop_probe.report_writer.supplement import render_prior_work_supplement_table
from shop_probe.surface import SurfaceMetrics
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


def _baseline_report(
    *,
    label: str,
    coverage_core: float = 0.4,
    coverage_modern: float = 0.2,
    coverage_weighted: float = 0.3,
    surface: SurfaceMetrics | None = None,
) -> ProbeReport:
    target = Target(
        label=label,
        base_url="http://localhost:4001",
        kind="real_unpaired",
        pair_id=None,
    )
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        probe_results=(),
        categories=(),
        coverage_core=coverage_core,
        coverage_modern=coverage_modern,
        coverage_advanced=0.0,
        coverage_weighted=coverage_weighted,
        surface=surface,
        rerun_index=1,
        flake_rate_per_probe={},
    )


# --------------------------------------------------------------------------- #
# Header + structure.
# --------------------------------------------------------------------------- #


def test_header_names_every_emitted_column() -> None:
    out = render_prior_work_supplement_table(
        (_baseline_report(label="baseline/mock_shop", surface=_surface()),),
    )
    header = out.splitlines()[0]
    assert "Environment" in header
    assert "Coverage core (A)" in header
    assert "Coverage modern (A)" in header
    assert "Coverage weighted (A)" in header
    assert "Distinct templates (B)" in header
    assert "Routes crawled (B)" in header
    assert "Interactables p95 (B)" in header
    assert "Forms total (B)" in header


def test_separator_is_markdown_alignment_row() -> None:
    out = render_prior_work_supplement_table(
        (_baseline_report(label="baseline/mock_shop", surface=_surface()),),
    )
    separator = out.splitlines()[1]
    # First column is unaligned (label); seven numeric columns are right-aligned.
    assert separator == "|---|---:|---:|---:|---:|---:|---:|---:|"


def test_table_ends_with_trailing_newline() -> None:
    out = render_prior_work_supplement_table(
        (_baseline_report(label="baseline/mock_shop", surface=_surface()),),
    )
    assert out.endswith("\n")


# --------------------------------------------------------------------------- #
# Per-row rendering.
# --------------------------------------------------------------------------- #


def test_one_row_per_baseline_report() -> None:
    reports = (
        _baseline_report(label="baseline/mock_shop", surface=_surface()),
        _baseline_report(label="baseline/webshop", surface=_surface()),
        _baseline_report(label="baseline/webarena_shopping", surface=_surface()),
    )
    out = render_prior_work_supplement_table(reports)
    body = out.splitlines()[2:]  # drop header + separator.
    assert len(body) == len(reports)


def test_rows_carry_three_axis_a_and_four_axis_b_cells() -> None:
    out = render_prior_work_supplement_table(
        (
            _baseline_report(
                label="baseline/mock_shop",
                coverage_core=0.4,
                coverage_modern=0.2,
                coverage_weighted=0.3,
                surface=_surface(
                    distinct_templates=3,
                    routes_crawled=12,
                    interactables_per_template_p95=40.5,
                    forms_total=2,
                ),
            ),
        ),
    )
    row = out.splitlines()[2]
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells == [
        "baseline/mock_shop",
        "0.400",
        "0.200",
        "0.300",
        "3",
        "12",
        "40.5",
        "2",
    ]


def test_missing_axis_b_renders_as_em_dash() -> None:
    """Axis-A-only baseline runs leave every axis-B cell as the em-dash."""
    out = render_prior_work_supplement_table(
        (_baseline_report(label="baseline/axis_a_only", surface=None),),
    )
    row = out.splitlines()[2]
    cells = [c.strip() for c in row.strip("|").split("|")]
    # 1 label + 3 axis-A coverage cells + 4 axis-B em-dashes.
    assert cells[0] == "baseline/axis_a_only"
    assert cells[4:] == ["—", "—", "—", "—"]
    # Sanity: the placeholder must not be the string "None" or "0".
    assert "None" not in row


# --------------------------------------------------------------------------- #
# Determinism.
# --------------------------------------------------------------------------- #


def test_rows_sorted_by_label_for_byte_stable_output() -> None:
    """Input order must not affect the rendered table (acceptance check)."""
    forward = (
        _baseline_report(label="baseline/a", surface=_surface()),
        _baseline_report(label="baseline/b", surface=_surface()),
        _baseline_report(label="baseline/c", surface=_surface()),
    )
    reversed_inputs = tuple(reversed(forward))
    assert render_prior_work_supplement_table(forward) == render_prior_work_supplement_table(
        reversed_inputs
    )


def test_rows_appear_in_label_sorted_order() -> None:
    out = render_prior_work_supplement_table(
        (
            _baseline_report(label="baseline/webshop", surface=_surface()),
            _baseline_report(label="baseline/mock_shop", surface=_surface()),
            _baseline_report(label="baseline/webarena_shopping", surface=_surface()),
        ),
    )
    body = out.splitlines()[2:]
    assert "| baseline/mock_shop " in body[0]
    assert "| baseline/webarena_shopping " in body[1]
    assert "| baseline/webshop " in body[2]


# --------------------------------------------------------------------------- #
# Empty input.
# --------------------------------------------------------------------------- #


def test_empty_input_still_produces_header_and_separator() -> None:
    out = render_prior_work_supplement_table(())
    lines = out.rstrip("\n").splitlines()
    assert len(lines) == 2  # noqa: PLR2004 — header + separator only.
    assert "Environment" in lines[0]
    assert lines[1] == "|---|---:|---:|---:|---:|---:|---:|---:|"
