"""Unit tests for :mod:`shop_arena.env_eval.transition.bfs` (M4).

Covers spec §5.5.1 + impl-plan M4:

* every measurable seed becomes a node at depth ``0`` with the supplied
  ``representative_url``,
* canonical-id collapsing happens through
  :func:`shop_arena.env_eval.transition.canonicalize.canonicalize_href`
  — multiple ``/products/<slug>`` instances merge into a single node and
  the **first** concrete URL wins as ``representative_url``,
* edges are deduped by ``(source, target)`` (one edge per page-class
  pair, spec §5.5.1 step 4),
* BFS termination respects ``max_hops`` (per-node depth) and
  ``global_cap`` (visited URLs across all seeds),
* per-attempt outcomes are recorded for ``trace.jsonl``,
* HTTP/navigation errors mark the page visited but do not enqueue
  children.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from shop_arena.env_eval.transition import bfs as bfs_mod
from shop_arena.env_eval.transition import graph
from shop_arena.env_eval.transition.bfs import (
    BFS_PHASE,
    GLOBAL_CAP,
    BfsAttempt,
    BfsEdge,
    BfsNode,
    BfsSeed,
    run_bfs,
    write_trace_jsonl,
)

BASE: str = "https://shop.example.com/"


@dataclass
class FakeBrowser:
    """In-memory :class:`shop_arena.env_eval.transition.bfs.BfsBrowser` stub.

    Attributes:
        link_map: ``{representative_url: [hrefs]}`` returned by
            :meth:`hrefs` for the most recent ``goto``.
        statuses: Optional override for HTTP status per URL; defaults to
            ``200`` when absent.
        redirects: Optional final URL per requested URL; defaults to no
            redirect.
        raise_on: URLs whose ``goto`` raises a synthetic transport error.
        nav_log: Ordered list of every ``goto`` target — lets tests
            assert dedup/cap behaviour without inspecting attempts.
    """

    link_map: dict[str, list[str]]
    statuses: dict[str, int] = field(default_factory=dict[str, int])
    redirects: dict[str, str] = field(default_factory=dict[str, str])
    raise_on: set[str] = field(default_factory=set[str])
    nav_log: list[str] = field(default_factory=list[str])
    _current: str = ""

    def goto(self, url: str) -> int | None:
        self.nav_log.append(url)
        if url in self.raise_on:
            raise RuntimeError(f"synthetic nav error for {url}")
        self._current = self.redirects.get(url, url)
        return self.statuses.get(url, 200)

    def current_url(self) -> str:
        return self._current

    def hrefs(self, selector: str = "a[href]") -> list[str]:
        return list(self.link_map.get(self._current, []))


# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


def test_transition_bfs_modules_are_importable() -> None:
    """M0 layout marker: ``transition.bfs`` and ``transition.graph`` import."""
    assert bfs_mod.__name__ == "shop_arena.env_eval.transition.bfs"
    assert graph.__name__ == "shop_arena.env_eval.transition.graph"


def test_global_cap_default_matches_spec() -> None:
    """Spec §5.5: hard ceiling of 64 visited URLs across both passes."""
    assert GLOBAL_CAP == 64


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------


def test_run_bfs_empty_seeds_returns_empty_result() -> None:
    """No seeds → no navigations, no nodes, no attempts."""
    browser = FakeBrowser(link_map={})
    result = run_bfs(browser, BASE, [], max_hops=3)
    assert result.nodes == {}
    assert result.edges == []
    assert result.seeds == []
    assert result.attempts == []
    assert browser.nav_log == []


def test_run_bfs_seeds_become_nodes_at_depth_zero() -> None:
    """Every seed is enqueued at depth 0 and gets a node + ok attempt."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": [],
            "https://shop.example.com/cart": [],
        },
    )
    seeds = [
        BfsSeed("/", "https://shop.example.com/"),
        BfsSeed("/cart", "https://shop.example.com/cart"),
    ]
    result = run_bfs(browser, BASE, seeds, max_hops=3)
    assert list(result.nodes.keys()) == ["/", "/cart"]
    assert result.seeds == ["/", "/cart"]
    assert all(a.depth == 0 and a.outcome == "ok" for a in result.attempts)


