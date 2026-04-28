"""Frozen fixture tests for ``rubric/v1.yaml`` (T1.4 — spec §7 M1, §5.3, §5.8).

The shipped rubric is the contract every :class:`ProbeReport` references
via ``rubric_version`` + ``rubric_hash`` (spec §5.6 / §5.8). These tests
pin the version, the SHA-256 over the raw YAML bytes, the M1 scope
(20 ``core`` probes across ``site_shell`` / ``collection`` / ``product`` /
``cart``), and the structural invariants the loader cannot enforce on its
own (every entry is ``core``, levels stay inside the M1 category whitelist,
no auth or transactional probes ship in v1 per spec §5.9).

Edits to ``rubric/v1.yaml`` MUST bump the version string AND update the
``EXPECTED_V1_HASH`` constant below — that is the whole point of pinning.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from shop_probe.rubric import compute_content_hash, load_rubric

# --------------------------------------------------------------------------- #
# Pinned fixture — bump together with rubric/v1.yaml.
# --------------------------------------------------------------------------- #

V1_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "src" / "shop_probe" / "rubric" / "v1.yaml"
)

EXPECTED_V1_HASH: str = "dca7e6a776460ed0eec20d2b11b9b7b89e0d30ce48fc90b656c017c09de0347e"
"""SHA-256 of ``rubric/v1.yaml`` raw bytes. Pin per spec §5.8."""

EXPECTED_V1_VERSION: str = "v1"

EXPECTED_V1_PROBE_COUNT: int = 61

EXPECTED_V1_CATEGORY_COUNTS: dict[str, int] = {
    "site_shell": 6,
    "homepage": 5,
    "collection": 8,
    "product": 10,
    "search": 5,
    "cart": 6,
    "i18n": 3,
    "floating": 3,
    "dynamics": 5,
    "a11y": 6,
    "media": 4,
}

EXPECTED_V1_LEVELS: set[str] = {"core", "modern"}
"""v1 ships only ``core`` + ``modern`` probes; ``advanced`` is dropped per spec §5.3."""


# --------------------------------------------------------------------------- #
# Hash + structural pinning
# --------------------------------------------------------------------------- #


def test_v1_yaml_exists() -> None:
    assert V1_PATH.is_file(), f"rubric file missing: {V1_PATH}"


def test_v1_content_hash_is_pinned() -> None:
    """Spec §5.8: rubric YAML is content-addressable across releases."""
    raw = V1_PATH.read_bytes()
    assert compute_content_hash(raw) == EXPECTED_V1_HASH


def test_v1_loads_via_loader() -> None:
    rubric = load_rubric(V1_PATH)
    assert rubric.version == EXPECTED_V1_VERSION
    assert rubric.content_hash == EXPECTED_V1_HASH


def test_v1_has_expected_probe_count() -> None:
    """Spec §7 M3: v1 ships 61 probes after the M3 expansion."""
    rubric = load_rubric(V1_PATH)
    assert len(rubric.entries) == EXPECTED_V1_PROBE_COUNT


def test_v1_drops_advanced_level() -> None:
    """v1 ships ``core`` + ``modern`` only; ``advanced`` is dropped per spec §5.3."""
    rubric = load_rubric(V1_PATH)
    levels = {entry.level for entry in rubric.entries}
    assert levels == EXPECTED_V1_LEVELS


def test_v1_category_distribution() -> None:
    """Spec §5.3: v1 covers all 11 categories with the M3 distribution."""
    rubric = load_rubric(V1_PATH)
    counts = dict(Counter(entry.category for entry in rubric.entries))
    assert counts == EXPECTED_V1_CATEGORY_COUNTS


def test_v1_all_entries_are_unauthenticated_and_nontransactional() -> None:
    """Spec §5.9: auth + transactional probes are deferred to v1.1."""
    rubric = load_rubric(V1_PATH)
    for entry in rubric.entries:
        assert entry.authenticated is False, entry.id
        assert entry.transactional is False, entry.id


def test_v1_probe_callables_use_dotted_module_form() -> None:
    """Spec §5.3: ``probe`` is a dotted reference resolved by the runner."""
    rubric = load_rubric(V1_PATH)
    for entry in rubric.entries:
        # e.g. "probes.product.has_title" — module + at least one segment.
        assert entry.probe.startswith("probes."), entry.probe
        assert entry.probe.count(".") >= 2, entry.probe  # noqa: PLR2004


def test_v1_probe_module_matches_category() -> None:
    """Each probe lives in ``probes.<category>.*`` for the M1 slice."""
    rubric = load_rubric(V1_PATH)
    for entry in rubric.entries:
        assert entry.probe.startswith(f"probes.{entry.category}."), entry.probe


def test_v1_entry_ids_are_unique() -> None:
    """The Rubric model already enforces this, but pin it as a contract."""
    rubric = load_rubric(V1_PATH)
    ids = [entry.id for entry in rubric.entries]
    assert len(set(ids)) == len(ids)
