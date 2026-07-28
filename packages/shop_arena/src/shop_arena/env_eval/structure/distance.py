"""Pure mean-centered distance functions for structural snapshots."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from statistics import fmean, median

from shop_arena.env_eval.structure.schema import (
    REPRESENTATIVE_PAGE_TYPES,
    CohortMean,
    DistanceSummary,
    MeanPageProfile,
    PageDistance,
    PageStructure,
    ProfileDistance,
    ProfileSummary,
    RepresentativePageType,
    SampleDistance,
    StructureSnapshot,
)

_ROUND_DIGITS = 6
_MEAN_ROUND_DIGITS = 12
_MIN_SAMPLES = 2
type _ProfileComponents = tuple[float, float]


def compute_cohort_mean(snapshots: Sequence[StructureSnapshot]) -> CohortMean:
    """Compute one mean AXTree profile per available page type."""
    if len(snapshots) < _MIN_SAMPLES:
        raise ValueError("at least two structural snapshots are required")

    page_groups: dict[RepresentativePageType, list[PageStructure]] = {
        page_type: [] for page_type in REPRESENTATIVE_PAGE_TYPES
    }
    for snapshot in snapshots:
        for page in snapshot.pages:
            page_groups[page.page_type].append(page)

    pages: list[MeanPageProfile] = []
    for page_type in REPRESENTATIVE_PAGE_TYPES:
        samples = page_groups[page_type]
        if not samples:
            continue
        pages.append(
            MeanPageProfile(
                page_type=page_type,
                sample_count=len(samples),
                element_type_distribution=_mean_distribution(samples),
                maximum_depth=_mean_rounded(page.maximum_depth for page in samples),
            ),
        )
    return CohortMean(pages=tuple(pages))


def distances_from_mean(
    snapshots: Sequence[StructureSnapshot],
    cohort_mean: CohortMean,
) -> tuple[SampleDistance, ...]:
    """Compute every shop's distance from the supplied cohort mean."""
    if len(snapshots) < _MIN_SAMPLES:
        raise ValueError("at least two structural snapshots are required")
    mean_pages = {page.page_type: page for page in cohort_mean.pages}

    distances: list[SampleDistance] = []
    for sample_index, snapshot in enumerate(snapshots):
        sample_pages = {page.page_type: page for page in snapshot.pages}
        page_distances: list[PageDistance] = []
        components: list[_ProfileComponents] = []
        for page_type in REPRESENTATIVE_PAGE_TYPES:
            page = sample_pages.get(page_type)
            mean_page = mean_pages.get(page_type)
            if page is None or mean_page is None:
                continue
            page_components = _page_components(page, mean_page)
            components.append(page_components)
            page_distances.append(
                PageDistance(
                    page_type=page_type,
                    canonical_id=page.canonical_id,
                    profile=_profile_distance(page_components),
                ),
            )
        if not components:
            raise ValueError(f"snapshot {sample_index} has no representative pages")
        distances.append(
            SampleDistance(
                sample=sample_index,
                page_count=len(page_distances),
                pages=tuple(page_distances),
                profile=_aggregate_profile(components),
            ),
        )
    return tuple(distances)


def summarize_distances(distances: Sequence[SampleDistance]) -> ProfileSummary:
    """Summarize shop-to-mean distances by retained component."""
    if not distances:
        raise ValueError("at least one sample distance is required")
    profiles = [distance.profile for distance in distances]
    return ProfileSummary(
        element_type_distribution=_summarize(
            [profile.element_type_distribution for profile in profiles],
        ),
        maximum_depth=_summarize([profile.maximum_depth for profile in profiles]),
    )


def _mean_distribution(pages: Sequence[PageStructure]) -> dict[str, float]:
    """Return the mean normalized element-type distribution for pages."""
    distributions = [_normalized_distribution(page.element_type_histogram) for page in pages]
    keys: set[str] = set()
    for distribution in distributions:
        keys.update(distribution)
    return {
        key: round(
            fmean(distribution.get(key, 0.0) for distribution in distributions),
            _MEAN_ROUND_DIGITS,
        )
        for key in sorted(keys)
    }


def _page_components(
    page: PageStructure,
    mean_page: MeanPageProfile,
) -> _ProfileComponents:
    """Return one page's two distances from its page-type mean."""
    return (
        _distribution_distance(
            _normalized_distribution(page.element_type_histogram),
            mean_page.element_type_distribution,
        ),
        _relative_difference(page.maximum_depth, mean_page.maximum_depth),
    )


def _profile_distance(components: _ProfileComponents) -> ProfileDistance:
    """Build a rounded profile distance from its raw components."""
    element_type_distribution, maximum_depth = components
    return ProfileDistance(
        element_type_distribution=_rounded(element_type_distribution),
        maximum_depth=_rounded(maximum_depth),
    )


def _aggregate_profile(pages: Sequence[_ProfileComponents]) -> ProfileDistance:
    """Average raw profile components across one shop's pages."""
    components: _ProfileComponents = (
        fmean(page[0] for page in pages),
        fmean(page[1] for page in pages),
    )
    return _profile_distance(components)


def _normalized_distribution(histogram: Mapping[str, int]) -> dict[str, float]:
    """Normalize non-negative element-type counts to a probability vector."""
    total = sum(histogram.values())
    if total <= 0:
        return {}
    return {key: value / total for key, value in histogram.items()}


def _distribution_distance(
    sample: Mapping[str, float],
    mean: Mapping[str, float],
) -> float:
    """Return total-variation distance from a mean element distribution."""
    keys = sample.keys() | mean.keys()
    element_difference = sum(abs(sample.get(key, 0.0) - mean.get(key, 0.0)) for key in keys)
    sample_empty_mass = max(0.0, 1.0 - sum(sample.values()))
    mean_empty_mass = max(0.0, 1.0 - sum(mean.values()))
    return 0.5 * (element_difference + abs(sample_empty_mass - mean_empty_mass))


def _relative_difference(sample: int, mean: float) -> float:
    """Return scale-independent absolute difference from a non-negative mean."""
    return abs(sample - mean) / max(sample, mean, 1.0)


def _mean_rounded(values: Iterable[int]) -> float:
    """Return a stable, high-precision mean for a published centroid."""
    return round(fmean(values), _MEAN_ROUND_DIGITS)


def _summarize(values: Sequence[float]) -> DistanceSummary:
    """Return deterministic descriptive statistics for one component."""
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


__all__ = ["compute_cohort_mean", "distances_from_mean", "summarize_distances"]