def test_run_bfs_duplicate_seed_canonical_id_only_visits_once() -> None:
    """Two seeds with the same canonical id collapse to one navigation."""
    browser = FakeBrowser(link_map={"https://shop.example.com/": []})
    seeds = [
        BfsSeed("/", "https://shop.example.com/"),
        BfsSeed("/", "https://shop.example.com/?ref=2"),
    ]
    result = run_bfs(browser, BASE, seeds, max_hops=3)
    assert len(browser.nav_log) == 1
    assert result.seeds == ["/"]
    # First-seen wins: the duplicate's representative_url is ignored.
    assert result.nodes["/"].representative_url == "https://shop.example.com/"


# ---------------------------------------------------------------------------
# Edge + node behaviour
# ---------------------------------------------------------------------------


def test_run_bfs_first_concrete_url_wins_as_representative() -> None:
    """Two ``/products/<slug>`` hrefs collapse; the first becomes representative."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": [
                "https://shop.example.com/products/red-shirt",
                "https://shop.example.com/products/blue-shirt",
            ],
            "https://shop.example.com/products/red-shirt": [],
        },
    )
    seeds = [BfsSeed("/", "https://shop.example.com/")]
    result = run_bfs(browser, BASE, seeds, max_hops=3)
    assert "/products/<*>" in result.nodes
    assert (
        result.nodes["/products/<*>"].representative_url
        == "https://shop.example.com/products/red-shirt"
    )
    # Both hrefs collapse to the same edge — only one is recorded.
    product_edges = [e for e in result.edges if e.target == "/products/<*>"]
    assert len(product_edges) == 1
    assert product_edges[0].source == "/"


def test_run_bfs_edge_label_uses_click_with_first_href() -> None:
    """Edge label format matches spec §5.5.1: ``click(<href>)``."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": ["https://shop.example.com/cart"],
            "https://shop.example.com/cart": [],
        },
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=3,
    )
    [edge] = [e for e in result.edges if e.target == "/cart"]
    assert edge == BfsEdge(source="/", target="/cart", href="https://shop.example.com/cart")
    assert edge.label == "click(https://shop.example.com/cart)"


def test_run_bfs_redirect_normalizes_node_after_navigation() -> None:
    """Redirect aliases merge into the final same-domain canonical node."""
    content_url = "https://shop.example.com/content/pets"
    collection_url = "https://shop.example.com/collections/paw-hoodies"
    cart_url = "https://shop.example.com/cart"
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": [content_url],
            collection_url: [cart_url],
            cart_url: [],
        },
        redirects={content_url: collection_url},
    )

    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=2,
    )

    assert list(result.nodes.keys()) == ["/", "/collections/<*>", "/cart"]
    assert "/content/pets" not in result.nodes
    assert BfsEdge(source="/", target="/collections/<*>", href=content_url) in result.edges
    assert (
        BfsEdge(
            source="/collections/<*>",
            target="/cart",
            href=cart_url,
        )
        in result.edges
    )
    [attempt] = [a for a in result.attempts if a.url == content_url]
    assert attempt.canonical_id == "/content/pets"
    assert attempt.final_url == collection_url
    assert attempt.resolved_canonical_id == "/collections/<*>"


def test_run_bfs_redirect_alias_dedupes_existing_edges() -> None:
    """A redirect target that duplicates an existing edge keeps one edge."""
    content_url = "https://shop.example.com/content/pets"
    collection_url = "https://shop.example.com/collections/paw-hoodies"
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": [content_url, collection_url],
            collection_url: [],
        },
        redirects={content_url: collection_url},
    )

    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=1,
    )

    home_edges = [edge for edge in result.edges if edge.source == "/"]
    assert home_edges == [
        BfsEdge(source="/", target="/collections/<*>", href=content_url),
    ]
    assert "/content/pets" not in result.nodes
    assert browser.nav_log == ["https://shop.example.com/", content_url]


