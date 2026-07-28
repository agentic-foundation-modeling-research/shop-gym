"""Closed schemas for URL-observable website-structure comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

SNAPSHOT_FILENAME = "structure.json"
SNAPSHOT_VERSION: Literal["0.4"] = "0.4"
REPORT_FILENAME = "variance.json"
REPORT_VERSION: Literal["0.5"] = "0.5"

type RepresentativePageType = Literal[
    "homepage",
    "collection",
    "product",
    "policy",
    "cart",
    "search",
]

REPRESENTATIVE_PAGE_TYPES: Final[tuple[RepresentativePageType, ...]] = (
    "homepage",
    "collection",
    "product",
    "policy",
    "cart",
    "search",
)


class _Closed(BaseModel):
    """Frozen base model that rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SnapshotShop(_Closed):
    """Identity of the hosted shop measured by one structural snapshot."""

    url: str = Field(min_length=1)
    eval_version: str = Field(min_length=1)


class PageStructure(_Closed):
    """Order-independent AXTree structure of one representative page."""

    page_type: RepresentativePageType
    canonical_id: str = Field(min_length=1)
    element_type_histogram: dict[str, int]
    maximum_depth: int = Field(ge=0)


class StructureSnapshot(_Closed):
    """Content-independent structural snapshot derived from an EnvEval run."""

    version: Literal["0.4"] = SNAPSHOT_VERSION
    shop: SnapshotShop
    pages: tuple[PageStructure, ...]


class MeanPageProfile(_Closed):
    """Cohort mean for one representative page type."""

    page_type: RepresentativePageType
    sample_count: int = Field(ge=1)
    element_type_distribution: dict[str, float]
    maximum_depth: float = Field(ge=0.0)


class CohortMean(_Closed):
    """Mean AXTree profile against which each sample is compared."""

    pages: tuple[MeanPageProfile, ...]


class ProfileDistance(_Closed):
    """Distance to the cohort mean for the two retained AXTree metrics."""

    element_type_distribution: float = Field(ge=0.0, le=1.0)
    maximum_depth: float = Field(ge=0.0, le=1.0)


class PageDistance(_Closed):
    """One representative page's distance from its cohort mean."""

    page_type: RepresentativePageType
    canonical_id: str = Field(min_length=1)
    profile: ProfileDistance


class SampleReference(_Closed):
    """One cohort sample and its comparison-relative artifact paths."""

    index: int = Field(ge=0)
    url: str = Field(min_length=1)
    metrics: str = Field(min_length=1)
    structure: str = Field(min_length=1)


class SampleDistance(_Closed):
    """One shop's aggregate and per-page distances from the cohort mean."""

    sample: int = Field(ge=0)
    page_count: int = Field(ge=1)
    pages: tuple[PageDistance, ...]
    profile: ProfileDistance


class DistanceSummary(_Closed):
    """Distribution summary for one distance component across shops."""

    count: int = Field(ge=1)
    mean: float = Field(ge=0.0, le=1.0)
    median: float = Field(ge=0.0, le=1.0)
    p90: float = Field(ge=0.0, le=1.0)
    minimum: float = Field(ge=0.0, le=1.0)
    maximum: float = Field(ge=0.0, le=1.0)


class ProfileSummary(_Closed):
    """Cohort summaries for the two retained profile components."""

    element_type_distribution: DistanceSummary
    maximum_depth: DistanceSummary


class VisualShopDistance(_Closed):
    """One judge's visual distance for one shop and representative page."""

    sample: int = Field(ge=0)
    screenshot: str = Field(min_length=1)
    distance: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)


class VisualPageJudgment(_Closed):
    """Auditable result of one model call for one representative page type."""

    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0.0)
    page_type: RepresentativePageType
    sample_count: int = Field(ge=2)
    artifact: str = Field(min_length=1)
    cohort_distance: float | None = Field(default=None, ge=0.0, le=1.0)
    shops: tuple[VisualShopDistance, ...] = ()
    rationale: str = ""
    raw_response: str
    parse_errors: tuple[str, ...] = ()


class VisualSampleSummary(_Closed):
    """One shop's mean visual distance across successfully judged pages."""

    sample: int = Field(ge=0)
    page_count: int = Field(ge=1)
    distance: float = Field(ge=0.0, le=1.0)


class VisualModelResult(_Closed):
    """Model-specific visual comparison, kept separate from other judges."""

    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0.0)
    artifact: str = Field(min_length=1)
    page_count: int = Field(ge=0)
    successful_page_count: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    visual_distance: float | None = Field(default=None, ge=0.0, le=1.0)
    shops: tuple[VisualSampleSummary, ...] = ()
    pages: tuple[VisualPageJudgment, ...] = ()


class VarianceReport(_Closed):
    """Published mean-centered website-structure variance report."""

    version: Literal["0.5"] = REPORT_VERSION
    sample_count: int = Field(ge=2)
    samples: tuple[SampleReference, ...]
    cohort_mean: CohortMean
    distances: tuple[SampleDistance, ...]
    summary: ProfileSummary
    visual_judges: tuple[VisualModelResult, ...] = ()


def dump_snapshot(snapshot: StructureSnapshot, path: Path | str) -> Path:
    """Write a deterministic structural snapshot."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(snapshot.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_snapshot(path: Path | str) -> StructureSnapshot:
    """Load and validate a structural snapshot."""
    return StructureSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8"))


def dump_report(report: VarianceReport, path: Path | str) -> Path:
    """Write a deterministic structural-variance report."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "REPORT_FILENAME",
    "REPORT_VERSION",
    "REPRESENTATIVE_PAGE_TYPES",
    "SNAPSHOT_FILENAME",
    "SNAPSHOT_VERSION",
    "CohortMean",
    "DistanceSummary",
    "MeanPageProfile",
    "PageDistance",
    "PageStructure",
    "ProfileDistance",
    "ProfileSummary",
    "RepresentativePageType",
    "SampleDistance",
    "SampleReference",
    "SnapshotShop",
    "StructureSnapshot",
    "VarianceReport",
    "VisualModelResult",
    "VisualPageJudgment",
    "VisualSampleSummary",
    "VisualShopDistance",
    "dump_report",
    "dump_snapshot",
    "load_snapshot",
]
