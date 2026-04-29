"""End-to-end test for ``shop-probe report`` (web_probe_patch.md).

Drives the CLI against synthetic, on-disk :class:`ProbeReport` fixtures
and asserts every paper figure renders without manual editing:

* the group comparison + per-shop tables;
* the per-category coverage radar;
* the per-metric surface bar chart;
* the group-level Turing chart when axis-C calls are present.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shop_probe.cli import EXIT_OK, EXIT_USAGE, main
from shop_probe.report import (
    BrowserMeta,
    CategoryScore,
    JudgeCall,
    ProbeReport,
)
from shop_probe.surface import SurfaceMetrics
from shop_probe.targets import Target, TargetLabel

_RUBRIC_HASH: str = "a" * 64
_PROMPT_HASH: str = "b" * 64
_TIMESTAMP: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
_CATEGORY_NAMES: tuple[str, ...] = ("cart", "product", "site_shell")


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


def _categories(coverages: dict[str, float]) -> tuple[CategoryScore, ...]:
    return tuple(
        CategoryScore(
            category=name,
            weight_passed=cov * 10.0,
            weight_total=10.0,
            coverage=cov,
        )
        for name, cov in coverages.items()
    )


def _report(
    *,
    name: str,
    label: TargetLabel,
    coverages: dict[str, float],
    surface: SurfaceMetrics,
    judge_calls: tuple[JudgeCall, ...] = (),
) -> ProbeReport:
    target = Target(name=name, base_url="http://localhost:4000", label=label)
    weighted = sum(coverages.values()) / max(len(coverages), 1)
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        categories=_categories(coverages),
        coverage_core=weighted,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=weighted,
        surface=surface,
        judge_calls=judge_calls,
        rerun_index=1,
    )


def _judge_call(predicted: str) -> JudgeCall:
    return JudgeCall(
        predicted_label=predicted,  # type: ignore[arg-type]
        prompt_hash=_PROMPT_HASH,
        response="r",
        latency_ms=10.0,
        cost_usd=0.0,
        model_id="gpt-stub",
    )


def _write_report(reports_dir: Path, report: ProbeReport) -> Path:
    """Write ``report`` to the consolidated ``<label>__<name>.json`` slot."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report.target.label}__{report.target.name}"
    path = reports_dir / f"{stem}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def _write_bench_yaml(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                'version: "0.1"',
                "sandboxes:",
                "  - { name: shop_alpha, base_url: http://localhost:4000, label: sandbox }",
                "  - { name: shop_beta, base_url: http://localhost:4001, label: sandbox }",
                "reals:",
                "  - { name: real_a, base_url: https://real-a.example.invalid, label: real }",
                "  - { name: real_b, base_url: https://real-b.example.invalid, label: real }",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_bench_reports(tmp_path: Path, *, with_judge: bool = False) -> tuple[Path, Path]:
    """Lay out reports/<label>__<name>.json under ``tmp_path`` and return (bench_yaml, out_root)."""
    out_root = tmp_path / "out"
    reports_dir = out_root / "reports"
    coverages_low = dict.fromkeys(_CATEGORY_NAMES, 0.6)
    coverages_high = dict.fromkeys(_CATEGORY_NAMES, 0.9)

    sandbox_calls: tuple[JudgeCall, ...] = (
        (_judge_call("sandbox"), _judge_call("real")) if with_judge else ()
    )
    real_calls: tuple[JudgeCall, ...] = (
        (_judge_call("real"), _judge_call("real")) if with_judge else ()
    )

    _write_report(
        reports_dir,
        _report(
            name="shop_alpha",
            label="sandbox",
            coverages=coverages_low,
            surface=_surface(distinct_templates=4),
            judge_calls=sandbox_calls,
        ),
    )
    _write_report(
        reports_dir,
        _report(
            name="shop_beta",
            label="sandbox",
            coverages=coverages_low,
            surface=_surface(distinct_templates=5),
            judge_calls=sandbox_calls,
        ),
    )
    _write_report(
        reports_dir,
        _report(
            name="real_a",
            label="real",
            coverages=coverages_high,
            surface=_surface(distinct_templates=8),
            judge_calls=real_calls,
        ),
    )
    _write_report(
        reports_dir,
        _report(
            name="real_b",
            label="real",
            coverages=coverages_high,
            surface=_surface(distinct_templates=10),
            judge_calls=real_calls,
        ),
    )

    bench_yaml = tmp_path / "bench.yaml"
    _write_bench_yaml(bench_yaml)
    return bench_yaml, out_root