def test_run_bfs_skips_cross_host_and_disallowed_schemes() -> None:
    """Same-host filter + disallowed-scheme filter run via ``canonicalize_href``."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": [
                "mailto:hi@shop.example.com",
                "javascript:void(0)",
                "https://other.example.com/leak",
                "https://shop.example.com/cart",
            ],
            "https://shop.example.com/cart": [],
        },
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=3,
    )
    assert set(result.nodes.keys()) == {"/", "/cart"}
    assert [e.target for e in result.edges] == ["/cart"]


def test_run_bfs_emits_edges_at_depth_boundary() -> None:
    """Out-edges are recorded even at ``depth == max_hops`` (out-degree metric)."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": ["https://shop.example.com/cart"],
            # ``/cart`` is at depth 1; with max_hops=1 it is still visited
            # and its outgoing href to ``/account`` becomes an edge but is
            # NOT enqueued.
            "https://shop.example.com/cart": ["https://shop.example.com/account"],
        },
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=1,
    )
    # ``/account`` was added as a node (so the edge can target it) but
    # never visited — it does not appear in nav_log.
    assert "/account" in result.nodes
    assert "https://shop.example.com/account" not in browser.nav_log
    targets = {(e.source, e.target) for e in result.edges}
    assert ("/", "/cart") in targets
    assert ("/cart", "/account") in targets


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------


def test_run_bfs_max_hops_zero_visits_only_seeds() -> None:
    """``max_hops=0`` visits seeds and records their outgoing edges, no more."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": ["https://shop.example.com/cart"],
            "https://shop.example.com/cart": ["https://shop.example.com/account"],
        },
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=0,
    )
    assert browser.nav_log == ["https://shop.example.com/"]
    assert {n.canonical_id for n in result.nodes.values()} == {"/", "/cart"}


def test_run_bfs_respects_max_hops() -> None:
    """At ``max_hops=2`` the BFS visits seed (0), neighbour (1), neighbour-of-neighbour (2)."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": ["https://shop.example.com/a"],
            "https://shop.example.com/a": ["https://shop.example.com/b"],
            "https://shop.example.com/b": ["https://shop.example.com/c"],
            "https://shop.example.com/c": ["https://shop.example.com/d"],
        },
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=2,
    )
    visited_paths = [url.removeprefix("https://shop.example.com") for url in browser.nav_log]
    assert visited_paths == ["/", "/a", "/b"]
    # ``/c`` was queued as an edge target from ``/b`` but never popped
    # because depth would have been 3 > max_hops=2.
    assert "/c" in result.nodes
    assert "/d" not in result.nodes


def test_run_bfs_global_cap_stops_navigations() -> None:
    """Once ``global_cap`` visits have happened, remaining queue entries skip."""
    # 5 in-domain pages, each linking to the next. Cap at 3 visits.
    paths = ["/", "/a", "/b", "/c", "/d"]
    link_map = {
        f"https://shop.example.com{paths[i]}": (
            [f"https://shop.example.com{paths[i + 1]}"] if i + 1 < len(paths) else []
        )
        for i in range(len(paths))
    }
    browser = FakeBrowser(link_map=link_map)
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=10,
        global_cap=3,
    )
    assert len(browser.nav_log) == 3
    skipped_cap = [a for a in result.attempts if a.outcome == "skipped_cap"]
    assert skipped_cap, "expected at least one skipped_cap attempt"


