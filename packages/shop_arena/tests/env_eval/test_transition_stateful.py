"""Unit tests for ``shop_arena.env_eval.transition.stateful`` (spec §5.5.2, M5).

Covers the rule executor's six surfaces in isolation:

* :func:`compute_structural_fingerprint` — closed
  ``(node_count, role_histogram, set_of_bids)`` snapshot.
* :func:`fingerprints_differ` — true/false on each of the three axes.
* :func:`resolve_selector` — landmark scoping + role/name match + bid extraction.
* :func:`load_state_prompt` — divider stripping, deterministic body load.
* :func:`name_state` + :class:`StateNameArtifact` — vision-call wrapper +
  artifact schema, with malformed responses collapsing to ``no_change``.
* :func:`execute_rule` — derived-query gating, ``no_target`` short-circuit,
  ``no_diff`` short-circuit, full ``fired`` happy path with pre/post screenshot
  + ``<state_id>.json`` artifact persistence.

The tests deliberately do **not** spin up Playwright or BrowserGym — every
collaborator is a small fake constructed inline so the suite stays
hermetic and fast.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from shop_arena.env_eval.transition import stateful
from shop_arena.env_eval.transition import stateful as _stateful_mod
from shop_arena.env_eval.transition.rules import (
    RULE_STATE_NAMES,
    RULES,
    Rule,
    Selector,
)
from shop_arena.env_eval.transition.stateful import (
    DEFAULT_NETWORKIDLE_TIMEOUT_MS,
    STATE_NAMES,
    STATE_PROMPT_VERSION,
    STATE_RESPONSE_SCHEMA,
    STATEFUL_PHASE,
    StatefulAttempt,
    StateNameArtifact,
    StructuralFingerprint,
    build_state_prompt_payload,
    compute_structural_fingerprint,
    execute_rule,
    fingerprints_differ,
    load_state_prompt,
    name_state,
    resolve_selector,
    run_stateful_pass,
    state_node_id,
    write_state_artifact,
    write_stateful_trace_lines,
)
from shop_arena.util._llm import VisionResponse

# Capture the real settle function before the autouse no-op in conftest
# replaces it.  Tests that exercise the polling loop directly use this
# alias; the rest of the file is happy with the noop.
_real_wait_for_axtree_settle = _stateful_mod.wait_for_axtree_settle

# ---------------------------------------------------------------------------
# Axtree fixture builders.
# ---------------------------------------------------------------------------


def _node(
    node_id: str,
    role: str,
    *,
    name: str = "",
    bid: str | None = None,
    children: list[str] | None = None,
) -> dict[str, Any]:
    """Build a CDP-shaped axtree node the production code expects."""
    out: dict[str, Any] = {
        "nodeId": node_id,
        "role": {"value": role},
        "name": {"value": name},
        "childIds": list(children or []),
    }
    if bid is not None:
        out["browsergym_id"] = bid
    return out


def _axtree(*nodes: Mapping[str, Any]) -> dict[str, Any]:
    return {"nodes": list(nodes)}


def _homepage_axtree(
    *,
    cart_name: str = "Cart",
    cart_bid: str = "header-cart-1",
    extra_nodes: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Minimal homepage tree: WebArea > banner > [search button, cart link]."""
    extras = list(extra_nodes or [])
    extra_ids = [n["nodeId"] for n in extras]
    return _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3", "4", *extra_ids]),
        _node("3", "button", name="Search", bid="header-search-1"),
        _node("4", "link", name=cart_name, bid=cart_bid),
        *extras,
    )


# ---------------------------------------------------------------------------
# Structural fingerprint.
# ---------------------------------------------------------------------------


def test_compute_structural_fingerprint_basic_shape() -> None:
    """The fingerprint records node count, per-role histogram, and bids."""
    fp = compute_structural_fingerprint(_homepage_axtree())
    assert fp.node_count == 4
    assert fp.role_histogram == {
        "RootWebArea": 1,
        "banner": 1,
        "button": 1,
        "link": 1,
    }
    assert fp.bids == frozenset({"header-search-1", "header-cart-1"})


def test_compute_structural_fingerprint_tolerates_malformed_nodes() -> None:
    """Non-mapping entries and missing roles/bids do not crash the fingerprint."""
    axtree = {
        "nodes": [
            _node("1", "RootWebArea"),
            "not-a-node",
            {"nodeId": "2"},  # no role, no bid
            _node("3", "button", bid="b-1"),
        ],
    }
    fp = compute_structural_fingerprint(axtree)
    # The string is dropped; the role-less mapping counts toward node_count
    # but not toward the histogram; the button bumps both.
    assert fp.node_count == 3
    assert fp.role_histogram == {"RootWebArea": 1, "button": 1}
    assert fp.bids == frozenset({"b-1"})


def test_compute_structural_fingerprint_rejects_non_mapping_axtree() -> None:
    """A non-mapping axtree input is a programmer error."""
    with pytest.raises(TypeError):
        compute_structural_fingerprint(["nope"])  # type: ignore[arg-type]


def test_compute_structural_fingerprint_rejects_non_list_nodes() -> None:
    """A non-list ``nodes`` value is a programmer error."""
    with pytest.raises(TypeError):
        compute_structural_fingerprint({"nodes": {"not": "a list"}})


def test_fingerprints_differ_on_node_count() -> None:
    pre = StructuralFingerprint(node_count=3, role_histogram={"button": 1}, bids=frozenset())
    post = StructuralFingerprint(node_count=4, role_histogram={"button": 1}, bids=frozenset())
    assert fingerprints_differ(pre, post)


