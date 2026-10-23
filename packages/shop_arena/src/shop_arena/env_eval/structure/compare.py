"""URL-cohort orchestration for website-structure variance measurement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shop_arena.env_eval.config import (
    DEFAULT_MAX_HOPS,
    DEFAULT_VIEWPORT,
    EvalConfig,
)
from shop_arena.env_eval.pipeline import RUN_ID_TIMESTAMP_FORMAT, evaluate
from shop_arena.env_eval.structure.distance import (
    compute_cohort_mean,
    distances_from_mean,
    summarize_distances,
)
from shop_arena.env_eval.structure.schema import (
    REPORT_FILENAME,
    SNAPSHOT_FILENAME,
    SampleReference,
    StructureSnapshot,
    VarianceReport,
    dump_report,
    dump_snapshot,
)
from shop_arena.env_eval.structure.snapshot import extract_snapshot
from shop_arena.env_eval.structure.visual import (
    VisionClientBuilder,
    run_visual_judges,
)
from shop_arena.util._llm import build_default_client

DEFAULT_COMPARISON_ROOT: Final[Path] = Path("outputs/shop_env_evals/comparisons")


class CompareConfig(BaseModel):
    """Configuration for evaluating and comparing a cohort of shop URLs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    urls: tuple[str, ...] = Field(min_length=2)
    out_dir: Path | None = None
    viewport: tuple[int, int] = DEFAULT_VIEWPORT
    max_hops: int = Field(default=DEFAULT_MAX_HOPS, ge=0)
    rediscover: bool = False
    visual_judge_models: tuple[str, ...] = ()

    @field_validator("visual_judge_models")
    @classmethod
    def _validate_visual_judge_models(cls, models: tuple[str, ...]) -> tuple[str, ...]:
        """Require non-empty, unique model ids while preserving CLI order."""
        normalized = tuple(model.strip() for model in models)
        if any(not model for model in normalized):
            raise ValueError("visual judge model ids must be non-empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("visual judge model ids must be unique")
        return normalized


@dataclass(frozen=True, slots=True)
class CompareResult:
    """Filesystem result of one URL-cohort comparison."""

    comparison_dir: Path
    report_path: Path


def resolve_comparison_dir(
    config: CompareConfig,
    *,
    now: datetime | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Resolve the comparison directory without creating it."""
    if config.out_dir is not None:
        return config.out_dir
    timestamp = (now or datetime.now(UTC)).strftime(RUN_ID_TIMESTAMP_FORMAT)
    root = base_dir if base_dir is not None else DEFAULT_COMPARISON_ROOT
    return root / timestamp


def compare_urls(
    config: CompareConfig,
    *,
    visual_client_builder: VisionClientBuilder = build_default_client,
) -> CompareResult:
    """Evaluate hosted shop URLs and write their structural-variance report.

    Completed child EnvEval runs are retained if a later URL fails. The report
    is written only after every sample has a valid structural snapshot.

    Args:
        config: Shared evaluation settings and at least two shop URLs.
        visual_client_builder: Vision-client constructor used only when visual
            judge models are configured. Tests inject fakes through this seam.

    Returns:
        Comparison directory and published report path.
    """
    comparison_dir = resolve_comparison_dir(config)
    runs_dir = comparison_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    snapshots: list[StructureSnapshot] = []
    samples: list[SampleReference] = []
    run_dirs: list[Path] = []
    for index, url in enumerate(config.urls):
        run_dir = runs_dir / f"{index:03d}-{_url_folder_name(url)}"
        result = evaluate(
            EvalConfig(
                url=url,
                out_dir=run_dir,
                viewport=config.viewport,
                max_hops=config.max_hops,
                no_rubric=True,
                rediscover=config.rediscover,
            ),
        )
        snapshot = extract_snapshot(result.run_dir)
        snapshot_path = dump_snapshot(snapshot, result.run_dir / SNAPSHOT_FILENAME)
        snapshots.append(snapshot)
        run_dirs.append(result.run_dir)
        samples.append(
            SampleReference(
                index=index,
                url=url,
                metrics=_relative_path(result.metrics_path, comparison_dir),
                structure=_relative_path(snapshot_path, comparison_dir),
            ),
        )

    cohort_mean = compute_cohort_mean(snapshots)
    distances = distances_from_mean(snapshots, cohort_mean)
    visual_judges = (
        run_visual_judges(
            models=config.visual_judge_models,
            snapshots=snapshots,
            run_dirs=run_dirs,
            comparison_dir=comparison_dir,
            client_builder=visual_client_builder,
        )
        if config.visual_judge_models
        else ()
    )
    report = VarianceReport(
        sample_count=len(samples),
        samples=tuple(samples),
        cohort_mean=cohort_mean,
        distances=distances,
        summary=summarize_distances(distances),
        visual_judges=visual_judges,
    )
    report_path = dump_report(report, comparison_dir / REPORT_FILENAME)
    return CompareResult(comparison_dir=comparison_dir, report_path=report_path)


def _url_folder_name(url: str) -> str:
    """Return a portable, bounded folder segment for one URL."""
    host = (urlsplit(url).hostname or "shop").casefold()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", host).strip("-.")
    return (normalized or "shop")[:80]


def _relative_path(path: Path, root: Path) -> str:
    """Return a portable comparison-relative artifact path."""
    return path.relative_to(root).as_posix()


__all__ = [
    "DEFAULT_COMPARISON_ROOT",
    "CompareConfig",
    "CompareResult",
    "compare_urls",
    "resolve_comparison_dir",
]
