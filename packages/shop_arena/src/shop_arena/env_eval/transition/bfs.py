"""Structural href BFS for the transition graph (spec §5.5.1, M4).

Walks each measurable sample URL as a seed, follows in-domain ``<a href>``
links breadth-first, and produces:

* a node table keyed by canonical id (template-collapsed host-relative
  path), each carrying the concrete URL selected for that page class,
* a deduped list of edges between canonical ids — one edge per
  ``(source, target)`` pair, labelled ``click(<href>)`` where ``<href>``
  is the first concrete in-domain URL that produced it,
* one :class:`BfsAttempt` per visit attempt for ``trace.jsonl``.

Href targets are canonicalized before enqueueing, then normalized again
after browser navigation. If a request redirects to a different same-domain
canonical id, the tentative node is merged into the final node and existing
edges are rewired. This makes the graph represent the actual post-click
state while preserving the original href in the edge label.

The BFS is bounded by ``max_hops`` (per-node depth from the nearest seed)
and a global cap of :data:`GLOBAL_CAP` navigations (spec §5.5). The
multi-source formulation — seeds are all enqueued at depth 0 and share
one ``visited`` set — matches "BFS from each measurable sample URL as a
seed" while keeping cost predictable: each resolved canonical id is
scanned at most once, regardless of how many seeds reach it.

This pass is fully deterministic: it issues no LLM calls and depends
only on browser navigation + DOM-link extraction. The stateful pass
(M5) extends the same node/edge tables with state nodes.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol
from urllib.parse import urljoin, urlsplit

from shop_arena.env_eval.transition.canonicalize import (
    PAGES_PREFIX,
    CanonicalLink,
    canonicalize_href,
    is_in_domain,
)

__all__ = [
    "BFS_PHASE",
    "GLOBAL_CAP",
    "HTTP_ERROR_FLOOR",
    "BfsAttempt",
    "BfsBrowser",
    "BfsEdge",
    "BfsNode",
    "BfsResult",
    "BfsSeed",
    "PagesClassifyFn",
    "VisitOutcome",
    "extract_pages_slug",
    "run_bfs",
    "write_trace_jsonl",
]

#: Callback the BFS uses to lazily classify newly-discovered ``/pages/<slug>``
#: paths. Receives the post-``/pages/`` slugs (trailing slash stripped) that
#: the BFS has not classified yet, in insertion order with duplicates removed.
#: Returns the cumulative collapse set the BFS should use from this point
#: forward — i.e. every slug ever decided as collapse-eligible across the run,
#: not just the freshly classified ones.  The callback owns batching,
#: persistence, and any caching; the BFS only stores the returned frozenset
#: and threads it through subsequent ``canonicalize_href`` calls.
PagesClassifyFn = Callable[[Sequence[str]], frozenset[str]]

#: Hard ceiling on navigation attempts across all seeds (spec §5.5).
#:
#: Caps cost on dense storefronts where ``max_hops=3`` would otherwise
#: enumerate hundreds of product pages.  The cap counts navigation attempts
#: that issue ``goto()``; pre-visit deduplication and known redirect aliases
#: do not consume the budget.
GLOBAL_CAP: Final[int] = 64

#: HTTP status floor that BFS treats as a navigation failure.
#:
#: Mirrors :data:`shop_arena.env_eval.pages._HTTP_ERROR_FLOOR` so the two
#: layers agree on what "bucket unavailable" means.  Pages 4xx/5xx are
#: marked visited (so other seeds do not retry them) and their outgoing
#: links are not enqueued.
HTTP_ERROR_FLOOR: Final[int] = 400

#: Closed enum of per-attempt outcomes recorded in ``trace.jsonl``.
#:
#: * ``"ok"`` — navigation returned a 2xx (or unknown) status; links
#:   were scanned and queued.
#: * ``"http_error"`` — navigation returned a 4xx/5xx; the page is still
#:   added to the visited set so subsequent seeds do not re-attempt it,
#:   but its links are not enqueued.
#: * ``"nav_error"`` — navigation raised (timeout, network failure);
#:   treated like ``"http_error"`` for visited-set bookkeeping.
#: * ``"skipped_visited"`` — popped from the queue but already visited
#:   from another seed or another path.
#: * ``"skipped_cap"`` — popped from the queue when the global cap was
#:   already hit; not navigated to.
VisitOutcome = Literal[
    "ok",
    "http_error",
    "nav_error",
    "skipped_visited",
    "skipped_cap",
]


class BfsBrowser(Protocol):
    """Minimal browser surface :func:`run_bfs` consumes.

    Mirrors the methods :class:`shop_arena.env_eval.pages.DiscoveryBrowser`
    already exposes so production code can wrap a single
    :class:`~shop_arena.env_eval.env.EnvEvalSession` once and pass it to
    both layers; tests inject a deterministic fake.
    """

    def goto(self, url: str) -> int | None:
        """Navigate to ``url`` and return the HTTP status (or ``None``)."""
        ...

    def current_url(self) -> str:
        """Return the browser's current URL after the latest navigation."""
        ...

    def hrefs(self, selector: str = "a[href]") -> list[str]:
        """Return absolute hrefs for ``selector`` matches in DOM order."""
        ...


