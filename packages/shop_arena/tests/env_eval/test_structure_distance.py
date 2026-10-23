"""Mean-centered structural-distance and cohort-summary tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shop_arena.env_eval.structure.distance import (
    compute_cohort_mean,
    distances_from_mean,
    summarize_distances,
)
from shop_arena.env_eval.structure.schema import (
    PageStructure,
    RepresentativePageType,
    SnapshotShop,
    StructureSnapshot,
)


def _snapshot(
    *,
    url: str,
    elements: dict[str, int],
    depth: int,
    page_type: RepresentativePageType = "homepage",
    canonical_id: str = "/",
) -> StructureSnapshot:
    """Build one compact structural snapshot."""
    return StructureSnapshot(
        shop=SnapshotShop(url=url, eval_version="test"),
        pages=(
            PageStructure(
                page_type=page_type,
                canonical_id=canonical_id,
                element_type_histogram=elements,
                maximum_depth=depth,
            ),
        ),
    )


def test_identical_snapshots_have_zero_distance_from_mean() -> None:
    """Identical shops equal their cohort mean on both retained metrics."""
    snapshots = (
        _snapshot(
            url="https://a.example/",
            elements={"main": 1, "heading": 1},
            depth=2,
        ),
        _snapshot(
            url="https://b.example/",
            elements={"main": 1, "heading": 1},
            depth=2,
        ),
    )

    cohort_mean = compute_cohort_mean(snapshots)
    distances = distances_from_mean(snapshots, cohort_mean)

    assert cohort_mean.pages[0].model_dump() == {
        "page_type": "homepage",
        "sample_count": 2,
        "element_type_distribution": {"heading": 0.5, "main": 0.5},
        "maximum_depth": 2.0,
    }
    assert len(distances) == 2
    assert distances[0].profile.model_dump() == {
        "element_type_distribution": 0.0,
        "maximum_depth": 0.0,
    }
    assert distances[1].profile == distances[0].profile


def test_three_shop_distances_are_computed_from_cohort_mean() -> None:
    """Each shop is compared with one centroid, not with every other shop."""
    snapshots = (
        _snapshot(url="https://a.example/", elements={"button": 1}, depth=2),
        _snapshot(url="https://b.example/", elements={"button": 1}, depth=2),
        _snapshot(url="https://c.example/", elements={"heading": 1}, depth=5),
    )

    cohort_mean = compute_cohort_mean(snapshots)
    distances = distances_from_mean(snapshots, cohort_mean)
    summary = summarize_distances(distances)

    assert cohort_mean.pages[0].element_type_distribution == {
        "button": 0.666666666667,
        "heading": 0.333333333333,
    }
    assert cohort_mean.pages[0].maximum_depth == 3.0
    assert [distance.profile.model_dump() for distance in distances] == [
        {
            "element_type_distribution": 0.333333,
            "maximum_depth": 0.333333,
        },
        {
            "element_type_distribution": 0.333333,
            "maximum_depth": 0.333333,
        },
        {
            "element_type_distribution": 0.666667,
            "maximum_depth": 0.4,
        },
    ]
    assert summary.element_type_distribution.mean == 0.444444
    assert summary.maximum_depth.mean == 0.355555


def test_distances_preserve_page_type_and_shop_route() -> None:
    """Equivalent page types share a mean even when their routes differ."""
    snapshots = (
        _snapshot(
            url="https://a.example/",
            elements={"main": 1, "heading": 1},
            depth=2,
            page_type="policy",
            canonical_id="/policies/<*>",
        ),
        _snapshot(
            url="https://b.example/",
            elements={"main": 1, "heading": 1},
            depth=2,
            page_type="policy",
            canonical_id="/pages/privacy-policy",
        ),
    )

    cohort_mean = compute_cohort_mean(snapshots)
    distances = distances_from_mean(snapshots, cohort_mean)

    assert cohort_mean.pages[0].page_type == "policy"
    assert distances[0].pages[0].canonical_id == "/policies/<*>"
    assert distances[1].pages[0].canonical_id == "/pages/privacy-policy"
    assert distances[0].pages[0].profile.maximum_depth == 0.0


def test_empty_element_profile_is_measured_as_missing_distribution_mass() -> None:
    """A blank profile and populated profile are equally far from their mean."""
    snapshots = (
        _snapshot(url="https://blank.example/", elements={}, depth=0),
        _snapshot(url="https://button.example/", elements={"button": 1}, depth=0),
    )

    cohort_mean = compute_cohort_mean(snapshots)
    distances = distances_from_mean(snapshots, cohort_mean)

    assert cohort_mean.pages[0].element_type_distribution == {"button": 0.5}
    assert [distance.profile.element_type_distribution for distance in distances] == [
        0.5,
        0.5,
    ]


def test_snapshot_schema_rejects_unknown_fields() -> None:
    """Published structure documents remain closed."""
    payload: dict[str, object] = {
        "shop": {"url": "https://a.example/", "eval_version": "test"},
        "pages": [],
        "unexpected": True,
    }

    with pytest.raises(ValidationError):
        StructureSnapshot.model_validate(payload)
