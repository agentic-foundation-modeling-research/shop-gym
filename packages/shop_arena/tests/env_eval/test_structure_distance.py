"""Pure structural-distance and cohort-summary tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shop_arena.env_eval.structure.distance import (
    compare_snapshots,
    pairwise_distances,
    summarize_distances,
)
from shop_arena.env_eval.structure.schema import (
    GraphStructure,
    PageStructure,
    RepresentativePageType,
    SnapshotShop,
    StructureEdge,
    StructureSnapshot,
)


def _snapshot(
    *,
    url: str,
    page_node: str,
    page_edge: StructureEdge,
    roles: dict[str, int],
    node_count: int,
    interactive_count: int,
    depth: int,
    page_type: RepresentativePageType = "homepage",
    page_canonical_id: str = "/",
) -> StructureSnapshot:
    """Build one compact structural snapshot."""
    return StructureSnapshot(
        shop=SnapshotShop(url=url, eval_version="test"),
        graph=GraphStructure(
            url_nodes=("/", page_node),
            url_edges=(page_edge,),
        ),
        pages=(
            PageStructure(
                page_type=page_type,
                canonical_id=page_canonical_id,
                role_histogram=roles,
                semantic_node_count=node_count,
                interactive_count=interactive_count,
                semantic_max_depth=depth,
            ),
        ),
    )


def test_identical_snapshots_have_zero_distance() -> None:
    """Navigation and every role-profile component are zero when identical."""
    snapshot = _snapshot(
        url="https://a.example/",
        page_node="/products/<*>",
        page_edge=StructureEdge(source="/", target="/products/<*>", action="click"),
        roles={"main": 1, "heading": 1},
        node_count=10,
        interactive_count=2,
        depth=2,
    )

    distance = compare_snapshots(snapshot, snapshot, left_index=0, right_index=1)

    assert distance.navigation == 0.0
    assert len(distance.pages) == 1
    assert distance.pages[0].page_type == "homepage"
    assert distance.role_profile.model_dump() == {
        "role_distribution": 0.0,
        "node_count": 0.0,
        "interactive_ratio": 0.0,
        "maximum_depth": 0.0,
        "score": 0.0,
    }


def test_distance_reports_role_profile_components() -> None:
    """Role-profile score is the mean of its four order-independent parts."""
    left = _snapshot(
        url="https://a.example/",
        page_node="/products/<*>",
        page_edge=StructureEdge(source="/", target="/products/<*>", action="click"),
        roles={"main": 1, "heading": 1},
        node_count=10,
        interactive_count=2,
        depth=2,
    )
    right = _snapshot(
        url="https://b.example/",
        page_node="/collections/<*>",
        page_edge=StructureEdge(source="/", target="/collections/<*>", action="click"),
        roles={"main": 1, "region": 1, "heading": 1},
        node_count=20,
        interactive_count=8,
        depth=3,
    )

    distance = compare_snapshots(left, right, left_index=0, right_index=1)

    assert distance.shared_page_count == 1
    assert distance.navigation == 0.833333
    assert distance.role_profile.model_dump() == {
        "role_distribution": 0.333333,
        "node_count": 0.5,
        "interactive_ratio": 0.2,
        "maximum_depth": 0.333333,
        "score": 0.341667,
    }
    assert distance.pages[0].role_profile == distance.role_profile


def test_page_structure_is_compared_by_type_not_route() -> None:
    """Equivalent page types remain comparable when their URL shapes differ."""
    left = _snapshot(
        url="https://a.example/",
        page_node="/policies/<*>",
        page_edge=StructureEdge(source="/", target="/policies/<*>", action="click"),
        roles={"main": 1, "heading": 1},
        node_count=2,
        interactive_count=0,
        depth=2,
        page_type="policy",
        page_canonical_id="/policies/<*>",
    )
    right = _snapshot(
        url="https://b.example/",
        page_node="/pages/privacy-policy",
        page_edge=StructureEdge(
            source="/",
            target="/pages/privacy-policy",
            action="click",
        ),
        roles={"main": 1, "heading": 1},
        node_count=2,
        interactive_count=0,
        depth=2,
        page_type="policy",
        page_canonical_id="/pages/privacy-policy",
    )

    distance = compare_snapshots(left, right, left_index=0, right_index=1)

    assert distance.shared_page_count == 1
    assert distance.pages[0].model_dump() == {
        "page_type": "policy",
        "left_canonical_id": "/policies/<*>",
        "right_canonical_id": "/pages/privacy-policy",
        "role_profile": {
            "role_distribution": 0.0,
            "node_count": 0.0,
            "interactive_ratio": 0.0,
            "maximum_depth": 0.0,
            "score": 0.0,
        },
    }
    assert distance.role_profile.score == 0.0


def test_pairwise_summary_reports_mean_and_p90() -> None:
    """A three-sample cohort produces three pairs and layer summaries."""
    base = _snapshot(
        url="https://a.example/",
        page_node="/products/<*>",
        page_edge=StructureEdge(source="/", target="/products/<*>", action="click"),
        roles={"main": 1},
        node_count=1,
        interactive_count=0,
        depth=1,
    )
    snapshots = (
        base,
        base.model_copy(
            update={"shop": SnapshotShop(url="https://b.example/", eval_version="test")}
        ),
        base.model_copy(
            update={"shop": SnapshotShop(url="https://c.example/", eval_version="test")}
        ),
    )

    pairs = pairwise_distances(snapshots)
    summary = summarize_distances(pairs)

    assert len(pairs) == 3
    assert summary.navigation.count == 3
    assert summary.navigation.mean == 0.0
    assert summary.navigation.p90 == 0.0
    assert summary.role_profile.score.count == 3
    assert summary.role_profile.score.mean == 0.0
    assert summary.role_profile.role_distribution.mean == 0.0


def test_snapshot_schema_rejects_unknown_fields() -> None:
    """Published structure documents remain closed."""
    payload: dict[str, object] = {
        "shop": {"url": "https://a.example/", "eval_version": "test"},
        "graph": {"url_nodes": [], "url_edges": []},
        "pages": [],
        "unexpected": True,
    }

    with pytest.raises(ValidationError):
        StructureSnapshot.model_validate(payload)
