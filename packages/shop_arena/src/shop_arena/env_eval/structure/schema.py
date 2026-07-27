"""Closed schemas for URL-observable website-structure comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SNAPSHOT_FILENAME = "structure.json"
SNAPSHOT_VERSION: Literal["0.3"] = "0.3"
REPORT_FILENAME = "variance.json"
REPORT_VERSION: Literal["0.3"] = "0.3"

type RepresentativePageType = Literal[
    "homepage",
    "collection",
    "product",
    "policy",
    "cart",
    "search",
]


class _Closed(BaseModel):
    """Frozen base model that rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SnapshotShop(_Closed):
    """Identity of the hosted shop measured by one structural snapshot."""

    url: str = Field(min_length=1)
    eval_version: str = Field(min_length=1)


class StructureEdge(_Closed):
    """Content-independent directed edge in a structural graph."""

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    action: str = Field(min_length=1)


class GraphStructure(_Closed):
    """Canonical URL navigation topology for one shop."""

    url_nodes: tuple[str, ...]
    url_edges: tuple[StructureEdge, ...]


class PageStructure(_Closed):
    """Normalized semantic structure of one representative page type."""

    page_type: RepresentativePageType
    canonical_id: str = Field(min_length=1)
    role_histogram: dict[str, int]
    semantic_node_count: int = Field(ge=0)
    interactive_count: int = Field(ge=0)
    semantic_max_depth: int = Field(ge=0)


class StructureSnapshot(_Closed):
    """Content-independent structural snapshot derived from an EnvEval run."""

    version: Literal["0.3"] = SNAPSHOT_VERSION
    shop: SnapshotShop
    graph: GraphStructure
    pages: tuple[PageStructure, ...]


class RoleProfileDistance(_Closed):
    """Order-independent accessibility-role profile distance."""

    role_distribution: float = Field(ge=0.0, le=1.0)
    node_count: float = Field(ge=0.0, le=1.0)
    interactive_ratio: float = Field(ge=0.0, le=1.0)
    maximum_depth: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=1.0)


class PageDistance(_Closed):
    """Role-profile distance for one shared representative page type."""

    page_type: RepresentativePageType
    left_canonical_id: str = Field(min_length=1)
    right_canonical_id: str = Field(min_length=1)
    role_profile: RoleProfileDistance


class SampleReference(_Closed):
    """One cohort sample and its comparison-relative artifact paths."""

    index: int = Field(ge=0)
    url: str = Field(min_length=1)
    metrics: str = Field(min_length=1)
    structure: str = Field(min_length=1)


class PairDistance(_Closed):
    """Layer distances for one unordered pair of cohort samples."""

    left: int = Field(ge=0)
    right: int = Field(ge=0)
    shared_page_count: int = Field(ge=0)
    pages: tuple[PageDistance, ...]
    navigation: float = Field(ge=0.0, le=1.0)
    role_profile: RoleProfileDistance


class DistanceSummary(_Closed):
    """Distribution summary for one structural-distance layer."""

    count: int = Field(ge=1)
    mean: float = Field(ge=0.0, le=1.0)
    median: float = Field(ge=0.0, le=1.0)
    p90: float = Field(ge=0.0, le=1.0)
    minimum: float = Field(ge=0.0, le=1.0)
    maximum: float = Field(ge=0.0, le=1.0)


class RoleProfileSummary(_Closed):
    """Cohort summaries for each role-profile component and its score."""

    role_distribution: DistanceSummary
    node_count: DistanceSummary
    interactive_ratio: DistanceSummary
    maximum_depth: DistanceSummary
    score: DistanceSummary


class VarianceSummary(_Closed):
    """Cohort summaries for deterministic comparison metrics."""

    navigation: DistanceSummary
    role_profile: RoleProfileSummary


class VarianceReport(_Closed):
    """Published website-structure variance report for a URL cohort."""

    version: Literal["0.3"] = REPORT_VERSION
    sample_count: int = Field(ge=2)
    pair_count: int = Field(ge=1)
    samples: tuple[SampleReference, ...]
    pairwise: tuple[PairDistance, ...]
    summary: VarianceSummary


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
    "SNAPSHOT_FILENAME",
    "SNAPSHOT_VERSION",
    "DistanceSummary",
    "GraphStructure",
    "PageDistance",
    "PageStructure",
    "PairDistance",
    "RepresentativePageType",
    "RoleProfileDistance",
    "RoleProfileSummary",
    "SampleReference",
    "SnapshotShop",
    "StructureEdge",
    "StructureSnapshot",
    "VarianceReport",
    "VarianceSummary",
    "dump_report",
    "dump_snapshot",
    "load_snapshot",
]
