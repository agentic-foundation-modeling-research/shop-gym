"""Frozen fixture tests for ``rubric/v1.2.yaml`` (spec ``web_probe_v1_2_advanced.md``).

The v1.2 rubric extends v1.1 with the 8-probe ``level: advanced`` behavioral
tier. These tests pin its version, the SHA-256 over the raw YAML bytes, the
new probe count, the per-category distribution (collection +4, product +2,
search +1, dynamics +1), and the structural invariants the loader cannot
enforce on its own (every advanced entry is ``authenticated=false`` /
``transactional=false``; every advanced probe lives under
``probes.<category>.*``).

Edits to ``rubric/v1.2.yaml`` MUST bump the version string AND update the
``EXPECTED_V1_2_HASH`` constant below — that is the whole point of pinning.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from shop_probe.rubric import compute_content_hash, load_rubric

# --------------------------------------------------------------------------- #
# Pinned fixture — bump together with rubric/v1.2.yaml.
# --------------------------------------------------------------------------- #

V1_2_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "src" / "shop_probe" / "rubric" / "v1.2.yaml"
)

EXPECTED_V1_2_HASH: str = "754c4e5300da29b8f8161574179ab5bfd4e31634604f51915550d156ae289804"
"""SHA-256 of ``rubric/v1.2.yaml`` raw bytes. Pin per spec §5.8."""

EXPECTED_V1_2_VERSION: str = "v1.2"

EXPECTED_V1_2_PROBE_COUNT: int = 74
"""66 v1.1 entries + 8 v1.2 advanced behavioral entries."""

EXPECTED_V1_2_ADVANCED_COUNT: int = 8
"""4 collection + 2 product + 1 search + 1 dynamics = 8 advanced probes."""

EXPECTED_V1_2_CATEGORY_COUNTS: dict[str, int] = {
    "site_shell": 6,
    "homepage": 5,
    "collection": 12,  # 8 v1 + 4 advanced
    "product": 12,  # 10 v1 + 2 advanced
    "search": 6,  # 5 v1 + 1 advanced
    "cart": 6,
    "i18n": 3,
    "floating": 3,
    "dynamics": 6,  # 5 v1 + 1 advanced
    "a11y": 6,
    "media": 4,
    "account": 3,
    "checkout": 2,
}

EXPECTED_V1_2_ADVANCED_IDS: frozenset[str] = frozenset(
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


def test_v1_2_yaml_exists() -> None:
    assert V1_2_PATH.is_file(), f"rubric file missing: {V1_2_PATH}"


def test_v1_2_content_hash_is_pinned() -> None:
    """Spec §5.8: rubric YAML is content-addressable across releases."""
    raw = V1_2_PATH.read_bytes()
    assert compute_content_hash(raw) == EXPECTED_V1_2_HASH


def test_v1_2_loads_via_loader() -> None:
    rubric = load_rubric(V1_2_PATH)
    assert rubric.version == EXPECTED_V1_2_VERSION
    assert rubric.content_hash == EXPECTED_V1_2_HASH


def test_v1_2_has_expected_probe_count() -> None:
    rubric = load_rubric(V1_2_PATH)
    assert len(rubric.entries) == EXPECTED_V1_2_PROBE_COUNT


def test_v1_2_category_distribution() -> None:
    """v1.1 categories preserved; collection / product / search / dynamics each grow."""
    rubric = load_rubric(V1_2_PATH)
    counts = dict(Counter(entry.category for entry in rubric.entries))
    assert counts == EXPECTED_V1_2_CATEGORY_COUNTS


def test_v1_2_advanced_entry_count() -> None:
    rubric = load_rubric(V1_2_PATH)
    advanced = [e for e in rubric.entries if e.level == "advanced"]
    assert len(advanced) == EXPECTED_V1_2_ADVANCED_COUNT


def test_v1_2_advanced_entry_ids() -> None:
    rubric = load_rubric(V1_2_PATH)
    advanced_ids = {e.id for e in rubric.entries if e.level == "advanced"}
    assert advanced_ids == EXPECTED_V1_2_ADVANCED_IDS


def test_v1_2_advanced_entries_are_unauthenticated_and_non_transactional() -> None:
    """Advanced probes ship without ``--include-auth`` (spec §Proposal §3)."""
    rubric = load_rubric(V1_2_PATH)
    for entry in rubric.entries:
        if entry.level == "advanced":
            assert entry.authenticated is False, entry.id
            assert entry.transactional is False, entry.id


def test_v1_2_advanced_probes_live_under_their_category_module() -> None:
    """Each advanced probe is resolvable as ``probes.<category>.<fn>``."""
    rubric = load_rubric(V1_2_PATH)
    for entry in rubric.entries:
        if entry.level == "advanced":
            assert entry.probe.startswith(f"probes.{entry.category}."), entry.probe


def test_v1_2_v1_1_slice_unchanged() -> None:
    """The 66 v1.1 entries (everything not ``level: advanced``) stay byte-identical
    in semantic meaning — same id set, same level, same auth/txn flags."""
    v1_1_path = V1_2_PATH.parent / "v1.1.yaml"
    v1_1 = load_rubric(v1_1_path)
    v1_2 = load_rubric(V1_2_PATH)
    v1_2_non_advanced = {e.id: e for e in v1_2.entries if e.level != "advanced"}
    v1_1_by_id = {e.id: e for e in v1_1.entries}
    assert set(v1_2_non_advanced) == set(v1_1_by_id)
    for eid, e1 in v1_1_by_id.items():
        e2 = v1_2_non_advanced[eid]
        assert e2.category == e1.category, eid
        assert e2.level == e1.level, eid
        assert e2.weight == e1.weight, eid
        assert e2.probe == e1.probe, eid
        assert e2.authenticated == e1.authenticated, eid
        assert e2.transactional == e1.transactional, eid


def test_v1_2_probe_callables_use_dotted_module_form() -> None:
    rubric = load_rubric(V1_2_PATH)
    for entry in rubric.entries:
        assert entry.probe.startswith("probes."), entry.probe
        assert entry.probe.count(".") >= 2, entry.probe  # noqa: PLR2004


def test_v1_2_probe_module_matches_category() -> None:
    """Each probe lives in ``probes.<category>.*``."""
    rubric = load_rubric(V1_2_PATH)
    for entry in rubric.entries:
        assert entry.probe.startswith(f"probes.{entry.category}."), entry.probe


def test_v1_2_entry_ids_are_unique() -> None:
    rubric = load_rubric(V1_2_PATH)
    ids = [entry.id for entry in rubric.entries]
    assert len(set(ids)) == len(ids)
