"""Tests for ``shop-probe eval`` (end-to-end pipeline driver).

The probe + aggregate stages are stubbed so the test runs without launching
Playwright; the test asserts ``eval`` orchestrates them in the right order
and then renders the bench-level figures via the real ``_cmd_report``
handler.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shop_probe import cli
from shop_probe.cli import EXIT_OK, EXIT_USAGE, main
from shop_probe.report import BrowserMeta, CategoryScore, ProbeReport
from shop_probe.surface import SurfaceMetrics
from shop_probe.targets import Target, TargetLabel

_CATEGORY_NAMES: tuple[str, ...] = ("cart", "product", "site_shell")
_TIMESTAMP: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _surface() -> SurfaceMetrics:
    return SurfaceMetrics.model_validate(
        {
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
    )


def _stub_report(name: str, label: TargetLabel) -> ProbeReport:
    runtime = BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1",
        viewport=(1280, 800),
        headless=True,
    )
    cov = 0.7
    categories = tuple(
        CategoryScore(category=c, weight_passed=cov * 10.0, weight_total=10.0, coverage=cov)
        for c in _CATEGORY_NAMES
    )
    return ProbeReport(
        target=Target(name=name, base_url="http://localhost:4000", label=label),
        rubric_version="v1",
        rubric_hash="a" * 64,
        runner_version="0.0.0",
        runtime=runtime,
        timestamp=_TIMESTAMP,
        categories=categories,
        coverage_core=cov,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=cov,
        surface=_surface(),
        rerun_index=1,
    )


def _write_benchmark_yaml(path: Path) -> None:
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


def _stub_cmd_run_factory() -> object:
    """Return a callable that records args and writes a synthetic ProbeReport."""
    calls: list[argparse.Namespace] = []

    def stub(args: argparse.Namespace) -> int:
        calls.append(args)
        report = _stub_report(args.name, args.label)
        out_path = (
            Path(args.out) / "reports" / f"{args.label}__{args.name}__rerun{args.rerun_index}.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return EXIT_OK

    stub.calls = calls  # type: ignore[attr-defined]
    return stub


def _eval_args(benchmark_yaml: Path, out_root: Path, *, reruns: int = 1) -> list[str]:
    return [
        "eval",
        "--benchmark",
        str(benchmark_yaml),
        "--out",
        str(out_root),
        "--reruns",
        str(reruns),
    ]


def test_cli_eval_invokes_run_per_target_then_renders_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "out"
    benchmark_yaml = tmp_path / "benchmark.yaml"
    _write_benchmark_yaml(benchmark_yaml)

    stub_run = _stub_cmd_run_factory()
    monkeypatch.setattr(cli, "_cmd_run", stub_run)

    rc = main(_eval_args(benchmark_yaml, out_root))
    assert rc == EXIT_OK

    # Bench has 2 sandboxes + 2 reals; reruns=1 → 4 probe calls, no aggregate.
    calls = list(stub_run.calls)  # type: ignore[attr-defined]
    seen = [(vars(c)["label"], vars(c)["name"], vars(c)["rerun_index"]) for c in calls]
    assert seen == [
        ("sandbox", "shop_alpha", 1),
        ("sandbox", "shop_beta", 1),
        ("real", "real_a", 1),
        ("real", "real_b", 1),
    ]

    figures_dir = out_root / "figures"
    assert (figures_dir / "group_comparison.md").is_file()
    assert (figures_dir / "per_shop_table.md").is_file()
    assert (figures_dir / "radar.svg").is_file()
    assert (figures_dir / "surface.svg").is_file()


def test_cli_eval_runs_aggregate_when_reruns_at_least_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_root = tmp_path / "out"
    benchmark_yaml = tmp_path / "benchmark.yaml"
    _write_benchmark_yaml(benchmark_yaml)

    stub_run = _stub_cmd_run_factory()
    monkeypatch.setattr(cli, "_cmd_run", stub_run)

    aggregate_calls: list[argparse.Namespace] = []

    def stub_aggregate(args: argparse.Namespace) -> int:
        aggregate_calls.append(args)
        # Pick rerun 1 as canonical; eval expects '<label>__<name>.json' to exist
        # after aggregate so _cmd_report can find it.
        first_run: Path = args.runs[0]
        consolidated = first_run.with_name(first_run.name.split("__rerun")[0] + ".json")
        consolidated.write_text(first_run.read_text(encoding="utf-8"), encoding="utf-8")
        return EXIT_OK

    monkeypatch.setattr(cli, "_cmd_aggregate_reruns", stub_aggregate)

    rc = main(_eval_args(benchmark_yaml, out_root, reruns=2))
    assert rc == EXIT_OK

    # 4 targets x 2 reruns = 8 probe calls, plus 4 aggregate calls.
    assert len(stub_run.calls) == 8  # type: ignore[attr-defined]  # noqa: PLR2004
    assert len(aggregate_calls) == 4  # noqa: PLR2004
    # Every aggregate call passes both rerun paths in order.
    for call in aggregate_calls:
        assert len(call.runs) == 2  # noqa: PLR2004
        assert "__rerun1.json" in call.runs[0].name
        assert "__rerun2.json" in call.runs[1].name


def test_cli_eval_aborts_on_probe_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_root = tmp_path / "out"
    benchmark_yaml = tmp_path / "benchmark.yaml"
    _write_benchmark_yaml(benchmark_yaml)

    def stub_run(args: argparse.Namespace) -> int:
        del args
        return EXIT_USAGE  # simulate an unrecoverable probe failure

    monkeypatch.setattr(cli, "_cmd_run", stub_run)

    rc = main(_eval_args(benchmark_yaml, out_root))
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "aborted on target='shop_alpha'" in captured.err
    # No figures should have been written when probing aborts.
    assert not (out_root / "figures").exists()


def test_cli_eval_rejects_non_positive_reruns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    benchmark_yaml = tmp_path / "benchmark.yaml"
    _write_benchmark_yaml(benchmark_yaml)

    rc = main(_eval_args(benchmark_yaml, tmp_path / "out", reruns=0))
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "must be >= 1" in captured.err


def test_cli_eval_missing_benchmark_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(_eval_args(tmp_path / "nope.yaml", tmp_path / "out"))
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "benchmark not found" in captured.err