def test_run_bfs_records_skipped_visited() -> None:
    """A canonical id reachable via two paths is popped twice — second is ``skipped_visited``."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": [
                "https://shop.example.com/a",
                "https://shop.example.com/b",
            ],
            "https://shop.example.com/a": ["https://shop.example.com/c"],
            "https://shop.example.com/b": ["https://shop.example.com/c"],
            "https://shop.example.com/c": [],
        },
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=3,
    )
    # ``/c`` is enqueued from both ``/a`` and ``/b`` but visited once.
    visits = [url for url in browser.nav_log if url.endswith("/c")]
    assert len(visits) == 1
    skipped = [a for a in result.attempts if a.outcome == "skipped_visited"]
    assert any(a.canonical_id == "/c" for a in skipped)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_run_bfs_http_error_marks_visited_without_enqueue() -> None:
    """A 404 from ``goto`` records ``http_error`` and does not scan links."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": ["https://shop.example.com/missing"],
            "https://shop.example.com/missing": ["https://shop.example.com/leak"],
        },
        statuses={"https://shop.example.com/missing": 404},
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=3,
    )
    [missing] = [a for a in result.attempts if a.canonical_id == "/missing"]
    assert missing == BfsAttempt(
        canonical_id="/missing",
        url="https://shop.example.com/missing",
        depth=1,
        status=404,
        outcome="http_error",
    )
    # Children of an HTTP-erroring page are not enqueued.
    assert "/leak" not in result.nodes


def test_run_bfs_nav_error_marks_visited_without_enqueue() -> None:
    """A raised exception from ``goto`` records ``nav_error`` and skips link scanning."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": ["https://shop.example.com/timeout"],
            "https://shop.example.com/timeout": ["https://shop.example.com/leak"],
        },
        raise_on={"https://shop.example.com/timeout"},
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=3,
    )
    [timeout] = [a for a in result.attempts if a.canonical_id == "/timeout"]
    assert timeout.outcome == "nav_error"
    assert timeout.status is None
    assert "/leak" not in result.nodes


# ---------------------------------------------------------------------------
# Multi-source BFS
# ---------------------------------------------------------------------------


def test_run_bfs_shares_visited_across_seeds() -> None:
    """Two seeds reaching the same canonical id navigate to it once total."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": ["https://shop.example.com/shared"],
            "https://shop.example.com/cart": ["https://shop.example.com/shared"],
            "https://shop.example.com/shared": [],
        },
    )
    seeds = [
        BfsSeed("/", "https://shop.example.com/"),
        BfsSeed("/cart", "https://shop.example.com/cart"),
    ]
    result = run_bfs(browser, BASE, seeds, max_hops=3)
    shared_visits = [u for u in browser.nav_log if u.endswith("/shared")]
    assert len(shared_visits) == 1
    # Both seeds emit edges to ``/shared``.
    edges_to_shared = {(e.source, e.target) for e in result.edges if e.target == "/shared"}
    assert edges_to_shared == {("/", "/shared"), ("/cart", "/shared")}


def test_run_bfs_node_insertion_order_matches_discovery() -> None:
    """``nodes`` dict is insertion-ordered = byte-stable for a fixed input."""
    browser = FakeBrowser(
        link_map={
            "https://shop.example.com/": [
                "https://shop.example.com/a",
                "https://shop.example.com/b",
            ],
            "https://shop.example.com/a": [],
            "https://shop.example.com/b": [],
        },
    )
    result = run_bfs(
        browser,
        BASE,
        [BfsSeed("/", "https://shop.example.com/")],
        max_hops=3,
    )
    assert list(result.nodes.keys()) == ["/", "/a", "/b"]


# ---------------------------------------------------------------------------
# Dataclass shape sanity
# ---------------------------------------------------------------------------


def test_bfs_node_default_kind_is_url() -> None:
    """Structural-pass nodes carry the ``"url"`` discriminator."""
    node = BfsNode(canonical_id="/", representative_url="https://x/")
    assert node.kind == "url"


# ---------------------------------------------------------------------------
# write_trace_jsonl
# ---------------------------------------------------------------------------