@dataclass(frozen=True, slots=True)
class BfsSeed:
    """One BFS starting point.

    Attributes:
        canonical_id: Template-collapsed host-relative path used as the
            graph node key (e.g. ``"/"``, ``"/products/<*>"``).
        representative_url: Concrete in-domain URL ``run_bfs`` will
            ``goto()``.  Spec §5.5.1 step 3: BFS enqueues representative
            URLs, never placeholder templates like ``/products/<*>``.
    """

    canonical_id: str
    representative_url: str


@dataclass(frozen=True, slots=True)
class BfsNode:
    """One graph node discovered by the structural BFS.

    Attributes:
        canonical_id: Template-collapsed host-relative path; primary key.
        representative_url: Concrete in-domain URL selected for this
            canonical id. Href discovery supplies the initial value; redirect
            normalization may replace a tentative alias with its final URL.
        kind: Always ``"url"`` for nodes produced by the structural pass.
            The stateful pass (M5) will extend the graph with
            ``"state"`` nodes; declaring the discriminator now keeps the
            JSON schema stable.
    """

    canonical_id: str
    representative_url: str
    kind: Literal["url"] = "url"


@dataclass(frozen=True, slots=True)
class BfsEdge:
    """One directed edge between canonical ids.

    Attributes:
        source: Canonical id of the page where the link was scanned.
        target: Canonical id of the page the link points to.
        href: The first concrete (query-stripped, in-domain) URL that
            produced this edge.  Used to render the spec §5.5.1 edge
            label ``click(<href>)`` and as a debugging hint.
        action: Closed action kind — always ``"click"`` for hrefs in
            the structural pass.
    """

    source: str
    target: str
    href: str
    action: Literal["click"] = "click"

    @property
    def label(self) -> str:
        """Return the spec-shaped edge label ``click(<href>)``."""
        return f"{self.action}({self.href})"


@dataclass(frozen=True, slots=True)
class BfsAttempt:
    """One visit attempt for ``trace.jsonl`` (spec §5.6).

    Attributes:
        canonical_id: Node id at the front of the queue before any redirect
            normalization for this attempt.
        url: ``representative_url`` requested by ``browser.goto``. Recorded
            even on ``"skipped_*"`` outcomes for trace completeness.
        depth: BFS depth — ``0`` for seeds, ``1`` for direct neighbours
            of any seed, etc.
        status: HTTP status returned by ``browser.goto`` when known,
            else ``None`` (same-document nav, or skipped).
        outcome: One of :data:`VisitOutcome`.
        final_url: Query/fragment-stripped browser URL after redirect
            normalization; ``None`` for non-redirect and skipped attempts.
        resolved_canonical_id: Final same-domain canonical id after redirect
            normalization when it differs from ``canonical_id``.
    """

    canonical_id: str
    url: str
    depth: int
    status: int | None
    outcome: VisitOutcome
    final_url: str | None = None
    resolved_canonical_id: str | None = None


@dataclass(frozen=True, slots=True)
class BfsResult:
    """Aggregate output of :func:`run_bfs`.

    Attributes:
        nodes: Insertion-ordered ``{canonical_id: BfsNode}``.  Insertion
            order = discovery order, which is byte-stable for fixed
            input.
        edges: Deduped edges in discovery order.  At most one edge per
            ``(source, target)`` pair (spec §5.5.1 step 4).
        seeds: Canonical ids of the seeds, in input order.  Useful for
            metrics that key off "reachable from homepage" etc.
        attempts: One :class:`BfsAttempt` per popped queue entry (one
            line per ``trace.jsonl`` row).
    """

    nodes: dict[str, BfsNode]
    edges: list[BfsEdge]
    seeds: list[str]
    attempts: list[BfsAttempt]