def test_fingerprints_differ_on_role_histogram() -> None:
    pre = StructuralFingerprint(node_count=4, role_histogram={"button": 1}, bids=frozenset())
    post = StructuralFingerprint(node_count=4, role_histogram={"button": 2}, bids=frozenset())
    assert fingerprints_differ(pre, post)


def test_fingerprints_differ_on_bid_set() -> None:
    pre = StructuralFingerprint(node_count=4, role_histogram={"button": 1}, bids=frozenset({"a"}))
    post = StructuralFingerprint(node_count=4, role_histogram={"button": 1}, bids=frozenset({"b"}))
    assert fingerprints_differ(pre, post)


def test_fingerprints_match_when_all_three_axes_equal() -> None:
    fp = StructuralFingerprint(
        node_count=2,
        role_histogram={"button": 1, "link": 1},
        bids=frozenset({"a", "b"}),
    )
    same = StructuralFingerprint(
        node_count=2,
        role_histogram={"button": 1, "link": 1},
        bids=frozenset({"a", "b"}),
    )
    assert not fingerprints_differ(fp, same)


# ---------------------------------------------------------------------------
# wait_for_axtree_settle.
# ---------------------------------------------------------------------------


def _stable_axtree() -> dict[str, Any]:
    """Single-node axtree: every fingerprint pair from this is identical."""
    return {"nodes": [{"nodeId": "1", "role": {"value": "main"}}]}


def test_wait_for_axtree_settle_returns_immediately_when_max_wait_zero() -> None:
    """``max_wait_ms <= 0`` is the documented test seam: skip polling entirely."""
    calls = 0

    def axtree() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _stable_axtree()

    _real_wait_for_axtree_settle(axtree=axtree, max_wait_ms=0)

    assert calls == 0


def test_wait_for_axtree_settle_returns_when_fingerprint_is_stable() -> None:
    """Identical fingerprints across polls → settle returns after ``stable_ms``."""
    started = time.monotonic()
    _real_wait_for_axtree_settle(
        axtree=_stable_axtree,
        poll_interval_ms=10,
        stable_ms=20,
        max_wait_ms=500,
    )
    elapsed_ms = (time.monotonic() - started) * 1000
    # Bounded by stable_ms + a couple of poll intervals; well under max_wait.
    assert elapsed_ms < 200, f"settle should exit promptly, took {elapsed_ms:.0f}ms"


def test_wait_for_axtree_settle_re_arms_timer_when_fingerprint_changes() -> None:
    """A late mutation pushes the deadline; settle returns once it stabilizes again."""
    sequence: list[dict[str, Any]] = [
        {"nodes": [{"nodeId": "1", "role": {"value": "main"}}]},
        {"nodes": [{"nodeId": "1", "role": {"value": "main"}}]},
        # Mid-poll: a popup_modal appears.
        {"nodes": [
            {"nodeId": "1", "role": {"value": "main"}},
            {"nodeId": "2", "role": {"value": "dialog"}, "browsergym_id": "d-1"},
        ]},
    ]
    idx = 0

    def axtree() -> dict[str, Any]:
        nonlocal idx
        out = sequence[min(idx, len(sequence) - 1)]
        idx += 1
        return out

    _real_wait_for_axtree_settle(
        axtree=axtree,
        poll_interval_ms=10,
        stable_ms=30,
        max_wait_ms=500,
    )
    # Must have polled at least until the dialog node showed up; once it
    # stabilises on the new fingerprint, settle returns.
    assert idx >= 4


def test_wait_for_axtree_settle_caps_at_max_wait_for_unstable_pages() -> None:
    """A page that never stabilises returns by ``max_wait_ms`` rather than hanging."""
    counter = 0

    def churning_axtree() -> dict[str, Any]:
        nonlocal counter
        counter += 1
        # Each call returns a fresh bid → fingerprint never stabilises.
        return {"nodes": [{
            "nodeId": str(counter),
            "role": {"value": "main"},
            "browsergym_id": f"b-{counter}",
        }]}

    started = time.monotonic()
    _real_wait_for_axtree_settle(
        axtree=churning_axtree,
        poll_interval_ms=10,
        stable_ms=50,
        max_wait_ms=80,
    )
    elapsed_ms = (time.monotonic() - started) * 1000
    assert 70 <= elapsed_ms < 250, (
        f"settle should exit near max_wait, took {elapsed_ms:.0f}ms"
    )


def test_wait_for_axtree_settle_respects_min_wait_floor() -> None:
    """``min_wait_ms`` floors total time even when the page is instantly stable.

    This is the homepage popup case: the axtree fingerprint is identical
    from the first poll (hero animation is pure CSS, no DOM mutation), but
    a Klaviyo-style ``setTimeout`` popup will mount a few seconds later.
    Without the floor, settle would return at ``stable_ms`` (~800ms) and
    miss the popup; with it, settle keeps polling so a late mutation has
    a chance to re-arm the stability counter."""
    started = time.monotonic()
    _real_wait_for_axtree_settle(
        axtree=_stable_axtree,
        poll_interval_ms=10,
        stable_ms=20,
        min_wait_ms=150,
        max_wait_ms=500,
    )
    elapsed_ms = (time.monotonic() - started) * 1000
    # Must wait at least min_wait, but not so long that it ever runs to max.
    assert 140 <= elapsed_ms < 300, (
        f"settle should honour min_wait_ms floor, took {elapsed_ms:.0f}ms"
    )


