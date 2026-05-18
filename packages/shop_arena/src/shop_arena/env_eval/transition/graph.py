"""Transition graph dataclass + ``compute_metrics()`` (spec §5.5.3, M4).

The transition graph is the union of the structural BFS pass (§5.5.1)
and the stateful in-page rule pass (§5.5.2).  Both passes share a
single node table:

* **URL nodes** (``kind="url"``) come from the BFS — one per canonical
  id (template-collapsed host-relative path).
* **State nodes** (``kind="state"``) come from the stateful pass — one
  per (page, state-name) attempt that produced a structural diff.

This module centralises:

* :class:`GraphNode` / :class:`GraphEdge` — the shared node and edge
  records.
* :class:`TransitionGraph` — the mutable container the two passes
  populate, with helpers for adding state nodes/edges, an upgrade path
  from a :class:`~shop_arena.env_eval.transition.bfs.BfsResult`, a
  byte-stable JSON serializer for ``transition/graph.json``, and a pure
  :meth:`TransitionGraph.compute_metrics` that derives the closed
  :class:`~shop_arena.env_eval.schema.metrics.Transition` block.

The metric definitions follow spec §5.5.3 exactly:

* ``node_count`` = ``|V|`` (URL + state nodes).
* ``edge_count`` = ``|E|`` directed edges (no auto-dedup beyond what
  the producing passes already do).
* ``state_node_count`` = number of nodes with ``kind="state"``.
* ``avg_out_degree`` = mean out-degree across all nodes
  (``0.0`` when ``|V| == 0``).
* ``max_out_degree`` = maximum out-degree across all nodes
  (``0`` when ``|V| == 0``).
* ``dead_end_count`` = nodes with ``out_degree == 0``.
* ``diameter`` = longest shortest-path between two distinct reachable
  nodes (directed BFS distance); ``None`` when no such pair exists.
* ``reachable_pct_from_homepage`` = ``|reachable(homepage)| / |V|``
  including the homepage itself; ``0.0`` when ``|V| == 0`` or when
  the homepage id is absent from the node table.
* ``homepage_to_cart_min_clicks`` = shortest directed path length
  from the homepage to ``/cart`` (URL node) or any ``cart_drawer``
  state node — whichever is reachable in fewer hops; ``None`` when
  neither is reachable.

The implementation is pure Python (no networkx) and deliberately
straightforward: BFS for distances, dict-of-list adjacency, and a
single sweep for the per-node degree counts.  Graphs are bounded by
:data:`shop_arena.env_eval.transition.bfs.GLOBAL_CAP` (64 URL nodes)
plus a handful of state nodes, so an O(V*(V+E)) all-pairs BFS is
trivially fine.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from shop_arena.env_eval.schema.metrics import Transition
from shop_arena.env_eval.transition.bfs import BfsEdge, BfsNode, BfsResult

__all__ = [
    "CART_DRAWER_STATE",
    "CART_URL_ID",
    "DEFAULT_HOMEPAGE_ID",
    "GraphEdge",
    "GraphNode",
    "NodeKind",
    "TransitionGraph",
    "write_graph_json",
]

#: Canonical id of the homepage URL node (spec §5.2: hostname root → ``"/"``).
DEFAULT_HOMEPAGE_ID: Final[str] = "/"

#: Canonical id of the ``/cart`` URL node used by
#: ``homepage_to_cart_min_clicks`` (spec §5.5.3).
CART_URL_ID: Final[str] = "/cart"

#: ``state_name`` value the stateful pass assigns to cart-drawer
#: transitions (spec §5.5.2 closed enum).  Recognised by
#: ``homepage_to_cart_min_clicks`` so a JS cart drawer counts as
#: "cart reached" even when ``/cart`` is unreachable.
CART_DRAWER_STATE: Final[str] = "cart_drawer"

#: Closed discriminator for :class:`GraphNode.kind`.  ``"url"`` nodes
#: come from the structural BFS (M4); ``"state"`` nodes come from the
#: stateful pass (M5).
NodeKind = Literal["url", "state"]


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One node in the combined transition graph.

    Attributes:
        canonical_id: Primary key.  For URL nodes, the template-collapsed
            host-relative path (``"/"``, ``"/products/<*>"``).  For state
            nodes, an opaque id assigned by the stateful pass — typically
            ``"state:<page_id>:<state_name>"`` but the graph treats it as
            a black box.
        representative_url: Concrete URL associated with the node.  For
            URL nodes, the first concrete in-domain URL seen by the BFS
            (spec §5.5.1 step 3).  For state nodes, the URL of the page
            on which the stateful rule fired.
        kind: ``"url"`` for structural BFS nodes; ``"state"`` for nodes
            produced by the M5 stateful pass.
        state_name: Closed-enum state name for ``kind="state"`` nodes
            (e.g. ``"cart_drawer"``); ``None`` for ``"url"`` nodes.
    """

    canonical_id: str
    representative_url: str
    kind: NodeKind = "url"
    state_name: str | None = None


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One directed edge in the combined transition graph.

    Attributes:
        source: Canonical id of the source node.
        target: Canonical id of the target node.
        label: Spec-shaped edge label (e.g. ``"click(<href>)"`` for the
            structural pass, ``"click(add_to_cart)"`` for stateful).
        action: Closed action kind.  Always ``"click"`` for the
            structural pass; the stateful pass also emits ``"fill"``
            (spec §5.5.2 rule table).
    """

    source: str
    target: str
    label: str
    action: str = "click"


@dataclass
class TransitionGraph:
    """Mutable container for the combined structural + stateful graph.

    Both passes append into ``nodes`` and ``edges``; ``seeds`` records
    the canonical ids of the BFS seeds (in input order) so consumers
    can identify the homepage even when the spec's default
    :data:`DEFAULT_HOMEPAGE_ID` is overridden.

    Attributes:
        nodes: Insertion-ordered ``{canonical_id: GraphNode}``.  The
            BFS pass guarantees insertion order = discovery order; the
            stateful pass appends after all URL nodes.
        edges: Edges in discovery order.  No auto-dedup happens here —
            the BFS already dedupes ``(source, target)`` pairs and the
            stateful pass emits one edge per attempted rule.
        seeds: Canonical ids of the BFS seeds, in input order.  Empty
            for a freshly-constructed graph; populated by
            :meth:`from_bfs`.
    """

    nodes: dict[str, GraphNode] = field(default_factory=dict[str, GraphNode])
    edges: list[GraphEdge] = field(default_factory=list[GraphEdge])
    seeds: list[str] = field(default_factory=list[str])

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_bfs(cls, result: BfsResult) -> TransitionGraph:
        """Build a graph from a structural BFS result.

        The stateful pass extends the returned graph in place by
        calling :meth:`add_state_node` and :meth:`add_edge`.

        Args:
            result: Output of
                :func:`shop_arena.env_eval.transition.bfs.run_bfs`.

        Returns:
            A populated :class:`TransitionGraph` with ``kind="url"``
            nodes for every entry in ``result.nodes`` and one edge
            per entry in ``result.edges``.
        """
        graph = cls()
        for node in result.nodes.values():
            graph._add_url_node(node)
        for edge in result.edges:
            graph._add_bfs_edge(edge)
        graph.seeds = list(result.seeds)
        return graph

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TransitionGraph:
        """Reconstruct a graph from a :meth:`to_dict` payload.

        Inverse of :meth:`to_dict` — used by
        :func:`shop_arena.env_eval.pipeline.evaluate` to reuse a previously
        written ``transition/graph.json`` without re-running the BFS pass.
        Insertion order of ``nodes`` and ``edges`` is preserved so
        downstream metrics stay byte-stable.

        Args:
            payload: Dict shaped like :meth:`to_dict`'s return value
                (``{"nodes": [...], "edges": [...], "seeds": [...]}``).

        Returns:
            A :class:`TransitionGraph` populated with the same nodes,
            edges, and seeds as ``payload``.

        Raises:
            KeyError: ``payload`` is missing one of the required top-level
                keys, or a node/edge entry is missing a required field.
            ValueError: ``payload`` contains an edge whose ``source`` or
                ``target`` is not in the node table, or a node with an
                unknown ``kind``.
        """
        graph = cls()
        for raw in payload["nodes"]:
            kind = raw["kind"]
            if kind not in ("url", "state"):
                raise ValueError(f"unknown node kind: {kind!r}")
            node = GraphNode(
                canonical_id=raw["canonical_id"],
                representative_url=raw["representative_url"],
                kind=kind,
                state_name=raw.get("state_name"),
            )
            graph.nodes[node.canonical_id] = node
        for raw in payload["edges"]:
            source = raw["source"]
            target = raw["target"]
            if source not in graph.nodes:
                raise ValueError(f"edge source {source!r} is not in the node table")
            if target not in graph.nodes:
                raise ValueError(f"edge target {target!r} is not in the node table")
            graph.edges.append(
                GraphEdge(
                    source=source,
                    target=target,
                    label=raw["label"],
                    action=raw.get("action", "click"),
                ),
            )
        graph.seeds = list(payload.get("seeds", []))
        return graph

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def add_state_node(
        self,
        *,
        canonical_id: str,
        representative_url: str,
        state_name: str,
    ) -> GraphNode:
        """Insert a state node and return it.

        Idempotent: re-adding a state node with the same ``canonical_id``
        returns the existing entry without overwriting it (so the
        first-seen ``representative_url`` and ``state_name`` win,
        matching the BFS first-concrete-URL rule).

        Args:
            canonical_id: Opaque state-node id assigned by the stateful
                pass.  Must not collide with a URL node id.
            representative_url: URL of the page on which the rule fired.
            state_name: Closed-enum state name (spec §5.5.2).

        Returns:
            The :class:`GraphNode` stored at ``canonical_id``.

        Raises:
            ValueError: ``canonical_id`` already maps to a URL node.
        """
        existing = self.nodes.get(canonical_id)
        if existing is not None:
            if existing.kind != "state":
                raise ValueError(
                    f"canonical_id {canonical_id!r} already exists as a {existing.kind!r} node",
                )
            return existing
        node = GraphNode(
            canonical_id=canonical_id,
            representative_url=representative_url,
            kind="state",
            state_name=state_name,
        )
        self.nodes[canonical_id] = node
        return node

    def add_edge(
        self,
        *,
        source: str,
        target: str,
        label: str,
        action: str = "click",
    ) -> GraphEdge:
        """Append an edge.  Both endpoints must already be nodes.

        Args:
            source: Canonical id of the source node.
            target: Canonical id of the target node.
            label: Spec-shaped edge label.
            action: Closed action kind.

        Returns:
            The appended :class:`GraphEdge`.

        Raises:
            KeyError: ``source`` or ``target`` is not in :attr:`nodes`.
        """
        if source not in self.nodes:
            raise KeyError(f"edge source {source!r} is not in the node table")
        if target not in self.nodes:
            raise KeyError(f"edge target {target!r} is not in the node table")
        edge = GraphEdge(source=source, target=target, label=label, action=action)
        self.edges.append(edge)
        return edge

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a byte-stable, schema-friendly view of the graph.

        Used by the M4 ``transition/graph.json`` writer.  The shape is:

        ```
        {
          "nodes": [{"canonical_id": ..., "representative_url": ...,
                     "kind": "url"|"state", "state_name": str | null}, ...],
          "edges": [{"source": ..., "target": ..., "label": ...,
                     "action": ...}, ...],
          "seeds": [canonical_id, ...]
        }
        ```

        Insertion order is preserved for both nodes and edges so
        repeated runs against a fixed input produce byte-identical
        output.
        """
        return {
            "nodes": [
                {
                    "canonical_id": node.canonical_id,
                    "representative_url": node.representative_url,
                    "kind": node.kind,
                    "state_name": node.state_name,
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "label": edge.label,
                    "action": edge.action,
                }
                for edge in self.edges
            ],
            "seeds": list(self.seeds),
        }

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        *,
        homepage_id: str = DEFAULT_HOMEPAGE_ID,
    ) -> Transition:
        """Return the closed :class:`Transition` metrics for this graph.

        Args:
            homepage_id: Canonical id of the homepage URL node.
                Defaults to :data:`DEFAULT_HOMEPAGE_ID` (``"/"``).
                When the id is absent from :attr:`nodes`,
                ``reachable_pct_from_homepage`` is ``0.0`` and
                ``homepage_to_cart_min_clicks`` is ``None``.

        Returns:
            A frozen, schema-valid :class:`Transition` document.
        """
        adjacency = self._build_adjacency()
        node_count = len(self.nodes)
        edge_count = len(self.edges)
        state_node_count = sum(1 for node in self.nodes.values() if node.kind == "state")

        out_degrees = [len(adjacency[nid]) for nid in self.nodes]
        if out_degrees:
            avg_out_degree = sum(out_degrees) / len(out_degrees)
            max_out_degree = max(out_degrees)
            dead_end_count = sum(1 for d in out_degrees if d == 0)
        else:
            avg_out_degree = 0.0
            max_out_degree = 0
            dead_end_count = 0

        diameter = self._diameter(adjacency)
        reachable_pct = self._reachable_pct(adjacency, homepage_id)
        homepage_to_cart = self._homepage_to_cart(adjacency, homepage_id)

        return Transition(
            node_count=node_count,
            edge_count=edge_count,
            state_node_count=state_node_count,
            avg_out_degree=avg_out_degree,
            max_out_degree=max_out_degree,
            dead_end_count=dead_end_count,
            diameter=diameter,
            reachable_pct_from_homepage=reachable_pct,
            homepage_to_cart_min_clicks=homepage_to_cart,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _add_url_node(self, node: BfsNode) -> None:
        """Insert a URL node from the BFS pass (no overwrite)."""
        if node.canonical_id in self.nodes:
            return
        self.nodes[node.canonical_id] = GraphNode(
            canonical_id=node.canonical_id,
            representative_url=node.representative_url,
            kind="url",
        )

    def _add_bfs_edge(self, edge: BfsEdge) -> None:
        """Insert an edge from the BFS pass (no node-existence check).

        The BFS guarantees both endpoints are present in
        :attr:`nodes` because :meth:`from_bfs` inserts the full node
        table first.
        """
        self.edges.append(
            GraphEdge(
                source=edge.source,
                target=edge.target,
                label=edge.label,
                action=edge.action,
            ),
        )

    def _build_adjacency(self) -> dict[str, list[str]]:
        """Return a ``{node_id: [target_id, ...]}`` adjacency map.

        Self-loops and parallel edges are preserved — the BFS does
        not produce them, but the stateful pass may emit a self-loop
        (e.g. ``cart_qty_changed`` on the cart page).  Counting them
        in out-degree is correct: each represents a distinct action
        target an agent can take from that node.
        """
        adjacency: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for edge in self.edges:
            # Defensive: a malformed graph (caller used the dataclass
            # constructors directly without going through ``add_edge``)
            # is silently ignored rather than crashing the metrics pass.
            if edge.source in adjacency:
                adjacency[edge.source].append(edge.target)
        return adjacency

    def _bfs_distances(
        self,
        adjacency: dict[str, list[str]],
        source: str,
    ) -> dict[str, int]:
        """Single-source BFS distances over the directed graph.

        Returns ``{node_id: hops}`` for every node reachable from
        ``source`` (including ``source`` itself at distance ``0``).
        Unreachable nodes are absent from the map.
        """
        distances: dict[str, int] = {source: 0}
        queue: deque[str] = deque([source])
        while queue:
            current = queue.popleft()
            depth = distances[current]
            for neighbour in adjacency.get(current, ()):
                if neighbour in distances:
                    continue
                distances[neighbour] = depth + 1
                queue.append(neighbour)
        return distances

    def _diameter(self, adjacency: dict[str, list[str]]) -> int | None:
        """Return the directed diameter, or ``None`` when undefined.

        Defined here as the maximum finite shortest-path length over
        all ordered pairs ``(u, v)`` with ``u != v`` and ``v``
        reachable from ``u``.  Returns ``None`` if no such pair
        exists (graph has 0 or 1 nodes, or is fully disconnected).
        """
        best: int = 0
        seen_pair: bool = False
        for source in self.nodes:
            distances = self._bfs_distances(adjacency, source)
            for target, hops in distances.items():
                if target == source:
                    continue
                seen_pair = True
                best = max(best, hops)
        return best if seen_pair else None

    def _reachable_pct(
        self,
        adjacency: dict[str, list[str]],
        homepage_id: str,
    ) -> float:
        """Return ``|reachable(homepage)| / |V|`` in ``[0.0, 1.0]``."""
        if not self.nodes:
            return 0.0
        if homepage_id not in self.nodes:
            return 0.0
        reachable = self._bfs_distances(adjacency, homepage_id)
        return len(reachable) / len(self.nodes)

    def _homepage_to_cart(
        self,
        adjacency: dict[str, list[str]],
        homepage_id: str,
    ) -> int | None:
        """Return the shortest directed path from homepage → cart.

        Considers two reachable targets:

        * the ``/cart`` URL node (:data:`CART_URL_ID`), and
        * any state node with ``state_name == "cart_drawer"``
          (:data:`CART_DRAWER_STATE`).

        Returns the smaller distance when either is reachable, else
        ``None``.
        """
        if homepage_id not in self.nodes:
            return None
        distances = self._bfs_distances(adjacency, homepage_id)
        candidates: list[int] = []
        cart_hops = distances.get(CART_URL_ID)
        if cart_hops is not None:
            candidates.append(cart_hops)
        for nid, node in self.nodes.items():
            if node.kind == "state" and node.state_name == CART_DRAWER_STATE:
                hops = distances.get(nid)
                if hops is not None:
                    candidates.append(hops)
        if not candidates:
            return None
        return min(candidates)


def write_graph_json(graph: TransitionGraph, path: Path | str) -> Path:
    """Serialize ``graph`` to ``transition/graph.json`` (spec §5.6, M4).

    Writes deterministic JSON (two-space indent, trailing newline) so
    repeated runs against a fixed input produce byte-identical output
    for cohort comparison.  The on-disk shape is the dict returned by
    :meth:`TransitionGraph.to_dict` — see that method's docstring for
    the schema.

    Args:
        graph: Combined URL + state graph to serialize.
        path: Destination path (parent directories must exist).

    Returns:
        The resolved :class:`pathlib.Path` written to disk.
    """
    p = Path(path)
    p.write_text(json.dumps(graph.to_dict(), indent=2) + "\n", encoding="utf-8")
    return p
