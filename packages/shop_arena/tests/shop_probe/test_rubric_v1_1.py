"""Frozen fixture tests for ``rubric/v1.1.yaml`` (T7.4 — spec §5.9, §7 M7).

The v1.1 rubric extends v1 with the auth + transactional surface that v1
deliberately omits (spec §5.9). These tests pin its version, the SHA-256
over the raw YAML bytes, the new probe count, the new categories
(``account``, ``checkout``), and the structural invariants the loader
cannot enforce on its own.

Edits to ``rubric/v1.1.yaml`` MUST bump the version string AND update the
``EXPECTED_V1_1_HASH`` constant below — that is the whole point of pinning.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from shop_probe.rubric import compute_content_hash, load_rubric

# --------------------------------------------------------------------------- #
# Pinned fixture — bump together with rubric/v1.1.yaml.
# --------------------------------------------------------------------------- #

V1_1_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "src" / "shop_probe" / "rubric" / "v1.1.yaml"
)

EXPECTED_V1_1_HASH: str = "83847a5520b5b77e2dcc0a32869124c42e91b77f89932dfd65ef0b07164b71dd"
"""SHA-256 of ``rubric/v1.1.yaml`` raw bytes. Pin per spec §5.8."""

EXPECTED_V1_1_VERSION: str = "v1.1"

EXPECTED_V1_1_PROBE_COUNT: int = 66
"""61 v1 entries + 5 v1.1 auth + transactional entries (T7.4)."""

EXPECTED_V1_1_CATEGORY_COUNTS: dict[str, int] = {
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
    "account": 3,
    "checkout": 2,
}

EXPECTED_V1_1_AUTH_COUNT: int = 3
"""account.* probes: login form, signup form, account page."""

EXPECTED_V1_1_TRANSACTIONAL_COUNT: int = 2
"""checkout.* probes: cart -> checkout flow, checkout page."""


# --------------------------------------------------------------------------- #
# Hash + structural pinning
# --------------------------------------------------------------------------- #


def test_v1_1_yaml_exists() -> None:
    assert V1_1_PATH.is_file(), f"rubric file missing: {V1_1_PATH}"


def test_v1_1_content_hash_is_pinned() -> None:
    """Spec §5.8: rubric YAML is content-addressable across releases."""
    raw = V1_1_PATH.read_bytes()
    assert compute_content_hash(raw) == EXPECTED_V1_1_HASH


def test_v1_1_loads_via_loader() -> None:
    rubric = load_rubric(V1_1_PATH)
    assert rubric.version == EXPECTED_V1_1_VERSION
    assert rubric.content_hash == EXPECTED_V1_1_HASH


def test_v1_1_has_expected_probe_count() -> None:
    rubric = load_rubric(V1_1_PATH)
    assert len(rubric.entries) == EXPECTED_V1_1_PROBE_COUNT


def test_v1_1_category_distribution() -> None:
    """Spec §5.3 + §5.9: v1 categories unchanged, plus account + checkout in v1.1."""
    rubric = load_rubric(V1_1_PATH)
    counts = dict(Counter(entry.category for entry in rubric.entries))
    assert counts == EXPECTED_V1_1_CATEGORY_COUNTS


def test_v1_1_authenticated_entries_are_account_only() -> None:
    """Auth flag is set only on the account.* entries (T7.4)."""
    rubric = load_rubric(V1_1_PATH)
    auth_entries = [e for e in rubric.entries if e.authenticated]
    assert len(auth_entries) == EXPECTED_V1_1_AUTH_COUNT
    for entry in auth_entries:
        assert entry.category == "account", entry.id
        assert entry.transactional is False, entry.id


def test_v1_1_transactional_entries_are_checkout_only() -> None:
    """Transactional flag is set only on the checkout.* entries (T7.4)."""
    rubric = load_rubric(V1_1_PATH)
    txn_entries = [e for e in rubric.entries if e.transactional]
    assert len(txn_entries) == EXPECTED_V1_1_TRANSACTIONAL_COUNT
    for entry in txn_entries:
        assert entry.category == "checkout", entry.id
        assert entry.authenticated is False, entry.id


def test_v1_1_v1_slice_remains_unflagged() -> None:
    """The 61 v1 entries stay ``authenticated=false`` and ``transactional=false``."""
    rubric = load_rubric(V1_1_PATH)
    v1_categories = {
        "site_shell",
        "homepage",
        "collection",
        "product",
        "search",
        "cart",
        "i18n",
        "floating",
        "dynamics",
        "a11y",
        "media",
    }
    for entry in rubric.entries:
        if entry.category in v1_categories:
            assert entry.authenticated is False, entry.id
            assert entry.transactional is False, entry.id


def test_v1_1_probe_callables_use_dotted_module_form() -> None:
    rubric = load_rubric(V1_1_PATH)
    for entry in rubric.entries:
        assert entry.probe.startswith("probes."), entry.probe
        assert entry.probe.count(".") >= 2, entry.probe  # noqa: PLR2004


def test_v1_1_probe_module_matches_category() -> None:
    """Each probe lives in ``probes.<category>.*``."""
    rubric = load_rubric(V1_1_PATH)
    for entry in rubric.entries:
        assert entry.probe.startswith(f"probes.{entry.category}."), entry.probe


def test_v1_1_entry_ids_are_unique() -> None:
    rubric = load_rubric(V1_1_PATH)
    ids = [entry.id for entry in rubric.entries]
    assert len(set(ids)) == len(ids)