def test_wait_for_axtree_settle_swallows_exceptions_in_axtree_callable() -> None:
    """A failing ``axtree()`` does not propagate — settle is best-effort."""

    def failing_axtree() -> dict[str, Any]:
        raise RuntimeError("simulated CDP detach")

    # No assertion necessary: the call must simply not raise.
    _real_wait_for_axtree_settle(
        axtree=failing_axtree,
        poll_interval_ms=10,
        stable_ms=20,
        max_wait_ms=100,
    )


def _selector(roles: str | tuple[str, ...], pattern: str, landmark: str = "banner") -> Selector:
    """Tiny helper so call sites can pass a single role string or a tuple."""
    role_tuple = (roles,) if isinstance(roles, str) else roles
    return Selector(
        roles=role_tuple,
        name_pattern=re.compile(pattern, re.IGNORECASE | re.UNICODE),
        landmark=landmark,  # type: ignore[arg-type]
    )


def test_resolve_selector_returns_first_matching_descendant_bid() -> None:
    """Happy path: role + name regex + landmark scope all match."""
    axtree = _homepage_axtree()
    selector = _selector("link", r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) == "header-cart-1"


def test_resolve_selector_returns_none_when_landmark_missing() -> None:
    """No banner / no main → the rule cannot fire."""
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "main", children=["3"]),
        _node("3", "link", name="Cart", bid="cart-1"),
    )
    selector = _selector("link", r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) is None


def test_resolve_selector_respects_landmark_scope() -> None:
    """A "Cart" link in the main body must NOT match a banner-scoped rule."""
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2", "3"]),
        _node("2", "banner", children=[]),  # banner exists but is empty
        _node("3", "main", children=["4"]),
        _node("4", "link", name="Cart", bid="body-cart-1"),
    )
    selector = _selector("link", r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) is None


def test_resolve_selector_skips_nodes_without_bid() -> None:
    """Selector resolution requires a ``browsergym_id`` to be useful for the executor."""
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3", "4"]),
        _node("3", "link", name="Cart"),  # matches role+name but has no bid
        _node("4", "link", name="Cart", bid="cart-bid-1"),
    )
    selector = _selector("link", r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) == "cart-bid-1"


def test_resolve_selector_uses_pre_order_dfs() -> None:
    """The walk visits children in document order (childIds order)."""
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3", "4"]),
        _node("3", "link", name="Cart", bid="first"),
        _node("4", "link", name="Cart", bid="second"),
    )
    selector = _selector("link", r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) == "first"


def test_resolve_selector_handles_cyclic_child_ids() -> None:
    """A self-referential childId must not infinite-loop the walk."""
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3"]),
        _node("3", "link", name="Cart", bid="cart-1", children=["3"]),  # cycle
    )
    selector = _selector("link", r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) == "cart-1"


def test_resolve_selector_against_real_rule_table() -> None:
    """The shipped homepage cart rule resolves on a synthetic homepage tree."""
    rule = next(r for r in RULES if r.id == "homepage_open_cart_drawer")
    axtree = _homepage_axtree(cart_name="Open cart")
    assert resolve_selector(axtree, rule.selector) == "header-cart-1"


def test_resolve_selector_matches_any_role_in_tuple() -> None:
    """v0.2: ``Selector.roles`` is a tuple; a node with any role in the
    tuple must resolve.  Drawer-style themes mark the header cart as
    ``button`` instead of ``link`` — the rule must still find it."""
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3"]),
        _node("3", "button", name="Open cart", bid="cart-button-1"),
    )
    selector = _selector(("link", "button"), r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) == "cart-button-1"


def test_resolve_selector_role_tuple_does_not_imply_priority_per_role() -> None:
    """Resolution is pre-order DFS first, role-membership second: the
    first matching descendant wins regardless of where its role sits in
    the ``roles`` tuple.  Pinning this so a future refactor that does
    a per-role pass would visibly fail."""
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3", "4"]),
        # ``button`` cart appears first in document order; even though
        # ``link`` is listed first in the roles tuple, document order wins.
        _node("3", "button", name="Cart", bid="button-cart"),
        _node("4", "link", name="Cart", bid="link-cart"),
    )
    selector = _selector(("link", "button"), r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) == "button-cart"


def test_resolve_selector_returns_none_when_no_role_matches() -> None:
    """A node whose role is outside the rule's ``roles`` tuple must not match."""
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3"]),
        # ``generic`` is not in the roles tuple.
        _node("3", "generic", name="Cart", bid="generic-cart"),
    )
    selector = _selector(("link", "button"), r"\bcart\b", landmark="banner")
    assert resolve_selector(axtree, selector) is None


# ---------------------------------------------------------------------------
# Prompt loader + payload assembly.
# ---------------------------------------------------------------------------


def test_load_state_prompt_strips_documentation_header() -> None:
    """Prompt body starts after the first ``---`` divider."""
    body = load_state_prompt()
    # The bullet list of state names must be in the body.
    for name in RULE_STATE_NAMES:
        assert f"`{name}`" in body
    assert "no_change" in body
    # The documentation-header string must NOT leak into the body.
    assert "Used by `shop_arena.env_eval.transition.stateful`" not in body


def test_load_state_prompt_is_deterministic() -> None:
    """Reading twice yields byte-identical content."""
    assert load_state_prompt() == load_state_prompt()


