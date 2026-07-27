"""Structural-snapshot extraction from completed EnvEval run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shop_arena.env_eval.errors import StructureComparisonError
from shop_arena.env_eval.schema.metrics import (
    Action,
    CartAndSearch,
    Metrics,
    NotFound,
    Observation,
    PageOk,
    Pages,
    Shop,
    Transition,
    dump_metrics,
)
from shop_arena.env_eval.structure.snapshot import extract_snapshot
from shop_arena.env_eval.transition.graph import (
    GraphEdge,
    GraphNode,
    TransitionGraph,
    write_graph_json,
)
from shop_arena.env_eval.transition.node_artifacts import node_folder_name

_URL = "https://shop.example/"


def _axtree(*, heading_name: str) -> dict[str, Any]:
    """Return a small ordered tree with content text that must be ignored."""
    return {
        "nodes": [
            {
                "nodeId": "1",
                "role": {"value": "RootWebArea"},
                "name": {"value": "Shop title"},
                "childIds": ["2", "4", "8"],
            },
            {
                "nodeId": "2",
                "role": {"value": "banner"},
                "name": {"value": "Header"},
                "childIds": ["3"],
            },
            {
                "nodeId": "3",
                "role": {"value": "navigation"},
                "name": {"value": "Main menu"},
                "childIds": [],
            },
            {
                "nodeId": "4",
                "role": {"value": "main"},
                "name": {"value": "Page body"},
                "childIds": ["5", "6"],
            },
            {
                "nodeId": "5",
                "role": {"value": "heading"},
                "name": {"value": heading_name},
                "childIds": [],
            },
            {
                "nodeId": "6",
                "role": {"value": "generic"},
                "name": {"value": "Layout wrapper"},
                "childIds": ["7"],
            },
            {
                "nodeId": "7",
                "role": {"value": "list"},
                "name": {"value": "Generated products"},
                "childIds": [],
            },
            {
                "nodeId": "8",
                "role": {"value": "contentinfo"},
                "name": {"value": "Footer"},
                "childIds": [],
            },
        ],
    }


def _write_run(
    run_dir: Path,
    *,
    heading_name: str,
    include_extra_url: bool = False,
) -> None:
    """Write the minimum valid EnvEval artifact set consumed by extraction."""
    run_dir.mkdir(parents=True)
    metrics = Metrics(
        shop=Shop(url=_URL, domain="shop.example"),
        pages=Pages(
            homepage=PageOk(url="/", selected_by="input"),
            collection=NotFound(reason="not_needed"),
            product=NotFound(reason="not_needed"),
            policy=NotFound(reason="not_needed"),
            cart_and_search=CartAndSearch(
                cart=NotFound(reason="not_needed"),
                search=NotFound(reason="not_needed"),
            ),
        ),
        observation=Observation(
            node_count=8,
            interactive_count=0,
            distinct_node_count=6,
            max_depth=3,
            semantic_max_depth=2,
            content_character_count=100,
        ),
        action=Action(),
        transition=Transition(
            node_count=1,
            edge_count=1,
            state_node_count=0,
            avg_out_degree=1.0,
            max_out_degree=1,
            dead_end_count=0,
            diameter=None,
            reachable_pct_from_homepage=1.0,
            homepage_to_cart_min_clicks=None,
        ),
    )
    dump_metrics(metrics, run_dir / "metrics.json")

    nodes = {"/": GraphNode(canonical_id="/", representative_url=_URL)}
    edges = [
        GraphEdge(
            source="/",
            target="/",
            label=f"click({_URL}?content-specific=true)",
        ),
    ]
    if include_extra_url:
        nodes["/pages/about"] = GraphNode(
            canonical_id="/pages/about",
            representative_url=f"{_URL}pages/about",
        )
        edges.append(
            GraphEdge(
                source="/",
                target="/pages/about",
                label=f"click({_URL}pages/about)",
            ),
        )
    graph = TransitionGraph(
        nodes=nodes,
        edges=edges,
        seeds=["/"],
    )
    (run_dir / "transition").mkdir()
    write_graph_json(graph, run_dir / "transition" / "graph.json")
    observation_dir = run_dir / "observation"
    observation_dir.mkdir()
    folder = node_folder_name("/")
    (observation_dir / f"{folder}.axtree.json").write_text(
        json.dumps(_axtree(heading_name=heading_name)),
        encoding="utf-8",
    )


def test_extract_snapshot_ignores_content(tmp_path: Path) -> None:
    """Accessible names and edge href labels do not enter the snapshot."""
    first_run = tmp_path / "first"
    second_run = tmp_path / "second"
    _write_run(first_run, heading_name="Coffee collection")
    _write_run(second_run, heading_name="Completely different catalog text")

    first = extract_snapshot(first_run)
    second = extract_snapshot(second_run)

    assert first.graph == second.graph
    assert first.pages == second.pages
    assert first.graph.url_edges[0].model_dump() == {
        "source": "/",
        "target": "/",
        "action": "click",
    }
    page = first.pages[0]
    assert page.page_type == "homepage"
    assert page.semantic_node_count == 6
    assert page.semantic_max_depth == 2
    assert "generic" not in page.role_histogram
    assert "rootwebarea" not in page.role_histogram


def test_extract_snapshot_uses_only_discovered_representative_pages(tmp_path: Path) -> None:
    """Crawled URL nodes remain navigational but do not add page samples."""
    run_dir = tmp_path / "run"
    _write_run(
        run_dir,
        heading_name="Heading",
        include_extra_url=True,
    )

    snapshot = extract_snapshot(run_dir)

    assert snapshot.graph.url_nodes == ("/", "/pages/about")
    assert [(page.page_type, page.canonical_id) for page in snapshot.pages] == [
        ("homepage", "/"),
    ]


def test_extract_snapshot_fails_when_page_axtree_is_missing(tmp_path: Path) -> None:
    """Missing per-page source artifacts fail loudly."""
    run_dir = tmp_path / "run"
    _write_run(run_dir, heading_name="Heading")
    (run_dir / "observation" / "home.axtree.json").unlink()

    with pytest.raises(StructureComparisonError, match="accessibility tree"):
        extract_snapshot(run_dir)