def run_bfs(
    browser: BfsBrowser,
    base_url: str,
    seeds: list[BfsSeed],
    *,
    max_hops: int,
    global_cap: int = GLOBAL_CAP,
    classify_pages: PagesClassifyFn | None = None,
) -> BfsResult:
    """Run the structural href BFS from ``seeds`` and return the graph.

    Implementation is a multi-source BFS: every seed is enqueued at
    depth ``0`` and a single ``visited`` set is shared across seeds. Href
    targets are tentative until navigation completes; when the browser's
    final same-domain URL canonicalizes differently, the tentative node is
    aliased into the final node before outgoing links are scanned.

    The cap on navigations (``global_cap``) is enforced *before* issuing
    ``goto()``: when the cap is already hit, the popped entry is recorded
    with outcome ``"skipped_cap"`` and the loop continues so subsequent
    queue entries also get a trace row.

    When ``classify_pages`` is provided, the BFS calls it once per scanned
    page that exposes previously-unseen in-domain ``/pages/<slug>`` hrefs,
    forwarding the new slugs and replacing its current ``collapse_pages``
    set with whatever the callback returns. The updated set is then threaded
    into every :func:`canonicalize_href` call. When the callback is ``None``
    the BFS never collapses ``/pages/`` (the safe identity behavior).

    Args:
        browser: Live browser surface used to navigate + scan links.
        base_url: Absolute storefront base URL (scheme + host + ``/``).
            Drives relative-href resolution and same-host filtering via
            :func:`canonicalize_href`.
        seeds: BFS starting points in insertion order. Duplicates by
            canonical id are tolerated — only the first occurrence
            seeds a node and gets enqueued.
        max_hops: Maximum BFS depth from any seed (inclusive).
            ``max_hops=0`` visits only the seeds; ``max_hops=3`` visits
            seeds + 3 levels of out-edges.
        global_cap: Hard ceiling on navigation attempts across all seeds.
            Defaults to :data:`GLOBAL_CAP`.
        classify_pages: Optional callback that classifies newly-discovered
            ``/pages/<slug>`` paths and returns the cumulative collapse set
            the BFS should use going forward. ``None`` (default) preserves
            the legacy behavior where ``/pages/`` is never collapsed.
            Errors raised by the callback propagate to the caller — the
            BFS does not silently fall back.

    Returns:
        :class:`BfsResult` with the discovered nodes, edges, and the
        per-attempt trace.
    """
    nodes, seed_ids, queue = _initial_frontier(seeds)
    edges: list[BfsEdge] = []
    edge_keys: set[tuple[str, str]] = set()
    attempts: list[BfsAttempt] = []
    visited: set[str] = set()
    aliases: dict[str, str] = {}
    collapse_pages: frozenset[str] = frozenset()
    seen_pages_slugs: set[str] = set()
    navigation_count = 0

    while queue:
        queued_id, depth = queue.popleft()
        canonical_id = _resolve_alias(queued_id, aliases)
        node = nodes.get(canonical_id)
        if node is None:
            continue
        if canonical_id in visited:
            attempts.append(
                BfsAttempt(
                    canonical_id=canonical_id,
                    url=node.representative_url,
                    depth=depth,
                    status=None,
                    outcome="skipped_visited",
                ),
            )
            continue
        if navigation_count >= global_cap:
            attempts.append(
                BfsAttempt(
                    canonical_id=canonical_id,
                    url=node.representative_url,
                    depth=depth,
                    status=None,
                    outcome="skipped_cap",
                ),
            )
            continue

        requested_url = node.representative_url
        navigation_count += 1
        try:
            status = browser.goto(requested_url)
        except Exception:
            visited.add(canonical_id)
            attempts.append(
                BfsAttempt(
                    canonical_id=canonical_id,
                    url=requested_url,
                    depth=depth,
                    status=None,
                    outcome="nav_error",
                ),
            )
            continue
        if status is not None and status >= HTTP_ERROR_FLOOR:
            visited.add(canonical_id)
            attempts.append(
                BfsAttempt(
                    canonical_id=canonical_id,
                    url=requested_url,
                    depth=depth,
                    status=status,
                    outcome="http_error",
                ),
            )
            continue

        final_link = canonicalize_href(
            browser.current_url(),
            base_url,
            collapse_pages=collapse_pages,
        )
        resolved_id = canonical_id
        if final_link is not None:
            resolved_id = _merge_redirect_alias(
                old_id=canonical_id,
                final_link=final_link,
                nodes=nodes,
                edges=edges,
                edge_keys=edge_keys,
                aliases=aliases,
                seed_ids=seed_ids,
            )
        resolved_was_visited = resolved_id in visited
        visited.add(resolved_id)

        final_url = _trace_final_url(requested_url, final_link, canonical_id, resolved_id)
        resolved_canonical_id = _trace_resolved_canonical_id(
            canonical_id,
            resolved_id,
        )
        attempts.append(
            BfsAttempt(
                canonical_id=canonical_id,
                url=requested_url,
                depth=depth,
                status=status,
                outcome="ok",
                final_url=final_url,
                resolved_canonical_id=resolved_canonical_id,
            ),
        )

        if final_link is None or resolved_was_visited:
            continue
        collapse_pages = _scan_links(
            browser=browser,
            base_url=base_url,
            source_id=resolved_id,
            depth=depth,
            max_hops=max_hops,
            nodes=nodes,
            edges=edges,
            edge_keys=edge_keys,
            visited=visited,
            aliases=aliases,
            queue=queue,
            collapse_pages=collapse_pages,
            seen_pages_slugs=seen_pages_slugs,
            classify_pages=classify_pages,
        )

    return BfsResult(
        nodes=nodes,
        edges=edges,
        seeds=seed_ids,
        attempts=attempts,
    )