def test_build_state_prompt_payload_appends_rule_context() -> None:
    """The triggering rule context is appended below the prompt body."""
    rule = next(r for r in RULES if r.id == "homepage_open_cart_drawer")
    out = build_state_prompt_payload(rule, base_prompt="BODY\n")
    assert out.startswith("BODY")
    assert "Triggering rule: homepage_open_cart_drawer" in out
    assert "Action: click" in out
    assert "Expected state: cart_drawer" in out


# ---------------------------------------------------------------------------
# Name-state + artifact schema.
# ---------------------------------------------------------------------------


@dataclass
class _FakeVisionClient:
    """Minimal :class:`LLMVisionClient` stub recording its calls."""

    response: VisionResponse
    model_name: str = "fake-vision-1"
    calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @property
    def model(self) -> str:
        return self.model_name

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        self.calls.append(
            {
                "prompt": prompt,
                "images": tuple(images),
                "schema": dict(schema),
                "temperature": temperature,
            },
        )
        return self.response


def _rule_for_homepage_cart() -> Rule:
    return next(r for r in RULES if r.id == "homepage_open_cart_drawer")


def test_name_state_returns_validated_state_on_clean_response() -> None:
    """Clean response → parsed enum value, no parse errors."""
    client = _FakeVisionClient(
        VisionResponse(parsed={"state": "cart_drawer"}, raw_response='{"state":"cart_drawer"}'),
    )
    state, raw, errors = name_state(
        client,
        rule=_rule_for_homepage_cart(),
        pre_png=b"\x89PNGpre",
        post_png=b"\x89PNGpost",
    )
    assert state == "cart_drawer"
    assert raw == '{"state":"cart_drawer"}'
    assert errors == ()
    assert len(client.calls) == 1
    assert client.calls[0]["schema"] == STATE_RESPONSE_SCHEMA
    assert client.calls[0]["temperature"] == 0.0


def test_name_state_forwards_pre_and_post_screenshots_in_order() -> None:
    """Both screenshots reach the wire, pre first then post (spec §5.5.2)."""
    client = _FakeVisionClient(
        VisionResponse(parsed={"state": "cart_drawer"}, raw_response='{"state":"cart_drawer"}'),
    )
    name_state(
        client,
        rule=_rule_for_homepage_cart(),
        pre_png=b"\x89PNGpre",
        post_png=b"\x89PNGpost",
    )
    assert client.calls[0]["images"] == (b"\x89PNGpre", b"\x89PNGpost")


def test_name_state_collapses_to_no_change_when_response_unparsed() -> None:
    """Client returns ``parsed=None`` → state defaults to no_change with errors propagated."""
    client = _FakeVisionClient(
        VisionResponse(
            parsed=None,
            raw_response="garbage",
            parse_errors=("upstream parse failed",),
        ),
    )
    state, _raw, errors = name_state(
        client,
        rule=_rule_for_homepage_cart(),
        pre_png=b"a",
        post_png=b"b",
    )
    assert state == "no_change"
    assert errors == ("upstream parse failed",)


def test_name_state_collapses_to_no_change_on_schema_violation() -> None:
    """Schema rejects unknown enum value → state=no_change + parse_errors populated."""
    client = _FakeVisionClient(
        VisionResponse(parsed={"state": "totally-invented-state"}, raw_response="…"),
    )
    state, _raw, errors = name_state(
        client,
        rule=_rule_for_homepage_cart(),
        pre_png=b"a",
        post_png=b"b",
    )
    assert state == "no_change"
    assert errors  # at least one schema-validation error


def test_name_state_rejects_extra_keys() -> None:
    """Extra keys violate the closed schema and collapse to no_change."""
    client = _FakeVisionClient(
        VisionResponse(parsed={"state": "cart_drawer", "extra": "oops"}, raw_response="…"),
    )
    state, _raw, errors = name_state(
        client,
        rule=_rule_for_homepage_cart(),
        pre_png=b"a",
        post_png=b"b",
    )
    assert state == "no_change"
    assert errors


def test_state_name_artifact_round_trips() -> None:
    """Schema + writer produce byte-stable JSON that re-validates."""
    artifact = StateNameArtifact(
        prompt_version=STATE_PROMPT_VERSION,
        model="fake-1",
        temperature=0.0,
        rule_id="homepage_open_cart_drawer",
        action="click",
        expected_state="cart_drawer",
        state="cart_drawer",
        raw_response='{"state":"cart_drawer"}',
        parse_errors=(),
        pre_screenshot="state-1.pre.png",
        post_screenshot="state-1.post.png",
    )
    out = StateNameArtifact.model_validate(json.loads(json.dumps(artifact.model_dump(mode="json"))))
    assert out == artifact


def test_state_name_artifact_rejects_unknown_state(tmp_path: Path) -> None:
    """An off-enum ``state`` value fails closed-schema validation."""
    with pytest.raises(ValidationError):
        StateNameArtifact(
            prompt_version=STATE_PROMPT_VERSION,
            model="fake",
            temperature=0.0,
            rule_id="x",
            action="click",
            expected_state="cart_drawer",
            state="not-a-real-state",  # type: ignore[arg-type]
            raw_response="",
            pre_screenshot="a.png",
            post_screenshot="b.png",
        )


def test_state_name_artifact_writer_is_byte_stable(tmp_path: Path) -> None:
    """Two writes of the same artifact produce identical bytes."""
    artifact = StateNameArtifact(
        prompt_version=STATE_PROMPT_VERSION,
        model="fake",
        temperature=0.0,
        rule_id="r1",
        action="click",
        expected_state="cart_drawer",
        state="cart_drawer",
        raw_response="…",
        pre_screenshot="a.png",
        post_screenshot="b.png",
    )
    p1 = write_state_artifact(artifact, tmp_path / "a.json")
    p2 = write_state_artifact(artifact, tmp_path / "b.json")
    assert p1.read_bytes() == p2.read_bytes()
    # JSON keys must be sorted (top-level alphabetical) so the file is comparable.
    keys = list(json.loads(p1.read_text()).keys())
    assert keys == sorted(keys)


