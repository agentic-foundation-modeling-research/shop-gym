"""Tests for `shop_probe.report_writer.supplement` (T7.5 — web_probe_patch.md).

Covers:

* The header columns and separator alignment.
* One row per :class:`ProbeReport`, sorted by ``target.name`` so the
  rendered table is byte-stable across runs.
* Em-dash for axis-B columns when the report carries no surface metrics.
"""

from __future__ import annotations

from datetime import UTC, datetime

from shop_probe.report import BrowserMeta, ProbeReport
from shop_probe.report_writer.supplement import render_prior_work_supplement_table
from shop_probe.surface.metrics import SurfaceMetrics
from shop_probe.targets import Target

_TIMESTAMP = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
_RUBRIC_HASH = "a" * 64


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11",
        playwright_version="1.48",
        chromium_version="129",
        user_agent="ShopProbe/0.1",
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
    name: str,
    coverage_core: float = 0.4,
    coverage_modern: float = 0.2,
    coverage_weighted: float = 0.3,
    surface: SurfaceMetrics | None = None,
) -> ProbeReport:
    target = Target(name=name, base_url="http://localhost:4001", label="real")
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        categories=(),
        coverage_core=coverage_core,
        coverage_modern=coverage_modern,
        coverage_advanced=0.0,
        coverage_weighted=coverage_weighted,
        surface=surface,
        rerun_index=1,
    )


def test_header_names_every_emitted_column() -> None:
    out = render_prior_work_supplement_table(
        (_baseline_report(name="mock_shop", surface=_surface()),),
    )
    header = out.splitlines()[0]
    for col in (
        "Environment",
        "Coverage core (A)",
        "Coverage modern (A)",
        "Coverage weighted (A)",
        "Distinct templates (B)",
        "Routes crawled (B)",
        "Interactables p95 (B)",
        "Forms total (B)",
    ):
        assert col in header


def test_renders_one_row_per_report() -> None:
    out = render_prior_work_supplement_table(
        (
            _baseline_report(name="mock_shop", surface=_surface()),
            _baseline_report(name="webshop", surface=_surface()),
            _baseline_report(name="webarena_shopping", surface=_surface()),
        )
    )
    body = out.splitlines()[2:]
    assert len(body) == 3  # noqa: PLR2004


def test_rows_sorted_by_target_name() -> None:
    out = render_prior_work_supplement_table(
        (
            _baseline_report(name="webshop", surface=_surface()),
            _baseline_report(name="mock_shop", surface=_surface()),
            _baseline_report(name="webarena_shopping", surface=_surface()),
        )
    )
    body = out.splitlines()[2:]
    # Sorted alphabetically by target.name.
    assert "mock_shop" in body[0]
    assert "webarena_shopping" in body[1]
    assert "webshop" in body[2]


def test_axis_b_columns_em_dash_when_surface_missing() -> None:
    out = render_prior_work_supplement_table(
        (_baseline_report(name="axis_a_only", surface=None),),
    )
    body_row = out.splitlines()[2]
    # Four axis-B columns rendered as em-dash.
    assert body_row.count("—") == 4  # noqa: PLR2004


def test_render_is_byte_stable() -> None:
    rows = (
        _baseline_report(name="b", surface=_surface()),
        _baseline_report(name="a", surface=_surface()),
    )
    assert render_prior_work_supplement_table(rows) == render_prior_work_supplement_table(rows)


def test_renders_empty_input_with_just_header() -> None:
    out = render_prior_work_supplement_table(())
    lines = out.splitlines()
    assert len(lines) == 2  # header + separator  # noqa: PLR2004
    assert lines[0].startswith("|")
    assert lines[1].startswith("|---")