def _initial_frontier(
    seeds: list[BfsSeed],
) -> tuple[dict[str, BfsNode], list[str], deque[tuple[str, int]]]:
    """Return initial nodes, seed ids, and BFS queue for ``seeds``."""
    nodes: dict[str, BfsNode] = {}
    seed_ids: list[str] = []
    queue: deque[tuple[str, int]] = deque()
    for seed in seeds:
        if seed.canonical_id not in nodes:
            nodes[seed.canonical_id] = BfsNode(
                canonical_id=seed.canonical_id,
                representative_url=seed.representative_url,
            )
            queue.append((seed.canonical_id, 0))
        if seed.canonical_id not in seed_ids:
            seed_ids.append(seed.canonical_id)
    return nodes, seed_ids, queue


def _trace_final_url(
    requested_url: str,
    final_link: CanonicalLink | None,
    canonical_id: str,
    resolved_id: str,
) -> str | None:
    """Return trace final URL metadata for a redirect-normalized attempt."""
    if final_link is None or resolved_id == canonical_id:
        return None
    if final_link.representative_url == requested_url:
        return None
    return final_link.representative_url


def _trace_resolved_canonical_id(canonical_id: str, resolved_id: str) -> str | None:
    """Return trace canonical-id metadata for a completed navigation."""
    if resolved_id == canonical_id:
        return None
    return resolved_id


def _resolve_alias(canonical_id: str, aliases: dict[str, str]) -> str:
    """Return the final canonical id for ``canonical_id``."""
    seen: set[str] = set()
    current = canonical_id
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def _merge_redirect_alias(
    *,
    old_id: str,
    final_link: CanonicalLink,
    nodes: dict[str, BfsNode],
    edges: list[BfsEdge],
    edge_keys: set[tuple[str, str]],
    aliases: dict[str, str],
    seed_ids: list[str],
) -> str:
    """Merge ``old_id`` into the same-domain canonical id in ``final_link``."""
    final_id = _resolve_alias(final_link.canonical_id, aliases)
    if final_id == old_id:
        return old_id

    aliases[old_id] = final_id
    for alias, target in list(aliases.items()):
        if target == old_id:
            aliases[alias] = final_id

    if final_id in nodes:
        nodes.pop(old_id, None)
    elif old_id in nodes:
        _replace_node_key(
            nodes=nodes,
            old_id=old_id,
            new_id=final_id,
            representative_url=final_link.representative_url,
        )
    else:
        nodes[final_id] = BfsNode(
            canonical_id=final_id,
            representative_url=final_link.representative_url,
        )

    _replace_seed_id(seed_ids, old_id, final_id)
    _rewrite_edges_for_alias(edges=edges, edge_keys=edge_keys, aliases=aliases)
    return final_id