def test_state_names_strict_superset_of_rule_state_names() -> None:
    """The LLM enum must enumerate every rule-emitted state name."""
    assert set(RULE_STATE_NAMES).issubset(set(STATE_NAMES))


# ---------------------------------------------------------------------------
# execute_rule.
# ---------------------------------------------------------------------------


def _good_response() -> VisionResponse:
    return VisionResponse(parsed={"state": "cart_drawer"}, raw_response='{"state":"cart_drawer"}')


@dataclass
class _ScriptedSession:
    """Replays a sequence of axtree dicts on each ``axtree()`` call."""

    axtrees: list[Mapping[str, Any]]
    screenshots: list[bytes] = field(default_factory=list[bytes])
    goto_calls: list[str] = field(default_factory=list[str])
    goto_raises: bool = False
    _idx: int = 0
    _shot_idx: int = 0

    def goto(self, url: str) -> None:
        if self.goto_raises:
            raise RuntimeError(f"simulated goto failure for {url}")
        self.goto_calls.append(url)

    def axtree(self) -> Mapping[str, Any]:
        out = self.axtrees[self._idx]
        self._idx += 1
        return out

    def screenshot_png(self) -> bytes:
        out = self.screenshots[self._shot_idx]
        self._shot_idx += 1
        return out


@dataclass
class _StubLocator:
    """Records every action invoked through the BrowserGym ``get_elem_by_bid`` shim."""

    invocations: list[tuple[str, tuple[Any, ...]]] = field(
        default_factory=list[tuple[str, tuple[Any, ...]]],
    )

    def click(self) -> None:
        self.invocations.append(("click", ()))

    def fill(self, text: str) -> None:
        self.invocations.append(("fill", (text,)))

    def hover(self) -> None:
        self.invocations.append(("hover", ()))


@dataclass
class _StubPage:
    """Minimal Playwright-page stand-in honoured by ``_execute_action``."""

    locator: _StubLocator = field(default_factory=_StubLocator)
    wait_calls: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])

    def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.wait_calls.append((state, timeout))


@pytest.fixture
def patch_get_elem_by_bid(monkeypatch: pytest.MonkeyPatch) -> _StubLocator:
    """Replace ``get_elem_by_bid`` with a stub that returns a recording locator."""
    locator = _StubLocator()
    from browsergym.core.action import utils

    def fake(_page: object, bid: str, *_args: Any, **_kwargs: Any) -> _StubLocator:
        del _page, bid
        return locator

    monkeypatch.setattr(utils, "get_elem_by_bid", fake)
    return locator


def test_execute_rule_skips_when_derived_query_missing(tmp_path: Path) -> None:
    """``needs_derived_query=True`` + missing query → ``skipped_no_query``."""
    rule = next(r for r in RULES if r.id == "homepage_predictive_search")
    session = _ScriptedSession(axtrees=[])  # never consulted
    result = execute_rule(
        rule,
        page_url="https://shop/",
        derived_query=None,
        states_dir=tmp_path,
        state_id="any",
        llm_client=None,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=None,
    )
    assert result.outcome == "skipped_no_query"
    assert result.bid is None
    assert result.state is None
    assert session.goto_calls == []  # the page was never reloaded


def test_execute_rule_records_load_error_when_goto_raises(tmp_path: Path) -> None:
    """A goto failure does not crash the run; outcome is recorded."""
    rule = _rule_for_homepage_cart()
    session = _ScriptedSession(axtrees=[], goto_raises=True)
    result = execute_rule(
        rule,
        page_url="https://shop/",
        derived_query=None,
        states_dir=tmp_path,
        state_id="cart-1",
        llm_client=None,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=None,
    )
    assert result.outcome == "load_error"
    assert result.error is not None and "simulated goto failure" in result.error


def test_execute_rule_returns_no_target_when_selector_fails(tmp_path: Path) -> None:
    """Selector resolution fails → no action, no LLM call, no screenshots."""
    rule = _rule_for_homepage_cart()
    # Banner without a cart link → selector cannot resolve.
    axtree = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3"]),
        _node("3", "button", name="Search", bid="b-1"),
    )
    session = _ScriptedSession(axtrees=[axtree])
    result = execute_rule(
        rule,
        page_url="https://shop/",
        derived_query=None,
        states_dir=tmp_path,
        state_id="cart-1",
        llm_client=None,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=None,
    )
    assert result.outcome == "no_target"
    assert result.bid is None
    assert not list(tmp_path.iterdir())  # no artifacts written
    assert session.goto_calls == ["https://shop/"]


def test_execute_rule_returns_no_diff_when_fingerprint_unchanged(
    tmp_path: Path,
    patch_get_elem_by_bid: _StubLocator,
) -> None:
    """Identical pre/post axtrees → no_diff, LLM not consulted."""
    rule = _rule_for_homepage_cart()
    axtree = _homepage_axtree()
    session = _ScriptedSession(axtrees=[axtree, axtree], screenshots=[b"pre", b"post"])
    page = _StubPage()
    client = _FakeVisionClient(_good_response())  # should NOT be called

    result = execute_rule(
        rule,
        page_url="https://shop/",
        derived_query=None,
        states_dir=tmp_path,
        state_id="cart-1",
        llm_client=client,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=page,  # type: ignore[arg-type]
    )

    assert result.outcome == "no_diff"
    assert result.bid == "header-cart-1"
    assert client.calls == []  # no LLM call on no_diff
    assert patch_get_elem_by_bid.invocations == [("click", ())]
    assert (tmp_path / "cart-1.pre.png").read_bytes() == b"pre"
    assert (tmp_path / "cart-1.post.png").read_bytes() == b"post"
    assert not (tmp_path / "cart-1.json").exists()


