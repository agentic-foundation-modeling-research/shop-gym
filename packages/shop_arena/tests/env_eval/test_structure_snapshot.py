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
    SearchPageOk,
    Shop,
    Transition,
    dump_metrics,
)
from shop_arena.env_eval.structure.snapshot import extract_snapshot
from shop_arena.env_eval.transition.node_artifacts import node_folder_name

_URL = "https://shop.example/"
_ALL_CANONICAL_IDS = (
    "/",
    "/collections/<*>",
    "/products/<*>",
    "/policies/<*>",
    "/cart",
    "/search",
)


def _axtree(*, heading_name: str) -> dict[str, Any]:
    """Return a small tree with content text that must be ignored."""
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
    all_page_types: bool = False,
) -> None:
    """Write the minimum valid EnvEval artifacts consumed by extraction."""
    run_dir.mkdir(parents=True)
    pages = (
        Pages(
            homepage=PageOk(url="/", selected_by="input"),
            collection=PageOk(
                url="/collections/coffee",
                canonical_url="/collections/<*>",
                selected_by="first_href",
            ),
            product=PageOk(
                url="/products/coffee",
                canonical_url="/products/<*>",
                selected_by="first_href",
            ),
            policy=PageOk(
                url="/policies/privacy-policy",
                canonical_url="/policies/<*>",
                selected_by="first_href",
            ),
            cart_and_search=CartAndSearch(
                cart=PageOk(url="/cart", selected_by="convention"),
                search=SearchPageOk(
                    url="/search?q=coffee",
                    query="coffee",
                    selected_by="product_title",
                ),
            ),
        )
        if all_page_types
        else Pages(
            homepage=PageOk(url="/", selected_by="input"),
            collection=NotFound(reason="not_needed"),
            product=NotFound(reason="not_needed"),
            policy=NotFound(reason="not_needed"),
            cart_and_search=CartAndSearch(
                cart=NotFound(reason="not_needed"),
                search=NotFound(reason="not_needed"),
            ),
        )
    )
    metrics = Metrics(
        shop=Shop(url=_URL, domain="shop.example"),
        pages=pages,
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
            edge_count=0,
            state_node_count=0,
            avg_out_degree=0.0,
            max_out_degree=0,
            dead_end_count=1,
            diameter=None,
            reachable_pct_from_homepage=1.0,
            homepage_to_cart_min_clicks=None,
        ),
    )
    dump_metrics(metrics, run_dir / "metrics.json")

    observation_dir = run_dir / "observation"
    observation_dir.mkdir()
    canonical_ids = _ALL_CANONICAL_IDS if all_page_types else ("/",)
    for canonical_id in canonical_ids:
        folder = node_folder_name(canonical_id)
        (observation_dir / f"{folder}.axtree.json").write_text(
            json.dumps(_axtree(heading_name=heading_name)),
            encoding="utf-8",
        )


def test_extract_snapshot_ignores_content(tmp_path: Path) -> None:
    """Accessible names do not enter element types or maximum depth."""
    first_run = tmp_path / "first"
    second_run = tmp_path / "second"
    _write_run(first_run, heading_name="Coffee collection")
    _write_run(second_run, heading_name="Completely different catalog text")

    first = extract_snapshot(first_run)
    second = extract_snapshot(second_run)

    assert first.pages == second.pages
    page = first.pages[0]
    assert page.page_type == "homepage"
    assert page.maximum_depth == 2
    assert sum(page.element_type_histogram.values()) == 6
    assert "generic" not in page.element_type_histogram
    assert "rootwebarea" not in page.element_type_histogram


def test_extract_snapshot_selects_all_six_representative_page_types(
    tmp_path: Path,
) -> None:
    """Exactly one AXTree is retained for every discovered typical page."""
    run_dir = tmp_path / "run"
    _write_run(run_dir, heading_name="Heading", all_page_types=True)

    snapshot = extract_snapshot(run_dir)

    assert [(page.page_type, page.canonical_id) for page in snapshot.pages] == [
        ("homepage", "/"),
        ("collection", "/collections/<*>"),
        ("product", "/products/<*>"),
        ("policy", "/policies/<*>"),
        ("cart", "/cart"),
        ("search", "/search"),
    ]


def test_extract_snapshot_fails_when_page_axtree_is_missing(tmp_path: Path) -> None:
    """Missing per-page source artifacts fail loudly."""
    run_dir = tmp_path / "run"
    _write_run(run_dir, heading_name="Heading")
    (run_dir / "observation" / "home.axtree.json").unlink()

    with pytest.raises(StructureComparisonError, match="accessibility tree"):
        extract_snapshot(run_dir)
