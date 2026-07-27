"""URL-cohort orchestration for website-structure variance measurement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from shop_arena.env_eval.config import (
    DEFAULT_MAX_HOPS,
    DEFAULT_VIEWPORT,
    EvalConfig,
)
from shop_arena.env_eval.pipeline import RUN_ID_TIMESTAMP_FORMAT, evaluate
from shop_arena.env_eval.structure.distance import pairwise_distances, summarize_distances
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

DEFAULT_COMPARISON_ROOT: Final[Path] = Path("outputs/shop_env_evals/comparisons")


class CompareConfig(BaseModel):
    """Configuration for evaluating and comparing a cohort of shop URLs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    urls: tuple[str, ...] = Field(min_length=2)
    out_dir: Path | None = None
    viewport: tuple[int, int] = DEFAULT_VIEWPORT
    max_hops: int = Field(default=DEFAULT_MAX_HOPS, ge=0)
    rediscover: bool = False


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


def compare_urls(config: CompareConfig) -> CompareResult:
    """Evaluate hosted shop URLs and write their structural-variance report.

    Completed child EnvEval runs are retained if a later URL fails. The report
    is written only after every sample has a valid structural snapshot.

    Args:
        config: Shared evaluation settings and at least two shop URLs.

    Returns:
        Comparison directory and published report path.
    """
    comparison_dir = resolve_comparison_dir(config)
    runs_dir = comparison_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    snapshots: list[StructureSnapshot] = []
    samples: list[SampleReference] = []
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
        samples.append(
            SampleReference(
                index=index,
                url=url,
                metrics=_relative_path(result.metrics_path, comparison_dir),
                structure=_relative_path(snapshot_path, comparison_dir),
            ),
        )

    pairwise = pairwise_distances(snapshots)
    report = VarianceReport(
        sample_count=len(samples),
        pair_count=len(pairwise),
        samples=tuple(samples),
        pairwise=pairwise,
        summary=summarize_distances(pairwise),
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