def test_execute_rule_fires_and_writes_artifact_on_diff(
    tmp_path: Path,
    patch_get_elem_by_bid: _StubLocator,
) -> None:
    """Happy path: diff fires, LLM is called, artifact is persisted."""
    rule = _rule_for_homepage_cart()
    pre = _homepage_axtree()
    drawer_node = _node("99", "dialog", name="Cart", bid="drawer-1")
    post = _homepage_axtree(extra_nodes=[drawer_node])
    session = _ScriptedSession(axtrees=[pre, post], screenshots=[b"PNGpre", b"PNGpost"])
    page = _StubPage()
    client = _FakeVisionClient(_good_response(), model_name="fake-claude")

    result = execute_rule(
        rule,
        page_url="https://shop/",
        derived_query=None,
        states_dir=tmp_path,
        state_id="cart-1",
        llm_client=client,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=page,  # type: ignore[arg-type]
        temperature=0.0,
    )

    assert result.outcome == "fired"
    assert result.state == "cart_drawer"
    assert result.bid == "header-cart-1"
    assert result.parse_errors == ()
    assert result.artifact_path == tmp_path / "cart-1.json"
    assert page.wait_calls == [("networkidle", DEFAULT_NETWORKIDLE_TIMEOUT_MS)]
    assert patch_get_elem_by_bid.invocations == [("click", ())]
    assert len(client.calls) == 1

    artifact = StateNameArtifact.model_validate(json.loads((tmp_path / "cart-1.json").read_text()))
    assert artifact.state == "cart_drawer"
    assert artifact.rule_id == rule.id
    assert artifact.expected_state == "cart_drawer"
    assert artifact.action == "click"
    assert artifact.model == "fake-claude"
    assert artifact.pre_screenshot == "cart-1.pre.png"
    assert artifact.post_screenshot == "cart-1.post.png"


def test_execute_rule_fill_branch_passes_derived_query(
    tmp_path: Path,
    patch_get_elem_by_bid: _StubLocator,
) -> None:
    """``fill`` rules forward the derived query into ``elem.fill``."""
    fill_rule = next(r for r in RULES if r.id == "homepage_predictive_search")
    # Searchbox lives in the banner so the rule's selector resolves.
    axtree_pre = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3"]),
        _node("3", "searchbox", name="Search", bid="search-input-1"),
    )
    axtree_post = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3", "4"]),
        _node("3", "searchbox", name="Search", bid="search-input-1"),
        _node("4", "listbox", name="Suggestions", bid="suggest-1"),
    )
    session = _ScriptedSession(axtrees=[axtree_pre, axtree_post], screenshots=[b"a", b"b"])
    page = _StubPage()
    client = _FakeVisionClient(
        VisionResponse(parsed={"state": "predictive_panel"}, raw_response="x"),
    )

    result = execute_rule(
        fill_rule,
        page_url="https://shop/",
        derived_query="linen shirt",
        states_dir=tmp_path,
        state_id="search-1",
        llm_client=client,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=page,  # type: ignore[arg-type]
    )

    assert result.outcome == "fired"
    assert result.state == "predictive_panel"
    assert patch_get_elem_by_bid.invocations == [("fill", ("linen shirt",))]


def test_execute_rule_hover_branch_dispatches_hover(
    tmp_path: Path,
    patch_get_elem_by_bid: _StubLocator,
) -> None:
    """``hover`` rules dispatch ``elem.hover()`` (used by ``homepage_open_mega_menu``)."""
    hover_rule = next(r for r in RULES if r.id == "homepage_open_mega_menu")
    # Primary nav landmark with a hoverable link inside; ``banner`` -> ``navigation``
    # -> ``link`` is the canonical Shopify shape.
    axtree_pre = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3"]),
        _node("3", "navigation", name="Primary", children=["4"]),
        _node("4", "link", name="Women", bid="nav-women-1"),
    )
    axtree_post = _axtree(
        _node("1", "RootWebArea", children=["2"]),
        _node("2", "banner", children=["3"]),
        _node("3", "navigation", name="Primary", children=["4"]),
        _node("4", "link", name="Women", bid="nav-women-1"),
        _node("5", "region", name="Mega menu", bid="mega-1"),
    )
    session = _ScriptedSession(axtrees=[axtree_pre, axtree_post], screenshots=[b"a", b"b"])
    page = _StubPage()
    client = _FakeVisionClient(
        VisionResponse(parsed={"state": "mega_menu"}, raw_response="x"),
    )

    result = execute_rule(
        hover_rule,
        page_url="https://shop/",
        derived_query=None,
        states_dir=tmp_path,
        state_id="mega-1",
        llm_client=client,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=page,  # type: ignore[arg-type]
    )

    assert result.outcome == "fired"
    assert result.state == "mega_menu"
    assert patch_get_elem_by_bid.invocations == [("hover", ())]


