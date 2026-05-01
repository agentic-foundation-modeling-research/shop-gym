"""Tests for ``shop-probe eval`` (the single user-facing subcommand).

Stubs the per-target probe runner so the test runs without launching
Playwright or hitting the Anthropic proxy. Asserts that ``eval``:

* writes one report per target into ``<out>/reports/``;
* skips a target when ``<out>/reports/<label>__<name>.json`` is present
  with a matching ``rubric_hash`` (cache hit);
* recomputes a target whose cached report has a stale ``rubric_hash``;
* recomputes everything when ``--force`` is passed;
* renders the two cohort tables under ``<out>/figures/``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from shop_probe import cli
from shop_probe.cli import EXIT_OK, EXIT_USAGE, main
from shop_probe.report import BrowserMeta, CategoryScore, ProbeReport, ProbeResult
from shop_probe.scale.metrics import ScaleMetrics
from shop_probe.targets import Target, TargetLabel

_TIMESTAMP = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _runtime() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1",
        viewport=(1280, 800),
        headless=True,
    )


def _stub_report(target: Target, *, rubric_hash: str) -> ProbeReport:
    cov = 0.7
    categories = (
        CategoryScore(category="product", weight_passed=cov * 10, weight_total=10, coverage=cov),
    )
    return ProbeReport(
        target=target,
        rubric_version="v3",
        rubric_hash=rubric_hash,
        runner_version="0.0.0",
        runtime=_runtime(),
        timestamp=_TIMESTAMP,
        categories=categories,
        coverage_core=cov,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=cov,
        scale=None,
    )


def _write_benchmark(path: Path) -> None:
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


def _stub_run_factory() -> tuple[list[Target], list[dict[str, Any]], Any]:
    """Patch ``cli._run`` to record targets and return synthetic reports.

    Returns three handles:
      * ``seen``       — targets actually dispatched to ``_run``.
      * ``cache_args`` — per-call dict capturing ``cached_results`` and
        ``cached_scale`` so tests can assert how the partial-cache
        plumbing handed state down to the runner.
      * ``stub``       — the stub itself (passed to ``monkeypatch``).
    """
    seen: list[Target] = []
    cache_args: list[dict[str, Any]] = []

    async def stub(
        *,
        target: Target,
        rubric: Any,
        evidence_root: Path,  # noqa: ARG001
        include_auth: bool,  # noqa: ARG001
        capture_judge_model: str,  # noqa: ARG001
        cached_results: dict[str, ProbeResult] | None = None,
        cached_scale: ScaleMetrics | None = None,
    ) -> ProbeReport:
        seen.append(target)
        cache_args.append(
            {"cached_results": cached_results, "cached_scale": cached_scale}
        )
        report = _stub_report(target, rubric_hash=rubric.content_hash)
        # Synthesize one ``passed=True`` ProbeResult per non-scale rubric
        # entry so the cache is fully populated — otherwise a partial-cache
        # follow-up run would treat every entry as "missing".
        results = tuple(
            ProbeResult(id=e.id, passed=True, duration_ms=0)
            for e in rubric.entries
            if e.type != "scale"
        )
        scale = ScaleMetrics(
            median_dom_kb_gz=None,
            interactables_per_page_median=None,
            form_fields_per_page_median=None,
            accessibility_nodes_per_page_median=None,
            catalog_products=None,
            catalog_collections=None,
        ) if any(e.type == "scale" for e in rubric.entries) else None
        return report.model_copy(update={"probe_results": results, "scale": scale})

    return seen, cache_args, stub


def _eval_args(benchmark: Path, out: Path, *extra: str) -> list[str]:
    return ["eval", "--benchmark", str(benchmark), "--out", str(out), *extra]


def test_cli_eval_runs_every_target_and_renders_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark = tmp_path / "benchmark.yaml"
    out = tmp_path / "out"
    _write_benchmark(benchmark)
    seen, _, stub = _stub_run_factory()
    monkeypatch.setattr(cli, "_run", stub)

    rc = main(_eval_args(benchmark, out))
    assert rc == EXIT_OK

    names = [(t.label, t.name) for t in seen]
    assert names == [
        ("sandbox", "shop_alpha"),
        ("sandbox", "shop_beta"),
        ("real", "real_a"),
        ("real", "real_b"),
    ]

    reports_dir = out / "reports"
    assert (reports_dir / "sandbox__shop_alpha.json").is_file()
    assert (reports_dir / "real__real_a.json").is_file()

    figures_dir = out / "figures"
    assert (figures_dir / "group_comparison.md").is_file()
    assert (figures_dir / "per_shop_table.md").is_file()


def test_cli_eval_cache_hit_skips_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark = tmp_path / "benchmark.yaml"
    out = tmp_path / "out"
    _write_benchmark(benchmark)
    seen, _, stub = _stub_run_factory()
    monkeypatch.setattr(cli, "_run", stub)

    # First run populates the cache.
    assert main(_eval_args(benchmark, out)) == EXIT_OK
    assert len(seen) == 4  # noqa: PLR2004
    seen.clear()

    # Second run with the same rubric should hit the cache for every target.
    assert main(_eval_args(benchmark, out)) == EXIT_OK
    assert seen == []


def test_cli_eval_force_bypasses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark = tmp_path / "benchmark.yaml"
    out = tmp_path / "out"
    _write_benchmark(benchmark)
    seen, _, stub = _stub_run_factory()
    monkeypatch.setattr(cli, "_run", stub)

    assert main(_eval_args(benchmark, out)) == EXIT_OK
    seen.clear()

    assert main(_eval_args(benchmark, out, "--force")) == EXIT_OK
    assert len(seen) == 4  # noqa: PLR2004


def test_cli_eval_recomputes_on_stale_rubric_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark = tmp_path / "benchmark.yaml"
    out = tmp_path / "out"
    _write_benchmark(benchmark)
    seen, _, stub = _stub_run_factory()
    monkeypatch.setattr(cli, "_run", stub)

    reports_dir = out / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    target = Target(name="shop_alpha", base_url="http://localhost:4000", label="sandbox")
    stale = _stub_report(target, rubric_hash="0" * 64)
    (reports_dir / "sandbox__shop_alpha.json").write_text(
        stale.model_dump_json(indent=2), encoding="utf-8"
    )

    assert main(_eval_args(benchmark, out)) == EXIT_OK
    # All four targets re-run because the cached report has a stale hash.
    assert any(t.name == "shop_alpha" for t in seen)


def test_cli_eval_appends_new_target_without_reprocessing_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark = tmp_path / "benchmark.yaml"
    out = tmp_path / "out"
    _write_benchmark(benchmark)
    seen, _, stub = _stub_run_factory()
    monkeypatch.setattr(cli, "_run", stub)

    assert main(_eval_args(benchmark, out)) == EXIT_OK
    seen.clear()

    # Add a new sandbox to the YAML and re-run.
    benchmark.write_text(
        "\n".join(
            [
                'version: "0.1"',
                "sandboxes:",
                "  - { name: shop_alpha, base_url: http://localhost:4000, label: sandbox }",
                "  - { name: shop_beta, base_url: http://localhost:4001, label: sandbox }",
                "  - { name: shop_gamma, base_url: http://localhost:4002, label: sandbox }",
                "reals:",
                "  - { name: real_a, base_url: https://real-a.example.invalid, label: real }",
                "  - { name: real_b, base_url: https://real-b.example.invalid, label: real }",
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert main(_eval_args(benchmark, out)) == EXIT_OK
    assert [t.name for t in seen] == ["shop_gamma"]


def test_cli_eval_partial_cache_passes_clean_results_and_reruns_unknowns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached report with a mix of clean + ``passed=None`` rows feeds
    the clean rows into ``_run`` and re-runs the rest."""
    benchmark = tmp_path / "benchmark.yaml"
    out = tmp_path / "out"
    _write_benchmark(benchmark)

    # Hand-build a cached report for one target with a clean row and a
    # ``passed=None`` row, sharing the live rubric's content hash so the
    # cache loader doesn't reject it as stale.
    from shop_probe.cli import _RUBRIC_PATH
    from shop_probe.rubric import load_rubric

    rubric_hash = load_rubric(_RUBRIC_PATH).content_hash
    target_alpha = Target(name="shop_alpha", base_url="http://localhost:4000", label="sandbox")
    cached_clean = ProbeResult(id="homepage.hero.present", passed=True, duration_ms=0)
    cached_unknown = ProbeResult(
        id="homepage.cta_to_collection", passed=None, duration_ms=0
    )
    cached = _stub_report(target_alpha, rubric_hash=rubric_hash).model_copy(
        update={"probe_results": (cached_clean, cached_unknown)}
    )
    reports_dir = out / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "sandbox__shop_alpha.json").write_text(
        cached.model_dump_json(indent=2), encoding="utf-8"
    )

    seen, cache_args, stub = _stub_run_factory()
    monkeypatch.setattr(cli, "_run", stub)

    assert main(_eval_args(benchmark, out)) == EXIT_OK

    # ``shop_alpha`` re-runs because at least one row was ``passed=None``.
    alpha_idx = next(i for i, t in enumerate(seen) if t.name == "shop_alpha")
    cached_results = cache_args[alpha_idx]["cached_results"]
    assert "homepage.hero.present" in cached_results
    assert "homepage.cta_to_collection" not in cached_results
    assert cached_results["homepage.hero.present"].passed is True


def test_cli_eval_missing_benchmark_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(_eval_args(tmp_path / "nope.yaml", tmp_path / "out"))
    assert rc == EXIT_USAGE
    assert "benchmark not found" in capsys.readouterr().err


def test_cli_eval_rejects_invalid_capture_judge_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    benchmark = tmp_path / "benchmark.yaml"
    _write_benchmark(benchmark)
    rc = main(
        _eval_args(
            benchmark,
            tmp_path / "out",
            "--capture-judge-model",
            "claude-haiku-4-5",  # missing provider prefix
        )
    )
    assert rc == EXIT_USAGE
    assert "anthropic:<id>" in capsys.readouterr().err