def test_write_trace_jsonl_one_line_per_attempt(tmp_path: Path) -> None:
    """Each :class:`BfsAttempt` becomes exactly one JSON line, in input order."""
    attempts = [
        BfsAttempt(
            canonical_id="/",
            url="https://shop/",
            depth=0,
            status=200,
            outcome="ok",
        ),
        BfsAttempt(
            canonical_id="/products/<*>",
            url="https://shop/products/red-shirt",
            depth=1,
            status=None,
            outcome="skipped_visited",
        ),
    ]
    path = write_trace_jsonl(attempts, tmp_path / "trace.jsonl")
    assert path == tmp_path / "trace.jsonl"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) == 2
    # Trailing newline so callers can append (M5).
    assert text.endswith("\n")
    import json as _json

    parsed = [_json.loads(line) for line in lines]
    assert parsed[0] == {
        "phase": BFS_PHASE,
        "canonical_id": "/",
        "url": "https://shop/",
        "depth": 0,
        "status": 200,
        "outcome": "ok",
    }
    assert parsed[1] == {
        "phase": BFS_PHASE,
        "canonical_id": "/products/<*>",
        "url": "https://shop/products/red-shirt",
        "depth": 1,
        "status": None,
        "outcome": "skipped_visited",
    }


def test_write_trace_jsonl_includes_redirect_fields(tmp_path: Path) -> None:
    """Redirect metadata is serialized only when present."""
    attempt = BfsAttempt(
        canonical_id="/content/pets",
        url="https://shop/content/pets",
        depth=1,
        status=200,
        outcome="ok",
        final_url="https://shop/collections/paw-hoodies",
        resolved_canonical_id="/collections/<*>",
    )

    path = write_trace_jsonl([attempt], tmp_path / "trace.jsonl")

    import json as _json

    [parsed] = [_json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert parsed["final_url"] == "https://shop/collections/paw-hoodies"
    assert parsed["resolved_canonical_id"] == "/collections/<*>"


def test_write_trace_jsonl_is_byte_stable(tmp_path: Path) -> None:
    """Repeated writes against the same attempts produce byte-identical output."""
    attempts = [
        BfsAttempt(
            canonical_id="/",
            url="https://shop/",
            depth=0,
            status=200,
            outcome="ok",
        ),
    ]
    a = write_trace_jsonl(attempts, tmp_path / "a.jsonl").read_bytes()
    b = write_trace_jsonl(attempts, tmp_path / "b.jsonl").read_bytes()
    assert a == b


def test_write_trace_jsonl_empty_attempts_writes_empty_file(tmp_path: Path) -> None:
    """Zero attempts produce an empty file (no spurious newline)."""
    path = write_trace_jsonl([], tmp_path / "trace.jsonl")
    assert path.read_text(encoding="utf-8") == ""


def test_write_trace_jsonl_appendable_for_m5(tmp_path: Path) -> None:
    """The writer leaves the file in a state where M5 can append more lines."""
    attempts = [
        BfsAttempt(
            canonical_id="/",
            url="https://shop/",
            depth=0,
            status=200,
            outcome="ok",
        ),
    ]
    path = write_trace_jsonl(attempts, tmp_path / "trace.jsonl")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"phase":"stateful","rule":"x"}\n')
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# /pages classifier wiring (lazy per-page-scan batched callback).
# ---------------------------------------------------------------------------


def test_run_bfs_invokes_classifier_for_new_pages_slugs() -> None:
    """``classify_pages`` fires once per scan that exposes fresh slugs."""
    homepage = "https://shop.example.com/"
    browser = FakeBrowser(
        link_map={
            homepage: [
                "/pages/warranty",
                "/pages/about",
                "/cart",
            ],
            "https://shop.example.com/cart": [],
            "https://shop.example.com/pages/warranty": [],
            "https://shop.example.com/pages/about": [],
        },
    )
    seeds = [BfsSeed("/", homepage)]
    calls: list[list[str]] = []

    def classify(new_paths: Sequence[str]) -> frozenset[str]:
        calls.append(list(new_paths))
        # Mark every newly discovered slug as collapse-eligible so subsequent
        # links land on the shared ``/pages/<*>`` canonical id.
        return frozenset(new_paths)

    result = run_bfs(
        browser,
        BASE,
        seeds,
        max_hops=2,
        classify_pages=classify,
    )

    assert len(calls) == 1
    assert sorted(calls[0]) == ["about", "warranty"]
    pages_node_ids = [nid for nid in result.nodes if nid.startswith("/pages")]
    # With both slugs in collapse_pages, ``/pages/warranty`` and
    # ``/pages/about`` collapse onto a single ``/pages/<*>`` canonical id.
    assert pages_node_ids == ["/pages/<*>"]