def test_execute_rule_records_exec_error_when_action_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Playwright failure during the action collapses to ``exec_error``."""
    rule = _rule_for_homepage_cart()
    axtree = _homepage_axtree()
    session = _ScriptedSession(axtrees=[axtree], screenshots=[b"pre"])
    page = _StubPage()

    from browsergym.core.action import utils

    def fake(_page: object, bid: str, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"detached for {bid}")

    monkeypatch.setattr(utils, "get_elem_by_bid", fake)

    result = execute_rule(
        rule,
        page_url="https://shop/",
        derived_query=None,
        states_dir=tmp_path,
        state_id="cart-1",
        llm_client=None,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=page,  # type: ignore[arg-type]
    )
    assert result.outcome == "exec_error"
    assert result.error is not None and "detached" in result.error
    assert (tmp_path / "cart-1.pre.png").exists()  # pre-screenshot was taken
    assert not (tmp_path / "cart-1.post.png").exists()
    assert not (tmp_path / "cart-1.json").exists()


def test_execute_rule_propagates_parse_errors_into_artifact(
    tmp_path: Path,
    patch_get_elem_by_bid: _StubLocator,
) -> None:
    """Malformed LLM response → state=no_change, parse_errors populated, artifact still written."""
    rule = _rule_for_homepage_cart()
    pre = _homepage_axtree()
    post = _homepage_axtree(extra_nodes=[_node("99", "dialog", name="Cart", bid="drawer-1")])
    session = _ScriptedSession(axtrees=[pre, post], screenshots=[b"a", b"b"])
    page = _StubPage()
    client = _FakeVisionClient(VisionResponse(parsed={"state": "totally-bogus"}, raw_response="x"))

    result = execute_rule(
        rule,
        page_url="https://shop/",
        derived_query=None,
        states_dir=tmp_path,
        state_id="cart-1",
        llm_client=client,
        goto=session.goto,
        axtree=session.axtree,
        screenshot_png=session.screenshot_png,
        page=page,  # type: ignore[arg-type]
    )
    assert result.outcome == "fired"
    assert result.state == "no_change"
    assert result.parse_errors

    artifact = StateNameArtifact.model_validate(json.loads((tmp_path / "cart-1.json").read_text()))
    assert artifact.state == "no_change"
    assert artifact.parse_errors


# ---------------------------------------------------------------------------
# Stateful pass orchestration: state_node_id, write_stateful_trace_lines,
# run_stateful_pass.
# ---------------------------------------------------------------------------


def test_state_node_id_uses_opaque_state_prefix() -> None:
    """Spec §5.5.2: state node ids start with ``state:`` so they cannot collide
    with URL-node ids (which start with ``/``)."""
    assert state_node_id("/", "cart_drawer") == "state:/:cart_drawer"
    assert state_node_id("/products/<*>", "variant_select_open") == (
        "state:/products/<*>:variant_select_open"
    )


def test_state_node_id_collapses_same_state_on_same_page() -> None:
    """Two attempts producing the same ``(page, state_name)`` pair share an id."""
    a = state_node_id("/", "cart_drawer")
    b = state_node_id("/", "cart_drawer")
    c = state_node_id("/products/<*>", "cart_drawer")
    assert a == b
    assert a != c


def test_write_stateful_trace_lines_emits_byte_stable_jsonl(tmp_path: Path) -> None:
    """Each attempt is one byte-stable JSON line tagged ``phase="stateful"``."""
    path = tmp_path / "trace.jsonl"
    attempts = [
        StatefulAttempt(
            rule_id="homepage_open_cart_drawer",
            page_class="homepage",
            page_url="https://shop/",
            outcome="fired",
            bid="a1",
            state="cart_drawer",
            state_node="state:/:cart_drawer",
            artifact="transition/node/state__home__cart_drawer/node.json",
        ),
        StatefulAttempt(
            rule_id="product_open_variant_select",
            page_class="product",
            page_url="https://shop/products/x",
            outcome="no_target",
        ),
    ]
    write_stateful_trace_lines(attempts, path, mode="w")
    lines = path.read_text("utf-8").splitlines()
    assert len(lines) == 2
    fired = json.loads(lines[0])
    assert fired["phase"] == STATEFUL_PHASE
    assert fired["rule_id"] == "homepage_open_cart_drawer"
    assert fired["state"] == "cart_drawer"
    assert fired["state_node"] == "state:/:cart_drawer"
    skipped = json.loads(lines[1])
    assert skipped["outcome"] == "no_target"
    assert skipped["state"] is None
    assert skipped["state_node"] is None
    assert skipped["artifact"] is None
    # No whitespace inside each line (deterministic separators).
    assert " " not in lines[0]
    assert " " not in lines[1]


def test_write_stateful_trace_lines_appends_to_existing_file(tmp_path: Path) -> None:
    """Default mode is append so structural-pass lines stay first on disk."""
    path = tmp_path / "trace.jsonl"
    path.write_text('{"phase":"bfs"}\n', encoding="utf-8")
    write_stateful_trace_lines(
        [
            StatefulAttempt(
                rule_id="r",
                page_class="homepage",
                page_url="https://shop/",
                outcome="no_target",
            ),
        ],
        path,
    )
    lines = path.read_text("utf-8").splitlines()
    assert json.loads(lines[0])["phase"] == "bfs"
    assert json.loads(lines[1])["phase"] == STATEFUL_PHASE


def _stub_canonical_id_for_url(url: str) -> str:
    """Tiny mirror of :func:`canonicalize.canonical_id_for_url` for hermetic tests."""
    if url.endswith("/"):
        return "/"
    if url.endswith("/cart"):
        return "/cart"
    if url.endswith("/search?q=linen"):
        return "/search"
    raise AssertionError(f"unhandled url {url!r}")


@dataclass
class _FakeLLM:
    """Tiny :class:`LLMVisionClient` stub that never gets called in these tests."""

    model: str = "claude-sonnet-4-6"

    def call(self, **_kwargs: Any) -> VisionResponse:
        msg = "_FakeLLM.call must not run when every rule is skipped/no_target"
        raise AssertionError(msg)


def test_run_stateful_pass_skips_rule_when_page_class_has_no_target(tmp_path: Path) -> None:
    """Rules whose page class has no measurable URL never run."""
    from shop_arena.env_eval.transition.graph import TransitionGraph

    graph = TransitionGraph()
    # ``page_targets`` only carries homepage; product/cart/search/collection rules
    # all silently skip because their bucket was ``not_found``.
    page_targets = {"homepage": "https://shop/"}
    visited: list[str] = []

    def _goto(url: str) -> None:
        visited.append(url)

    def _axtree() -> dict[str, Any]:
        return {"nodes": []}  # no banner/main, every selector returns None

    def _screenshot_png() -> bytes:
        return b"\x89PNG"

    attempts, llm_calls = run_stateful_pass(
        rules=tuple(r for r in RULES if r.page_class == "homepage"),
        page_targets=page_targets,
        derived_query="linen",
        graph=graph,
        states_dir=tmp_path / "states",
        llm_client=_FakeLLM(),
        goto=_goto,
        axtree=_axtree,
        screenshot_png=_screenshot_png,
        page=None,
        canonical_id_for_url=_stub_canonical_id_for_url,
        run_dir=tmp_path,
    )
    # 6 homepage rules: 4 originals + the v0.3 hover ``homepage_open_mega_menu``
    # + its v0.3 click variant ``homepage_click_mega_menu``.  All resolve to
    # ``no_target`` because the stub axtree has no banner / navigation landmark.
    assert len(attempts) == 6
    assert all(a.outcome == "no_target" for a in attempts)
    assert llm_calls == 0
    assert graph.nodes == {}


def test_run_stateful_pass_skips_fill_rule_without_derived_query(tmp_path: Path) -> None:
    """Spec §5.5.2: a fill rule is silently skipped when no query is available."""
    from shop_arena.env_eval.transition.graph import TransitionGraph

    graph = TransitionGraph()
    # Filter to the single homepage_predictive_search rule, which is ``fill`` +
    # ``needs_derived_query``.
    fill_rule = next(r for r in RULES if r.id == "homepage_predictive_search")
    attempts, llm_calls = run_stateful_pass(
        rules=[fill_rule],
        page_targets={"homepage": "https://shop/"},
        derived_query=None,
        graph=graph,
        states_dir=tmp_path / "states",
        llm_client=_FakeLLM(),
        goto=lambda _u: None,
        axtree=lambda: {"nodes": []},
        screenshot_png=lambda: b"",
        page=None,
        canonical_id_for_url=_stub_canonical_id_for_url,
        run_dir=tmp_path,
    )
    # No goto / no LLM call: the rule was gated out before either ran.
    assert len(attempts) == 1
    assert attempts[0].outcome == "skipped_no_query"
    assert llm_calls == 0
    assert not (tmp_path / "states").exists()


def test_run_stateful_pass_rule_filter_skips_without_goto_or_llm(tmp_path: Path) -> None:
    """``rule_filter`` returning False short-circuits a rule entirely.

    Spec §5.7 reuse contract: when an artifact already exists for a rule the
    pipeline-level reuse layer can pass a predicate that gates that rule out.
    The filtered rule must produce no goto, no trace line, and no LLM call;
    other rules still run normally.
    """
    from shop_arena.env_eval.transition.graph import TransitionGraph

    graph = TransitionGraph()
    rule = _rule_for_homepage_cart()
    other_rule = next(
        r for r in RULES if r.page_class == "homepage" and r.id != rule.id and r.action == "click"
    )
    page_targets = {"homepage": "https://shop/"}
    visited: list[str] = []

    def _goto(url: str) -> None:
        visited.append(url)

    def _axtree() -> dict[str, Any]:
        return {"nodes": []}  # selector cannot resolve → ``no_target``

    def _screenshot_png() -> bytes:
        return b"\x89PNG"

    attempts, llm_calls = run_stateful_pass(
        rules=[rule, other_rule],
        page_targets=page_targets,
        derived_query="linen",
        graph=graph,
        states_dir=tmp_path / "states",
        llm_client=_FakeLLM(),
        goto=_goto,
        axtree=_axtree,
        screenshot_png=_screenshot_png,
        page=None,
        canonical_id_for_url=_stub_canonical_id_for_url,
        run_dir=tmp_path,
        rule_filter=lambda r: r.id != rule.id,
    )
    # Only ``other_rule`` produced an attempt; the filtered rule never reached
    # ``goto`` / the LLM and left no trace.
    assert [a.rule_id for a in attempts] == [other_rule.id]
    assert visited == ["https://shop/"]  # only one rule navigated
    assert llm_calls == 0
    assert graph.nodes == {}


def test_modules_are_importable() -> None:
    """M0 layout marker preserved: ``transition.rules`` and ``transition.stateful`` import."""
    from shop_arena.env_eval.transition import rules

    assert rules.__name__ == "shop_arena.env_eval.transition.rules"
    assert stateful.__name__ == "shop_arena.env_eval.transition.stateful"