def _replace_node_key(
    *,
    nodes: dict[str, BfsNode],
    old_id: str,
    new_id: str,
    representative_url: str,
) -> None:
    """Replace a node key while preserving insertion order."""
    replacement = BfsNode(canonical_id=new_id, representative_url=representative_url)
    items: list[tuple[str, BfsNode]] = []
    replaced = False
    for key, node in nodes.items():
        if key == old_id:
            items.append((new_id, replacement))
            replaced = True
        else:
            items.append((key, node))
    if not replaced:
        items.append((new_id, replacement))
    nodes.clear()
    nodes.update(items)


def _replace_seed_id(seed_ids: list[str], old_id: str, new_id: str) -> None:
    """Replace seed ids in place, preserving first occurrence order."""
    seen: set[str] = set()
    replaced: list[str] = []
    for seed_id in seed_ids:
        candidate = new_id if seed_id == old_id else seed_id
        if candidate in seen:
            continue
        seen.add(candidate)
        replaced.append(candidate)
    seed_ids[:] = replaced


def _rewrite_edges_for_alias(
    *,
    edges: list[BfsEdge],
    edge_keys: set[tuple[str, str]],
    aliases: dict[str, str],
) -> None:
    """Rewrite existing edges through ``aliases`` and dedupe by pair."""
    rewritten: list[BfsEdge] = []
    rewritten_keys: set[tuple[str, str]] = set()
    for edge in edges:
        source = _resolve_alias(edge.source, aliases)
        target = _resolve_alias(edge.target, aliases)
        edge_key = (source, target)
        if edge_key in rewritten_keys:
            continue
        rewritten_keys.add(edge_key)
        if source == edge.source and target == edge.target:
            rewritten.append(edge)
        else:
            rewritten.append(
                BfsEdge(
                    source=source,
                    target=target,
                    href=edge.href,
                    action=edge.action,
                ),
            )
    edges[:] = rewritten
    edge_keys.clear()
    edge_keys.update(rewritten_keys)


def _scan_links(
    *,
    browser: BfsBrowser,
    base_url: str,
    source_id: str,
    depth: int,
    max_hops: int,
    nodes: dict[str, BfsNode],
    edges: list[BfsEdge],
    edge_keys: set[tuple[str, str]],
    visited: set[str],
    aliases: dict[str, str],
    queue: deque[tuple[str, int]],
    collapse_pages: frozenset[str],
    seen_pages_slugs: set[str],
    classify_pages: PagesClassifyFn | None,
) -> frozenset[str]:
    """Add nodes/edges for every in-domain link on the active page.

    Edges are emitted even at the ``depth == max_hops`` boundary so the
    out-degree metric is accurate; queue insertion is gated on
    ``depth < max_hops`` instead.  Extracted from :func:`run_bfs` to keep
    the main loop's branch count under the ruff ``PLR0912`` ceiling.

    Performs a single pre-pass over the scraped hrefs to discover any new
    in-domain ``/pages/<slug>`` slugs and — when ``classify_pages`` is
    provided — invokes the callback once per scan to refresh
    ``collapse_pages``. The freshly returned set is used for every
    canonicalize call in the same scan so a slug discovered on this page
    can collapse on the same page.

    Returns the (possibly updated) ``collapse_pages`` so the caller can
    keep using it on subsequent iterations.
    """
    raw_hrefs = list(browser.hrefs())
    new_slugs: list[str] = []
    seen_in_scan: set[str] = set()
    for raw_href in raw_hrefs:
        slug = extract_pages_slug(raw_href, base_url)
        if slug is None or slug in seen_pages_slugs or slug in seen_in_scan:
            continue
        seen_in_scan.add(slug)
        new_slugs.append(slug)
    if new_slugs:
        if classify_pages is not None:
            collapse_pages = classify_pages(new_slugs)
        seen_pages_slugs.update(new_slugs)

    for raw_href in raw_hrefs:
        link = canonicalize_href(raw_href, base_url, collapse_pages=collapse_pages)
        if link is None:
            continue
        target_id = _resolve_alias(link.canonical_id, aliases)
        if target_id not in nodes:
            nodes[target_id] = BfsNode(
                canonical_id=target_id,
                representative_url=link.representative_url,
            )
        edge_key = (source_id, target_id)
        if edge_key not in edge_keys:
            edge_keys.add(edge_key)
            edges.append(
                BfsEdge(
                    source=source_id,
                    target=target_id,
                    href=link.representative_url,
                ),
            )
        if depth < max_hops and target_id not in visited:
            queue.append((target_id, depth + 1))
    return collapse_pages


