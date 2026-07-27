"""Extract deterministic website-structure snapshots from EnvEval artifacts."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

from shop_arena.env_eval.errors import StructureComparisonError
from shop_arena.env_eval.observation.axtree_stats import (
    SEMANTIC_DEPTH_IGNORED_ROLES,
    compute_axtree_stats,
)
from shop_arena.env_eval.schema import metrics as metrics_mod
from shop_arena.env_eval.structure.schema import (
    GraphStructure,
    PageStructure,
    RepresentativePageType,
    SnapshotShop,
    StructureEdge,
    StructureSnapshot,
)
from shop_arena.env_eval.transition import node_artifacts
from shop_arena.env_eval.transition.canonicalize import canonical_id_for_url
from shop_arena.env_eval.transition.graph import TransitionGraph

_IGNORED_ROLES: Final[frozenset[str]] = frozenset(
    role.casefold() for role in SEMANTIC_DEPTH_IGNORED_ROLES
) | frozenset({"rootwebarea", "webarea"})


def extract_snapshot(run_dir: Path | str) -> StructureSnapshot:
    """Build a content-independent structural snapshot from an EnvEval run.

    Args:
        run_dir: Completed EnvEval run directory.

    Returns:
        Validated structural snapshot.

    Raises:
        StructureComparisonError: Required artifacts are missing or invalid.
    """
    root = Path(run_dir)
    metrics = metrics_mod.load_metrics(root / "metrics.json")
    graph = _load_graph(root)

    url_node_ids = frozenset(
        node.canonical_id for node in graph.nodes.values() if node.kind == "url"
    )
    url_edges: list[StructureEdge] = []
    for edge in graph.edges:
        structural_edge = StructureEdge(
            source=edge.source,
            target=edge.target,
            action=edge.action,
        )
        if edge.source in url_node_ids and edge.target in url_node_ids:
            url_edges.append(structural_edge)

    representative_pages = _representative_page_ids(metrics)
    for page_type, canonical_id in representative_pages:
        if canonical_id not in url_node_ids:
            raise StructureComparisonError(
                f"representative {page_type} page {canonical_id!r} is absent from "
                "the transition graph",
            )
    pages = tuple(
        _extract_page_structure(root, page_type, canonical_id)
        for page_type, canonical_id in representative_pages
    )
    return StructureSnapshot(
        shop=SnapshotShop(
            url=metrics.shop.url,
            eval_version=metrics.shop.eval_version,
        ),
        graph=GraphStructure(
            url_nodes=tuple(sorted(url_node_ids)),
            url_edges=tuple(sorted(url_edges, key=_edge_key)),
        ),
        pages=pages,
    )


def _load_graph(run_dir: Path) -> TransitionGraph:
    """Load the canonical transition graph from an EnvEval run."""
    path = run_dir / "transition" / "graph.json"
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("top-level graph payload must be an object")
        # TransitionGraph is the owning parser for its JSON artifact. The Any
        # cast is confined to this untyped JSON I/O boundary.
        return TransitionGraph.from_dict(cast("dict[str, Any]", raw))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise StructureComparisonError(f"cannot load transition graph {path}: {exc}") from exc


def _representative_page_ids(
    metrics: metrics_mod.Metrics,
) -> tuple[tuple[RepresentativePageType, str], ...]:
    """Return one discovered representative for each available page type."""
    entries: tuple[
        tuple[
            RepresentativePageType,
            metrics_mod.PageEntry | metrics_mod.SearchPageEntry,
        ],
        ...,
    ] = (
        ("homepage", metrics.pages.homepage),
        ("collection", metrics.pages.collection),
        ("product", metrics.pages.product),
        ("policy", metrics.pages.policy),
        ("cart", metrics.pages.cart_and_search.cart),
        ("search", metrics.pages.cart_and_search.search),
    )
    representatives: list[tuple[RepresentativePageType, str]] = []
    for page_type, entry in entries:
        if isinstance(entry, metrics_mod.NotFound):
            continue
        canonical_id = (
            entry.canonical_url
            if isinstance(entry, metrics_mod.PageOk) and entry.canonical_url is not None
            else canonical_id_for_url(entry.url)
        )
        representatives.append((page_type, canonical_id))
    return tuple(representatives)


def _extract_page_structure(
    run_dir: Path,
    page_type: RepresentativePageType,
    canonical_id: str,
) -> PageStructure:
    """Extract one representative page's normalized accessibility structure."""
    folder = node_artifacts.node_folder_name(canonical_id)
    path = run_dir / "observation" / f"{folder}.axtree.json"
    axtree = _load_axtree(path)
    stats = compute_axtree_stats(axtree)
    role_histogram = _role_histogram(axtree)
    return PageStructure(
        page_type=page_type,
        canonical_id=canonical_id,
        role_histogram=role_histogram,
        semantic_node_count=sum(role_histogram.values()),
        interactive_count=stats.interactive_count,
        semantic_max_depth=stats.semantic_max_depth,
    )


def _load_axtree(path: Path) -> dict[str, Any]:
    """Load one BrowserGym accessibility tree at the JSON boundary."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StructureComparisonError(f"cannot load accessibility tree {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise StructureComparisonError(
            f"accessibility tree {path} must contain a top-level object",
        )
    # BrowserGym axtrees are intentionally open dictionaries owned by the
    # upstream library; keep Any confined to this loader and pure consumers.
    return cast("dict[str, Any]", raw)


def _role_histogram(axtree: Mapping[str, Any]) -> dict[str, int]:
    """Return a sorted histogram of content-independent semantic roles."""
    counter: Counter[str] = Counter()
    for node in _nodes(axtree):
        role = _normalized_role(node)
        if role and role not in _IGNORED_ROLES:
            counter[role] += 1
    return dict(sorted(counter.items()))


def _nodes(axtree: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return mapping-shaped axtree nodes in source order."""
    raw_nodes: object = axtree.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise StructureComparisonError("accessibility tree 'nodes' must be a list")
    return tuple(
        cast("Mapping[str, Any]", node)
        for node in cast("list[object]", raw_nodes)
        if isinstance(node, Mapping)
    )


def _normalized_role(node: Mapping[str, Any]) -> str:
    """Return a lowercase CDP role value without reading accessible text."""
    raw_role: object = node.get("role")
    if not isinstance(raw_role, Mapping):
        return ""
    value: object = cast("Mapping[str, object]", raw_role).get("value")
    return value.casefold() if isinstance(value, str) else ""


def _edge_key(edge: StructureEdge) -> tuple[str, str, str]:
    """Return deterministic ordering fields for one structural edge."""
    return (edge.source, edge.target, edge.action)


__all__ = ["extract_snapshot"]
