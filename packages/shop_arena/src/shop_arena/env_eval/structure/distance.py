"""Pure pairwise distance functions for structural snapshots."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import combinations
from statistics import fmean, median
from typing import Final

from shop_arena.env_eval.structure.schema import (
    DistanceSummary,
    PageDistance,
    PageStructure,
    PairDistance,
    RepresentativePageType,
    RoleProfileDistance,
    RoleProfileSummary,
    StructureEdge,
    StructureSnapshot,
    VarianceSummary,
)

_ROUND_DIGITS = 6
_MIN_SAMPLES = 2
_PAGE_TYPE_ORDER: Final[tuple[RepresentativePageType, ...]] = (
    "homepage",
    "collection",
    "product",
    "policy",
    "cart",
    "search",
)
type _RoleProfileComponents = tuple[float, float, float, float]


def compare_snapshots(
    left: StructureSnapshot,
    right: StructureSnapshot,
    *,
    left_index: int,
    right_index: int,
) -> PairDistance:
    """Compute deterministic navigation and role-profile distances."""
    navigation = fmean(
        (
            _jaccard_distance(set(left.graph.url_nodes), set(right.graph.url_nodes)),
            _jaccard_distance(_edge_set(left.graph.url_edges), _edge_set(right.graph.url_edges)),
        ),
    )

    left_pages: dict[RepresentativePageType, PageStructure] = {
        page.page_type: page for page in left.pages
    }
    right_pages: dict[RepresentativePageType, PageStructure] = {
        page.page_type: page for page in right.pages
    }
    shared_ids: list[RepresentativePageType] = []
    for page_type in _PAGE_TYPE_ORDER:
        if page_type in left_pages and page_type in right_pages:
            shared_ids.append(page_type)
    if not shared_ids:
        raise ValueError("snapshots must share at least one representative page type")

    page_distances: list[PageDistance] = []
    role_profile_components: list[_RoleProfileComponents] = []
    for page_type in shared_ids:
        left_page = left_pages[page_type]
        right_page = right_pages[page_type]
        components = _role_profile_components(left_page, right_page)
        role_profile_components.append(components)
        page_distances.append(
            PageDistance(
                page_type=page_type,
                left_canonical_id=left_page.canonical_id,
                right_canonical_id=right_page.canonical_id,
                role_profile=_role_profile_distance(components),
            ),
        )
    return PairDistance(
        left=left_index,
        right=right_index,
        shared_page_count=len(shared_ids),
        pages=tuple(page_distances),
        navigation=_rounded(navigation),
        role_profile=_aggregate_role_profile(role_profile_components),
    )


def pairwise_distances(
    snapshots: Sequence[StructureSnapshot],
) -> tuple[PairDistance, ...]:
    """Return distances for every unordered pair in input order."""
    if len(snapshots) < _MIN_SAMPLES:
        raise ValueError("at least two structural snapshots are required")
    return tuple(
        compare_snapshots(
            snapshots[left_index],
            snapshots[right_index],
            left_index=left_index,
            right_index=right_index,
        )
        for left_index, right_index in combinations(range(len(snapshots)), 2)
    )


def summarize_distances(pairwise: Sequence[PairDistance]) -> VarianceSummary:
    """Summarize deterministic pairwise distances by metric and component."""
    if not pairwise:
        raise ValueError("at least one pairwise distance is required")
    profiles = [pair.role_profile for pair in pairwise]
    return VarianceSummary(
        navigation=_summarize([pair.navigation for pair in pairwise]),
        role_profile=RoleProfileSummary(
            role_distribution=_summarize(
                [profile.role_distribution for profile in profiles],
            ),
            node_count=_summarize([profile.node_count for profile in profiles]),
            interactive_ratio=_summarize(
                [profile.interactive_ratio for profile in profiles],
            ),
            maximum_depth=_summarize([profile.maximum_depth for profile in profiles]),
            score=_summarize([profile.score for profile in profiles]),
        ),
    )


def _role_profile_components(
    left: PageStructure,
    right: PageStructure,
) -> _RoleProfileComponents:
    """Return the four order-independent role-profile components."""
    left_interactive_ratio = left.interactive_count / max(left.semantic_node_count, 1)
    right_interactive_ratio = right.interactive_count / max(right.semantic_node_count, 1)
    return (
        _histogram_distance(left.role_histogram, right.role_histogram),
        _relative_difference(left.semantic_node_count, right.semantic_node_count),
        abs(left_interactive_ratio - right_interactive_ratio),
        _relative_difference(left.semantic_max_depth, right.semantic_max_depth),
    )


def _role_profile_distance(
    components: _RoleProfileComponents,
) -> RoleProfileDistance:
    """Build a rounded role-profile distance from its raw components."""
    role_distribution, node_count, interactive_ratio, maximum_depth = components
    return RoleProfileDistance(
        role_distribution=_rounded(role_distribution),
        node_count=_rounded(node_count),
        interactive_ratio=_rounded(interactive_ratio),
        maximum_depth=_rounded(maximum_depth),
        score=_rounded(fmean(components)),
    )


def _aggregate_role_profile(
    pages: Sequence[_RoleProfileComponents],
) -> RoleProfileDistance:
    """Average raw role-profile components across representative pages."""
    components: _RoleProfileComponents = (
        fmean(page[0] for page in pages),
        fmean(page[1] for page in pages),
        fmean(page[2] for page in pages),
        fmean(page[3] for page in pages),
    )
    return _role_profile_distance(components)


def _edge_set(edges: Sequence[StructureEdge]) -> set[tuple[str, str, str]]:
    """Project structural edges onto hashable content-independent triples."""
    return {(edge.source, edge.target, edge.action) for edge in edges}


def _jaccard_distance[T](left: set[T], right: set[T]) -> float:
    """Return Jaccard distance, defining two empty sets as identical."""
    union = left | right
    if not union:
        return 0.0
    return 1.0 - (len(left & right) / len(union))


def _histogram_distance(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    """Return total-variation distance between normalized role histograms."""
    left_total = sum(left.values())
    right_total = sum(right.values())
    if left_total == 0 and right_total == 0:
        return 0.0
    if left_total == 0 or right_total == 0:
        return 1.0
    keys = left.keys() | right.keys()
    return 0.5 * sum(
        abs((left.get(key, 0) / left_total) - (right.get(key, 0) / right_total)) for key in keys
    )


def _relative_difference(left: int, right: int) -> float:
    """Return scale-independent absolute difference for non-negative counts."""
    return abs(left - right) / max(left, right, 1)


def _summarize(values: Sequence[float]) -> DistanceSummary:
    """Return deterministic descriptive statistics for one layer."""
    ordered = sorted(values)
    return DistanceSummary(
        count=len(ordered),
        mean=_rounded(fmean(ordered)),
        median=_rounded(median(ordered)),
        p90=_rounded(_percentile(ordered, 0.9)),
        minimum=_rounded(ordered[0]),
        maximum=_rounded(ordered[-1]),
    )


def _percentile(ordered: Sequence[float], quantile: float) -> float:
    """Return a linearly interpolated percentile from sorted values."""
    position = quantile * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _rounded(value: float) -> float:
    """Round report values for readable, byte-stable JSON."""
    return round(value, _ROUND_DIGITS)


__all__ = ["compare_snapshots", "pairwise_distances", "summarize_distances"]