def extract_pages_slug(href: str, base_url: str) -> str | None:
    """Return the post-``/pages/`` slug for an in-domain ``/pages/<slug>`` href.

    The result is the path *after* ``/pages/`` with any trailing ``/``
    stripped — e.g. ``"warranty"`` for ``/pages/warranty`` and
    ``"gift-bundle/coming-home-set"`` for ``/pages/gift-bundle/coming-home-set``.
    Returns ``None`` when:

    * ``href`` is empty,
    * the href is cross-host or has a non-HTTP scheme,
    * the path does not start with :data:`PAGES_PREFIX`,
    * the path is exactly ``/pages/`` or ``/pages`` (the bare index).

    The classifier never sees the empty slug so the caller does not need
    a special-case for it.

    Args:
        href: Raw ``href`` attribute from the scanned page.
        base_url: Absolute storefront base URL — drives same-host filtering.

    Returns:
        The trailing-slash-stripped post-``/pages/`` path, or ``None``.
    """
    if not href:
        return None
    abs_url = urljoin(base_url, href.strip())
    parts = urlsplit(abs_url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    if not is_in_domain(abs_url, base_url):
        return None
    path = parts.path or "/"
    if not path.startswith(PAGES_PREFIX):
        return None
    rest = path[len(PAGES_PREFIX) :].rstrip("/")
    if not rest:
        return None
    return rest


#: Phase tag emitted on every line that comes from the structural BFS pass
#: (spec §5.6 ``trace.jsonl``).  M5 will append additional lines tagged
#: ``"stateful"`` to the same file, so any reader must dispatch on
#: ``phase`` before parsing the rest of the line.
BFS_PHASE: Final[str] = "bfs"


def write_trace_jsonl(
    attempts: Iterable[BfsAttempt],
    path: Path | str,
) -> Path:
    """Write the BFS attempt trace to ``transition/trace.jsonl`` (spec §5.6).

    One JSON object per visit attempt, one attempt per line, in the
    order produced by :func:`run_bfs`.  Each line is tagged with
    ``"phase": "bfs"`` so the M5 stateful pass can append additional
    rows (``"phase": "stateful"``) without breaking forward readers.

    The line schema is:

    ```jsonc
    {
      "phase": "bfs",
      "canonical_id": "/products/<*>",
      "url": "https://shop/products/red-shirt",
      "depth": 1,
      "status": 200,        // null for skipped / nav_error
      "outcome": "ok",      // one of VisitOutcome
      "final_url": "https://shop/collections/sale",        // optional
      "resolved_canonical_id": "/collections/<*>"           // optional
    }
    ```

    Output is byte-stable for fixed input: keys are emitted in
    insertion order with no whitespace inside each line, and every line
    (including the last) is terminated with ``\n``.

    Args:
        attempts: Visit attempts in the order they should appear on
            disk — typically :attr:`BfsResult.attempts`.
        path: Destination path (parent directories must exist).

    Returns:
        The resolved :class:`pathlib.Path` written to disk.
    """
    p = Path(path)
    with p.open("w", encoding="utf-8") as fh:
        for attempt in attempts:
            line = {
                "phase": BFS_PHASE,
                "canonical_id": attempt.canonical_id,
                "url": attempt.url,
                "depth": attempt.depth,
                "status": attempt.status,
                "outcome": attempt.outcome,
            }
            if attempt.final_url is not None:
                line["final_url"] = attempt.final_url
            if attempt.resolved_canonical_id is not None:
                line["resolved_canonical_id"] = attempt.resolved_canonical_id
            fh.write(json.dumps(line, separators=(",", ":")))
            fh.write("\n")
    return p
