"""Frozen fixture tests for ``rubric/v1.3.yaml`` (spec ``web_probe_v1_3_agent_driven.md``).

The v1.3 rubric replaces the v1.2 deterministic ``advanced`` tier with 8
``level: agent_driven`` entries that carry inline ``agent_task`` blocks
instead of dotted ``probe`` references. These tests pin its version, the
SHA-256 over the raw YAML bytes, the new probe count, the agent-driven
distribution (collection +4, product +2, search +1, dynamics +1), and the
structural invariants the loader cannot enforce on its own (every
agent-driven entry is ``authenticated=false`` / ``transactional=false``;
every agent-driven entry has a non-``None`` ``agent_task`` block; total
``agent_driven`` weight equals v1.2 ``advanced`` weight = 14).

Edits to ``rubric/v1.3.yaml`` MUST bump the version string AND update the
``EXPECTED_V1_3_HASH`` constant below — that is the whole point of pinning.
"""

from __future__ import annotations

from pathlib import Path

from shop_probe.rubric import compute_content_hash, load_rubric

# --------------------------------------------------------------------------- #
# Pinned fixture — bump together with rubric/v1.3.yaml.
# --------------------------------------------------------------------------- #

V1_3_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "src" / "shop_probe" / "rubric" / "v1.3.yaml"
)

EXPECTED_V1_3_HASH: str = "f3d0dd66a40f682a5131ff554da59a36f9752833e44441f225ff8967bd8f785c"
"""SHA-256 of ``rubric/v1.3.yaml`` raw bytes. Pin per spec §5.8."""

EXPECTED_V1_3_VERSION: str = "v1.3"

EXPECTED_V1_3_PROBE_COUNT: int = 74
"""66 v1.1 entries + 8 v1.3 agent-driven entries."""

EXPECTED_V1_3_AGENT_DRIVEN_COUNT: int = 8
"""4 collection + 2 product + 1 search + 1 dynamics = 8 agent-driven probes."""

EXPECTED_V1_3_AGENT_DRIVEN_WEIGHT: int = 14
"""Total weight of agent-driven entries; matches v1.2 advanced (slot stable)."""

EXPECTED_V1_3_AGENT_DRIVEN_IDS: frozenset[str] = frozenset(
    {
        "collection.sort.changes_order",
        "collection.filters.applies_to_results",
        "collection.pagination.advances",
        "collection.filters.url_state_advances",
        "product.variant.swap_updates_state",
        "product.qty.spinner_increments",
        "search.predictive.populates_listbox",
        "dynamics.cart_count_badge_updates",
    }
)


# --------------------------------------------------------------------------- #
# Hash + structural pinning
# --------------------------------------------------------------------------- #


def test_v1_3_yaml_exists() -> None:
    assert V1_3_PATH.is_file(), f"rubric file missing: {V1_3_PATH}"


def test_v1_3_content_hash_is_pinned() -> None:
    """Spec §5.8: rubric YAML is content-addressable across releases."""
    raw = V1_3_PATH.read_bytes()
    assert compute_content_hash(raw) == EXPECTED_V1_3_HASH


def test_v1_3_loads_via_loader() -> None:
    rubric = load_rubric(V1_3_PATH)
    assert rubric.version == EXPECTED_V1_3_VERSION
    assert rubric.content_hash == EXPECTED_V1_3_HASH


def test_v1_3_has_expected_probe_count() -> None:
    rubric = load_rubric(V1_3_PATH)
    assert len(rubric.entries) == EXPECTED_V1_3_PROBE_COUNT


def test_v1_3_agent_driven_entry_count() -> None:
    rubric = load_rubric(V1_3_PATH)
    agent_driven = [e for e in rubric.entries if e.level == "agent_driven"]
    assert len(agent_driven) == EXPECTED_V1_3_AGENT_DRIVEN_COUNT


def test_v1_3_agent_driven_entry_ids() -> None:
    rubric = load_rubric(V1_3_PATH)
    ids = {e.id for e in rubric.entries if e.level == "agent_driven"}
    assert ids == EXPECTED_V1_3_AGENT_DRIVEN_IDS


def test_v1_3_agent_driven_entries_are_unauthenticated_and_non_transactional() -> None:
    """Agent-driven entries ship without ``--include-auth`` (spec §Proposal)."""
    rubric = load_rubric(V1_3_PATH)
    for entry in rubric.entries:
        if entry.level == "agent_driven":
            assert entry.authenticated is False, entry.id
            assert entry.transactional is False, entry.id


def test_v1_3_agent_driven_entries_carry_inline_block() -> None:
    """Each ``level: agent_driven`` entry has a non-None inline ``agent_task``."""
    rubric = load_rubric(V1_3_PATH)
    for entry in rubric.entries:
        if entry.level == "agent_driven":
            assert entry.agent_task is not None, entry.id
            assert entry.probe is None, entry.id
            assert entry.agent_task.goal.strip(), entry.id
            assert entry.agent_task.judge_prompt.strip(), entry.id


def test_v1_3_agent_driven_total_weight_matches_v1_2_advanced() -> None:
    """Slot stability: total agent-driven weight = v1.2 advanced weight = 14."""
    rubric = load_rubric(V1_3_PATH)
    total = sum(e.weight for e in rubric.entries if e.level == "agent_driven")
    assert total == EXPECTED_V1_3_AGENT_DRIVEN_WEIGHT


def test_v1_3_v1_1_slice_unchanged() -> None:
    """The 66 v1.1 entries (everything not agent-driven) stay semantically identical:
    same id set, same level, same probe ref, same auth/txn flags."""
    v1_1_path = V1_3_PATH.parent / "v1.1.yaml"
    v1_1 = load_rubric(v1_1_path)
    v1_3 = load_rubric(V1_3_PATH)
    v1_3_non_agent = {e.id: e for e in v1_3.entries if e.level != "agent_driven"}
    v1_1_by_id = {e.id: e for e in v1_1.entries}
    assert set(v1_3_non_agent) == set(v1_1_by_id)
    for eid, e1 in v1_1_by_id.items():
        e3 = v1_3_non_agent[eid]
        assert e3.category == e1.category, eid
        assert e3.level == e1.level, eid
        assert e3.weight == e1.weight, eid
        assert e3.probe == e1.probe, eid
        assert e3.authenticated == e1.authenticated, eid
        assert e3.transactional == e1.transactional, eid


def test_v1_3_entry_ids_are_unique() -> None:
    rubric = load_rubric(V1_3_PATH)
    ids = [entry.id for entry in rubric.entries]
    assert len(set(ids)) == len(ids)
