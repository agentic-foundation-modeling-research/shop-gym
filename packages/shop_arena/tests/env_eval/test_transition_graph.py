"""Unit tests for :mod:`shop_arena.env_eval.transition.graph` (M4).

Covers spec §5.5.3 and the impl-plan M4 ``compute_metrics()`` task:

* :meth:`TransitionGraph.from_bfs` translates a
  :class:`~shop_arena.env_eval.transition.bfs.BfsResult` 1:1 (URL nodes
  in insertion order, edges in discovery order, seeds preserved).
* :meth:`TransitionGraph.add_state_node` inserts ``kind="state"``
  nodes idempotently and rejects collisions with URL nodes.
* :meth:`TransitionGraph.add_edge` enforces both endpoints exist.
* :meth:`TransitionGraph.compute_metrics` returns a closed
  :class:`~shop_arena.env_eval.schema.metrics.Transition` doc with every
  spec §5.5.3 field (``node_count``, ``edge_count``,
  ``state_node_count``, degree stats, ``diameter``,
  ``reachable_pct_from_homepage``, ``homepage_to_cart_min_clicks``)
  computed correctly across linear, fork, dead-end, cyclic, and
  disconnected fixtures.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from shop_arena.env_eval.schema.metrics import Transition
from shop_arena.env_eval.transition.bfs import BfsEdge, BfsNode, BfsResult
from shop_arena.env_eval.transition.graph import (
    CART_DRAWER_STATE,
    GraphEdge,
    GraphNode,
    TransitionGraph,
    write_graph_json,
)


def _bfs(
    nodes: list[tuple[str, str]],
    edges: list[tuple[str, str, str]],
    seeds: list[str],
) -> BfsResult:
    """Build a minimal ``BfsResult`` from compact tuples for fixtures."""
    return BfsResult(
        nodes={cid: BfsNode(canonical_id=cid, representative_url=url) for cid, url in nodes},
        edges=[BfsEdge(source=s, target=t, href=h) for s, t, h in edges],
        seeds=list(seeds),
        attempts=[],
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_from_bfs_preserves_node_and_edge_order() -> None:
    """``from_bfs`` is a 1:1 translation in insertion order."""
    result = _bfs(
        nodes=[
            ("/", "https://shop/"),
            ("/cart", "https://shop/cart"),
            ("/products/<*>", "https://shop/products/red-shirt"),
        ],
        edges=[
            ("/", "/cart", "https://shop/cart"),
            ("/", "/products/<*>", "https://shop/products/red-shirt"),
        ],
        seeds=["/", "/cart"],
    )
    graph = TransitionGraph.from_bfs(result)
    assert list(graph.nodes.keys()) == ["/", "/cart", "/products/<*>"]
    assert all(node.kind == "url" for node in graph.nodes.values())
    assert [(e.source, e.target) for e in graph.edges] == [
        ("/", "/cart"),
        ("/", "/products/<*>"),
    ]
    assert graph.seeds == ["/", "/cart"]
    # Edge label format mirrors the BFS edge label exactly.
    assert graph.edges[0].label == "click(https://shop/cart)"
    assert graph.edges[0].action == "click"


def test_from_bfs_empty_result_yields_empty_graph() -> None:
    """An empty BFS result produces an empty graph (no metrics-time crash)."""
    graph = TransitionGraph.from_bfs(_bfs(nodes=[], edges=[], seeds=[]))
    assert graph.nodes == {}
    assert graph.edges == []
    assert graph.seeds == []


# ---------------------------------------------------------------------------
# State nodes + edges
# ---------------------------------------------------------------------------


def test_add_state_node_assigns_state_kind() -> None:
    """``add_state_node`` inserts a ``kind="state"`` entry with the given name."""
    graph = TransitionGraph()
    node = graph.add_state_node(
        canonical_id="state:/:cart_drawer",
        representative_url="https://shop/",
        state_name=CART_DRAWER_STATE,
    )
    assert node == GraphNode(
        canonical_id="state:/:cart_drawer",
        representative_url="https://shop/",
        kind="state",
        state_name=CART_DRAWER_STATE,
    )
    assert graph.nodes["state:/:cart_drawer"].state_name == CART_DRAWER_STATE


def test_add_state_node_idempotent_keeps_first_seen() -> None:
    """Re-adding the same id preserves the first-seen state name + URL."""
    graph = TransitionGraph()
    graph.add_state_node(
        canonical_id="state:x",
        representative_url="https://shop/a",
        state_name="cart_drawer",
    )
    again = graph.add_state_node(
        canonical_id="state:x",
        representative_url="https://shop/b",
        state_name="search_overlay",
    )
    assert again.representative_url == "https://shop/a"
    assert again.state_name == "cart_drawer"
    assert len(graph.nodes) == 1


def test_add_state_node_rejects_url_collision() -> None:
    """A canonical id that already names a URL node fails loudly."""
    result = _bfs(nodes=[("/", "https://shop/")], edges=[], seeds=["/"])
    graph = TransitionGraph.from_bfs(result)
    with pytest.raises(ValueError, match="already exists"):
        graph.add_state_node(
            canonical_id="/",
            representative_url="https://shop/",
            state_name=CART_DRAWER_STATE,
        )


def test_add_edge_requires_both_endpoints() -> None:
    """``add_edge`` raises when an endpoint is missing from the node table."""
    graph = TransitionGraph()
    graph.nodes["/"] = GraphNode(canonical_id="/", representative_url="https://shop/")
    with pytest.raises(KeyError, match="target"):
        graph.add_edge(source="/", target="/cart", label="click(...)")
    with pytest.raises(KeyError, match="source"):
        graph.nodes["/cart"] = GraphNode(
            canonical_id="/cart", representative_url="https://shop/cart"
        )
        graph.add_edge(source="/missing", target="/cart", label="click(...)")


def test_add_edge_appends_in_order() -> None:
    """Edges added via ``add_edge`` keep insertion order and the action kind."""
    graph = TransitionGraph()
    graph.nodes["/"] = GraphNode(canonical_id="/", representative_url="https://shop/")
    graph.nodes["s"] = GraphNode(
        canonical_id="s",
        representative_url="https://shop/",
        kind="state",
        state_name="search_overlay",
    )
    edge = graph.add_edge(source="/", target="s", label="click(header.search)", action="click")
    assert graph.edges == [edge]
    assert edge == GraphEdge(source="/", target="s", label="click(header.search)", action="click")


# ---------------------------------------------------------------------------
# to_dict serializer
# ---------------------------------------------------------------------------


def test_to_dict_is_byte_stable_for_fixed_input() -> None:
    """Repeated ``to_dict`` calls produce identical output for fixed input."""
    result = _bfs(
        nodes=[("/", "https://shop/"), ("/cart", "https://shop/cart")],
        edges=[("/", "/cart", "https://shop/cart")],
        seeds=["/"],
    )
    graph = TransitionGraph.from_bfs(result)
    graph.add_state_node(
        canonical_id="state:/:cart_drawer",
        representative_url="https://shop/",
        state_name=CART_DRAWER_STATE,
    )
    a = graph.to_dict()
    b = graph.to_dict()
    assert a == b
    assert a == {
        "nodes": [
            {
                "canonical_id": "/",
                "representative_url": "https://shop/",
                "kind": "url",
                "state_name": None,
            },
            {
                "canonical_id": "/cart",
                "representative_url": "https://shop/cart",
                "kind": "url",
                "state_name": None,
            },
            {
                "canonical_id": "state:/:cart_drawer",
                "representative_url": "https://shop/",
                "kind": "state",
                "state_name": "cart_drawer",
            },
        ],
        "edges": [
            {
                "source": "/",
                "target": "/cart",
                "label": "click(https://shop/cart)",
                "action": "click",
            },
        ],
        "seeds": ["/"],
    }


# ---------------------------------------------------------------------------
# compute_metrics — basic shape + empty graph
# ---------------------------------------------------------------------------


def test_compute_metrics_empty_graph_is_zeroed() -> None:
    """An empty graph yields a fully-zeroed Transition with diameter=None."""
    graph = TransitionGraph()
    metrics = graph.compute_metrics()
    assert isinstance(metrics, Transition)
    assert metrics.node_count == 0
    assert metrics.edge_count == 0
    assert metrics.state_node_count == 0
    assert metrics.avg_out_degree == 0.0
    assert metrics.max_out_degree == 0
    assert metrics.dead_end_count == 0
    assert metrics.diameter is None
    assert metrics.reachable_pct_from_homepage == 0.0
    assert metrics.homepage_to_cart_min_clicks is None


def test_compute_metrics_single_node_diameter_is_none() -> None:
    """A graph with one node has no ordered pair → diameter is None."""
    graph = TransitionGraph.from_bfs(
        _bfs(nodes=[("/", "https://shop/")], edges=[], seeds=["/"]),
    )
    metrics = graph.compute_metrics()
    assert metrics.node_count == 1
    assert metrics.diameter is None
    assert metrics.dead_end_count == 1
    assert metrics.reachable_pct_from_homepage == 1.0


# ---------------------------------------------------------------------------
# compute_metrics — degree stats
# ---------------------------------------------------------------------------


def test_compute_metrics_degree_stats_on_fork() -> None:
    """Fork from `/` to two leaves: avg=2/3, max=2, dead-ends=2."""
    result = _bfs(
        nodes=[
            ("/", "https://shop/"),
            ("/a", "https://shop/a"),
            ("/b", "https://shop/b"),
        ],
        edges=[
            ("/", "/a", "https://shop/a"),
            ("/", "/b", "https://shop/b"),
        ],
        seeds=["/"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.node_count == 3
    assert metrics.edge_count == 2
    assert metrics.max_out_degree == 2
    assert metrics.dead_end_count == 2
    assert math.isclose(metrics.avg_out_degree, 2 / 3)


def test_compute_metrics_dead_end_excludes_self_loop() -> None:
    """A self-loop counts as one out-edge, so the node is not a dead end."""
    result = _bfs(
        nodes=[("/", "https://shop/")],
        edges=[("/", "/", "https://shop/")],
        seeds=["/"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.edge_count == 1
    assert metrics.dead_end_count == 0
    assert metrics.max_out_degree == 1


# ---------------------------------------------------------------------------
# compute_metrics — diameter
# ---------------------------------------------------------------------------


def test_compute_metrics_linear_diameter() -> None:
    """Linear chain ``/ → /a → /b → /c`` has diameter 3."""
    result = _bfs(
        nodes=[
            ("/", "https://shop/"),
            ("/a", "https://shop/a"),
            ("/b", "https://shop/b"),
            ("/c", "https://shop/c"),
        ],
        edges=[
            ("/", "/a", "https://shop/a"),
            ("/a", "/b", "https://shop/b"),
            ("/b", "/c", "https://shop/c"),
        ],
        seeds=["/"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.diameter == 3


def test_compute_metrics_cycle_diameter() -> None:
    """In a 3-cycle every node reaches every other; diameter = 2."""
    result = _bfs(
        nodes=[("/a", "https://shop/a"), ("/b", "https://shop/b"), ("/c", "https://shop/c")],
        edges=[
            ("/a", "/b", "https://shop/b"),
            ("/b", "/c", "https://shop/c"),
            ("/c", "/a", "https://shop/a"),
        ],
        seeds=["/a"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.diameter == 2


def test_compute_metrics_disconnected_diameter_is_finite_component_max() -> None:
    """Unreachable pairs are excluded; diameter is the max within reachable pairs."""
    result = _bfs(
        nodes=[
            ("/", "https://shop/"),
            ("/a", "https://shop/a"),
            ("/orphan", "https://shop/orphan"),
        ],
        edges=[("/", "/a", "https://shop/a")],
        seeds=["/"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.diameter == 1
    # The orphan is unreachable from `/`, so reachable_pct < 1.0.
    assert math.isclose(metrics.reachable_pct_from_homepage, 2 / 3)


def test_compute_metrics_fully_disconnected_diameter_is_none() -> None:
    """Two singletons with no edges have no ordered reachable pair."""
    result = _bfs(
        nodes=[("/a", "https://shop/a"), ("/b", "https://shop/b")],
        edges=[],
        seeds=["/a"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.diameter is None


# ---------------------------------------------------------------------------
# compute_metrics — reachable_pct_from_homepage
# ---------------------------------------------------------------------------


def test_compute_metrics_reachable_pct_includes_homepage() -> None:
    """Homepage counts toward the reachable set."""
    result = _bfs(
        nodes=[("/", "https://shop/"), ("/a", "https://shop/a")],
        edges=[("/", "/a", "https://shop/a")],
        seeds=["/"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.reachable_pct_from_homepage == 1.0


def test_compute_metrics_reachable_pct_zero_when_homepage_absent() -> None:
    """Custom homepage id missing from the node table → pct = 0.0."""
    result = _bfs(
        nodes=[("/a", "https://shop/a")],
        edges=[],
        seeds=["/a"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics(homepage_id="/")
    assert metrics.reachable_pct_from_homepage == 0.0
    assert metrics.homepage_to_cart_min_clicks is None


# ---------------------------------------------------------------------------
# compute_metrics — homepage_to_cart_min_clicks
# ---------------------------------------------------------------------------


def test_compute_metrics_homepage_to_cart_via_url() -> None:
    """``/cart`` reachable in 1 hop → ``homepage_to_cart_min_clicks == 1``."""
    result = _bfs(
        nodes=[("/", "https://shop/"), ("/cart", "https://shop/cart")],
        edges=[("/", "/cart", "https://shop/cart")],
        seeds=["/"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.homepage_to_cart_min_clicks == 1


def test_compute_metrics_homepage_to_cart_via_state_drawer() -> None:
    """A reachable cart_drawer state node satisfies the cart-min-clicks metric."""
    result = _bfs(nodes=[("/", "https://shop/")], edges=[], seeds=["/"])
    graph = TransitionGraph.from_bfs(result)
    graph.add_state_node(
        canonical_id="state:/:cart_drawer",
        representative_url="https://shop/",
        state_name=CART_DRAWER_STATE,
    )
    graph.add_edge(
        source="/",
        target="state:/:cart_drawer",
        label="click(header.cart_icon)",
    )
    metrics = graph.compute_metrics()
    assert metrics.homepage_to_cart_min_clicks == 1
    assert metrics.state_node_count == 1


def test_compute_metrics_homepage_to_cart_takes_min_of_url_and_drawer() -> None:
    """When both ``/cart`` and a cart_drawer are reachable, the minimum wins."""
    result = _bfs(
        nodes=[("/", "https://shop/"), ("/a", "https://shop/a"), ("/cart", "https://shop/cart")],
        edges=[
            ("/", "/a", "https://shop/a"),
            ("/a", "/cart", "https://shop/cart"),
        ],
        seeds=["/"],
    )
    graph = TransitionGraph.from_bfs(result)
    graph.add_state_node(
        canonical_id="state:/:cart_drawer",
        representative_url="https://shop/",
        state_name=CART_DRAWER_STATE,
    )
    graph.add_edge(
        source="/",
        target="state:/:cart_drawer",
        label="click(header.cart_icon)",
    )
    metrics = graph.compute_metrics()
    # Drawer is 1 hop, /cart is 2 hops → the minimum (drawer) wins.
    assert metrics.homepage_to_cart_min_clicks == 1


def test_compute_metrics_homepage_to_cart_none_when_unreachable() -> None:
    """Neither ``/cart`` nor a cart_drawer reachable → metric is None."""
    result = _bfs(
        nodes=[("/", "https://shop/"), ("/a", "https://shop/a")],
        edges=[("/", "/a", "https://shop/a")],
        seeds=["/"],
    )
    metrics = TransitionGraph.from_bfs(result).compute_metrics()
    assert metrics.homepage_to_cart_min_clicks is None


def test_compute_metrics_state_node_count_only_counts_state_kind() -> None:
    """``state_node_count`` ignores URL nodes."""
    result = _bfs(nodes=[("/", "https://shop/")], edges=[], seeds=["/"])
    graph = TransitionGraph.from_bfs(result)
    graph.add_state_node(
        canonical_id="state:a",
        representative_url="https://shop/",
        state_name="search_overlay",
    )
    graph.add_state_node(
        canonical_id="state:b",
        representative_url="https://shop/",
        state_name="cart_drawer",
    )
    metrics = graph.compute_metrics()
    assert metrics.state_node_count == 2
    assert metrics.node_count == 3


# ---------------------------------------------------------------------------
# write_graph_json
# ---------------------------------------------------------------------------


def test_write_graph_json_round_trips_to_dict(tmp_path: Path) -> None:
    """The on-disk JSON parses back to ``graph.to_dict()`` exactly."""
    import json as _json

    result = _bfs(
        nodes=[("/", "https://shop/"), ("/cart", "https://shop/cart")],
        edges=[("/", "/cart", "https://shop/cart")],
        seeds=["/"],
    )
    g = TransitionGraph.from_bfs(result)
    g.add_state_node(
        canonical_id="state:/:cart_drawer",
        representative_url="https://shop/",
        state_name=CART_DRAWER_STATE,
    )
    g.add_edge(
        source="/",
        target="state:/:cart_drawer",
        label="click(header.cart_icon)",
    )
    path = write_graph_json(g, tmp_path / "graph.json")
    assert path == tmp_path / "graph.json"
    assert _json.loads(path.read_text(encoding="utf-8")) == g.to_dict()


def test_write_graph_json_byte_stable(tmp_path: Path) -> None:
    """Repeated writes against the same graph produce byte-identical output."""
    result = _bfs(
        nodes=[("/", "https://shop/"), ("/a", "https://shop/a")],
        edges=[("/", "/a", "https://shop/a")],
        seeds=["/"],
    )
    g = TransitionGraph.from_bfs(result)
    a = write_graph_json(g, tmp_path / "a.json").read_bytes()
    b = write_graph_json(g, tmp_path / "b.json").read_bytes()
    assert a == b
    # Two-space indent + trailing newline so the file is human-readable diff-friendly.
    assert a.endswith(b"\n")
    assert b'"nodes": [' in a


def test_write_graph_json_empty_graph(tmp_path: Path) -> None:
    """An empty graph still serializes to a schema-shaped document."""
    import json as _json

    g = TransitionGraph()
    path = write_graph_json(g, tmp_path / "graph.json")
    parsed = _json.loads(path.read_text(encoding="utf-8"))
    assert parsed == {"nodes": [], "edges": [], "seeds": []}