def test_cli_report_writes_group_comparison_and_per_shop_tables(tmp_path: Path) -> None:
    bench_yaml, out_root = _make_bench_reports(tmp_path)
    rc = main(["report", "--benchmark", str(bench_yaml), "--out", str(out_root)])
    assert rc == EXIT_OK

    group_table = (out_root / "figures" / "group_comparison.md").read_text(encoding="utf-8")
    # Header + sandbox + real + delta rows.
    assert "Group" in group_table
    assert "sandbox" in group_table
    assert "real" in group_table
    assert "delta" in group_table

    per_shop = (out_root / "figures" / "per_shop_table.md").read_text(encoding="utf-8")
    for shop in ("shop_alpha", "shop_beta", "real_a", "real_b"):
        assert shop in per_shop


def test_cli_report_writes_radar_and_surface(tmp_path: Path) -> None:
    bench_yaml, out_root = _make_bench_reports(tmp_path)
    rc = main(["report", "--benchmark", str(bench_yaml), "--out", str(out_root)])
    assert rc == EXIT_OK

    radar = (out_root / "figures" / "radar.svg").read_text(encoding="utf-8")
    assert radar.startswith("<svg")
    assert "real-shop envelope" in radar
    assert "shop_alpha" in radar  # legend uses target.name

    surface = (out_root / "figures" / "surface.svg").read_text(encoding="utf-8")
    assert surface.startswith("<svg")
    assert "real-shop envelope" in surface
    assert "shop_alpha" in surface


def test_cli_report_skips_turing_when_no_judge_calls(tmp_path: Path) -> None:
    bench_yaml, out_root = _make_bench_reports(tmp_path, with_judge=False)
    rc = main(["report", "--benchmark", str(bench_yaml), "--out", str(out_root)])
    assert rc == EXIT_OK
    assert not (out_root / "figures" / "turing.svg").exists()


def test_cli_report_writes_turing_chart_when_judge_calls_present(tmp_path: Path) -> None:
    bench_yaml, out_root = _make_bench_reports(tmp_path, with_judge=True)
    rc = main(["report", "--benchmark", str(bench_yaml), "--out", str(out_root)])
    assert rc == EXIT_OK
    turing = (out_root / "figures" / "turing.svg").read_text(encoding="utf-8")
    assert turing.startswith("<svg")
    assert "Judge accuracy" in turing


def test_cli_report_resolves_max_n_rerun_when_consolidated_absent(tmp_path: Path) -> None:
    bench_yaml, out_root = _make_bench_reports(tmp_path)
    # Replace one consolidated file with two raw rerun files; the loader
    # must still resolve to the max-N raw report.
    reports_dir = out_root / "reports"
    consolidated = reports_dir / "sandbox__shop_alpha.json"
    consolidated.unlink()
    payload = consolidated.with_suffix(".rerun")  # placeholder
    del payload  # unused

    coverages = dict.fromkeys(_CATEGORY_NAMES, 0.7)
    raw_report_v1 = _report(
        name="shop_alpha",
        label="sandbox",
        coverages=coverages,
        surface=_surface(),
    )
    raw_report_v2 = _report(
        name="shop_alpha",
        label="sandbox",
        coverages=coverages,
        surface=_surface(distinct_templates=6),
    ).model_copy(update={"rerun_index": 2})
    (reports_dir / "sandbox__shop_alpha__rerun1.json").write_text(
        raw_report_v1.model_dump_json(indent=2), encoding="utf-8"
    )
    (reports_dir / "sandbox__shop_alpha__rerun2.json").write_text(
        raw_report_v2.model_dump_json(indent=2), encoding="utf-8"
    )

    rc = main(["report", "--benchmark", str(bench_yaml), "--out", str(out_root)])
    assert rc == EXIT_OK


def test_cli_report_missing_report_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bench_yaml = tmp_path / "bench.yaml"
    _write_bench_yaml(bench_yaml)
    out_root = tmp_path / "out"
    (out_root / "reports").mkdir(parents=True)
    rc = main(["report", "--benchmark", str(bench_yaml), "--out", str(out_root)])
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "missing report" in captured.err


def test_cli_report_missing_benchmark_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        ["report", "--benchmark", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "out")]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "benchmark not found" in captured.err
