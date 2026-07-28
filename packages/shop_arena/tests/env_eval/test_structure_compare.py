"""URL-cohort structural-comparison orchestration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from shop_arena.env_eval import structure as structure_mod
from shop_arena.env_eval.config import EvalConfig, EvalResult
from shop_arena.env_eval.structure import compare as compare_mod
from shop_arena.env_eval.structure.compare import CompareConfig, compare_urls
from shop_arena.env_eval.structure.schema import (
    PageStructure,
    SnapshotShop,
    StructureSnapshot,
    VarianceReport,
)


def _snapshot(url: str) -> StructureSnapshot:
    """Return a minimal identical-structure sample for orchestration tests."""
    return StructureSnapshot(
        shop=SnapshotShop(url=url, eval_version="test"),
        pages=(
            PageStructure(
                page_type="homepage",
                canonical_id="/",
                element_type_histogram={"main": 1},
                maximum_depth=1,
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
        return _snapshot(
            ("https://a.example", "https://b.example", "https://c.example")[index],
        )

    monkeypatch.setattr(compare_mod, "evaluate", _fake_evaluate)
    monkeypatch.setattr(compare_mod, "extract_snapshot", _fake_extract)
    out_dir = tmp_path / "comparison"

    result = compare_urls(
        CompareConfig(
            urls=("https://a.example", "https://b.example", "https://c.example"),
            out_dir=out_dir,
            max_hops=2,
        ),
    )

    assert len(captured) == 3
    assert all(config.no_rubric for config in captured)
    assert all(config.max_hops == 2 for config in captured)
    assert captured[0].out_dir == out_dir / "runs" / "000-a.example"
    assert captured[1].out_dir == out_dir / "runs" / "001-b.example"
    assert captured[2].out_dir == out_dir / "runs" / "002-c.example"
    assert result.report_path == out_dir / "variance.json"
    report = VarianceReport.model_validate_json(result.report_path.read_text(encoding="utf-8"))
    assert report.version == "0.5"
    assert report.sample_count == 3
    assert report.cohort_mean.pages[0].sample_count == 3
    assert len(report.distances) == 3
    assert report.summary.element_type_distribution.mean == 0.0
    assert report.summary.maximum_depth.mean == 0.0
    assert report.visual_judges == ()
    assert report.samples[0].structure == "runs/000-a.example/structure.json"
    assert (out_dir / report.samples[0].structure).is_file()


def test_compare_config_requires_two_urls() -> None:
    """A single hosted shop cannot define output-to-output variance."""
    with pytest.raises(ValueError, match="at least 2 items"):
        CompareConfig(urls=("https://only.example",))


def test_compare_config_requires_unique_non_empty_visual_models() -> None:
    """Model artifact identities are unambiguous within one comparison."""
    with pytest.raises(ValueError, match="must be unique"):
        CompareConfig(
            urls=("https://a.example", "https://b.example"),
            visual_judge_models=("gpt-5", "gpt-5"),
        )
    with pytest.raises(ValueError, match="must be non-empty"):
        CompareConfig(
            urls=("https://a.example", "https://b.example"),
            visual_judge_models=(" ",),
        )


def test_structure_public_surface_exports_compare() -> None:
    """The package exposes the URL-cohort library entrypoint."""
    assert structure_mod.compare_urls is compare_urls