def test_run_bfs_skips_classifier_when_no_new_slugs() -> None:
    """Pages without ``/pages/<slug>`` hrefs do not trigger the callback."""
    homepage = "https://shop.example.com/"
    browser = FakeBrowser(
        link_map={
            homepage: ["/cart", "/products/sku-1"],
            "https://shop.example.com/cart": [],
            "https://shop.example.com/products/sku-1": [],
        },
    )
    seeds = [BfsSeed("/", homepage)]
    calls: list[list[str]] = []

    def classify(new_paths: Sequence[str]) -> frozenset[str]:
        calls.append(list(new_paths))  # pragma: no cover — must not run
        return frozenset()

    run_bfs(browser, BASE, seeds, max_hops=2, classify_pages=classify)

    assert calls == []


def test_run_bfs_no_classifier_preserves_full_pages_paths() -> None:
    """When ``classify_pages`` is ``None`` the BFS keeps every ``/pages/<slug>``."""
    homepage = "https://shop.example.com/"
    browser = FakeBrowser(
        link_map={
            homepage: ["/pages/warranty", "/pages/about"],
            "https://shop.example.com/pages/warranty": [],
            "https://shop.example.com/pages/about": [],
        },
    )
    seeds = [BfsSeed("/", homepage)]

    result = run_bfs(browser, BASE, seeds, max_hops=2)

    pages_ids = sorted(nid for nid in result.nodes if nid.startswith("/pages"))
    assert pages_ids == ["/pages/about", "/pages/warranty"]


def test_run_bfs_classifies_sub_path_pages_slug() -> None:
    """``/pages/gift-bundle/coming-home-set`` is treated as a sub-path slug."""
    homepage = "https://shop.example.com/"
    browser = FakeBrowser(
        link_map={
            homepage: ["/pages/gift-bundle/coming-home-set"],
            "https://shop.example.com/pages/gift-bundle/coming-home-set": [],
        },
    )
    seeds = [BfsSeed("/", homepage)]
    calls: list[list[str]] = []

    def classify(new_paths: Sequence[str]) -> frozenset[str]:
        calls.append(list(new_paths))
        return frozenset()

    run_bfs(browser, BASE, seeds, max_hops=2, classify_pages=classify)

    assert calls == [["gift-bundle/coming-home-set"]]


def test_run_bfs_classifier_error_propagates() -> None:
    """A classifier error aborts the BFS — no silent fallback."""
    homepage = "https://shop.example.com/"
    browser = FakeBrowser(
        link_map={homepage: ["/pages/warranty"]},
    )
    seeds = [BfsSeed("/", homepage)]

    def classify(_new_paths: Sequence[str]) -> frozenset[str]:
        raise RuntimeError("classifier boom")

    try:
        run_bfs(browser, BASE, seeds, max_hops=2, classify_pages=classify)
    except RuntimeError as exc:
        assert "classifier boom" in str(exc)
    else:
        msg = "classifier exception did not propagate"
        raise AssertionError(msg)


def test_extract_pages_slug_strips_trailing_slash() -> None:
    """``extract_pages_slug`` returns the post-prefix slug with no trailing slash."""
    assert (
        bfs_mod.extract_pages_slug("/pages/warranty/", BASE)
        == "warranty"
    )
    assert (
        bfs_mod.extract_pages_slug("/pages/gift-bundle/coming-home-set", BASE)
        == "gift-bundle/coming-home-set"
    )


def test_extract_pages_slug_returns_none_for_non_pages_href() -> None:
    """Non-``/pages/`` hrefs and out-of-domain hrefs return ``None``."""
    assert bfs_mod.extract_pages_slug("/cart", BASE) is None
    assert bfs_mod.extract_pages_slug("/pages/", BASE) is None
    assert (
        bfs_mod.extract_pages_slug("https://other.com/pages/warranty", BASE)
        is None
    )
