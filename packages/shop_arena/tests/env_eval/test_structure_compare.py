"""URL-cohort structural-comparison orchestration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from shop_arena.env_eval import structure as structure_mod
from shop_arena.env_eval.config import EvalConfig, EvalResult
from shop_arena.env_eval.structure import compare as compare_mod
from shop_arena.env_eval.structure.compare import CompareConfig, compare_urls
from shop_arena.env_eval.structure.schema import (
    GraphStructure,
    PageStructure,
    SnapshotShop,
    StructureSnapshot,
    VarianceReport,
)


def _snapshot(url: str) -> StructureSnapshot:
    """Return a minimal identical-structure sample for orchestration tests."""
    return StructureSnapshot(
        shop=SnapshotShop(url=url, eval_version="test"),
        graph=GraphStructure(
            url_nodes=("/",),
            url_edges=(),
        ),
        pages=(
            PageStructure(
                page_type="homepage",
                canonical_id="/",
                role_histogram={"main": 1},
                semantic_node_count=1,
                interactive_count=0,
                semantic_max_depth=1,
            ),
        ),
    )


def test_compare_urls_evaluates_each_url_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Every URL gets an isolated resumable run plus structure.json."""
    captured: list[EvalConfig] = []

    def _fake_evaluate(config: EvalConfig) -> EvalResult:
        captured.append(config)
        assert config.out_dir is not None
        config.out_dir.mkdir(parents=True)
        metrics_path = config.out_dir / "metrics.json"
        metrics_path.write_text("{}", encoding="utf-8")
        return EvalResult(run_dir=config.out_dir, metrics_path=metrics_path)

    def _fake_extract(run_dir: Path | str) -> StructureSnapshot:
        index = int(Path(run_dir).name.split("-", 1)[0])
        return _snapshot(("https://a.example", "https://b.example")[index])

    monkeypatch.setattr(compare_mod, "evaluate", _fake_evaluate)
    monkeypatch.setattr(compare_mod, "extract_snapshot", _fake_extract)
    out_dir = tmp_path / "comparison"

    result = compare_urls(
        CompareConfig(
            urls=("https://a.example", "https://b.example"),
            out_dir=out_dir,
            max_hops=2,
        ),
    )

    assert len(captured) == 2
    assert all(config.no_rubric for config in captured)
    assert all(config.max_hops == 2 for config in captured)
    assert captured[0].out_dir == out_dir / "runs" / "000-a.example"
    assert captured[1].out_dir == out_dir / "runs" / "001-b.example"
    assert result.report_path == out_dir / "variance.json"
    report = VarianceReport.model_validate_json(result.report_path.read_text(encoding="utf-8"))
    assert report.sample_count == 2
    assert report.pair_count == 1
    assert report.summary.navigation.mean == 0.0
    assert report.summary.role_profile.score.mean == 0.0
    assert report.samples[0].structure == "runs/000-a.example/structure.json"
    assert (out_dir / report.samples[0].structure).is_file()


def test_compare_config_requires_two_urls() -> None:
    """A single hosted shop cannot define output-to-output variance."""
    with pytest.raises(ValueError, match="at least 2 items"):
        CompareConfig(urls=("https://only.example",))


def test_structure_public_surface_exports_compare() -> None:
    """The package exposes the URL-cohort library entrypoint."""
    assert structure_mod.compare_urls is compare_urls
