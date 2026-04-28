"""Tests for ``cohort.yaml`` + ``shop_probe.cohort`` loader (T2.4 acceptance — spec §7 M2, §8.2).

Covers:

* The shipped ``packages/shop_arena/src/shop_probe/cohort.yaml`` loads successfully via
  :func:`shop_probe.cohort.load_cohort`.
* The cohort matches the v1 shape required by spec §8.2: 3 sandbox/source
  pairs (hardware, hexclad, aloyoga) + 3 ``real_unpaired`` slots.
* Each ``pair_id`` ties exactly one ``sandbox`` and exactly one ``source``
  (the T2.4 gate check verbatim).
* ``load_cohort_bytes`` accepts in-memory YAML, rejects malformed YAML,
  rejects non-mapping top-level documents, and surfaces schema errors as
  :class:`CohortLoadError`.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from shop_probe.cohort import CohortLoadError, load_cohort, load_cohort_bytes
from shop_probe.targets import Cohort

# --------------------------------------------------------------------------- #
# Pinned fixture path — bumps together with cohort.yaml.
# --------------------------------------------------------------------------- #

COHORT_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "src" / "shop_probe" / "cohort.yaml"
)


_EXPECTED_PAIR_IDS: tuple[str, ...] = ("pair_hardware", "pair_hexclad", "pair_aloyoga")


# --------------------------------------------------------------------------- #
# Shipped cohort.yaml — structure + spec §8.2 invariants.
# --------------------------------------------------------------------------- #


def test_shipped_cohort_loads() -> None:
    cohort = load_cohort(COHORT_PATH)
    assert isinstance(cohort, Cohort)
    assert cohort.version == "0.1"


def test_shipped_cohort_has_three_pairs_and_three_real_unpaired() -> None:
    cohort = load_cohort(COHORT_PATH)
    assert tuple(p.id for p in cohort.pairs) == _EXPECTED_PAIR_IDS
    assert len(cohort.real_unpaired) == 3  # noqa: PLR2004 — spec §5.2 fixes this at 3.
    for target in cohort.real_unpaired:
        assert target.kind == "real_unpaired"
        assert target.pair_id is None


def test_shipped_cohort_pair_id_ties_exactly_one_sandbox_and_one_source() -> None:
    """T2.4 check verbatim: each ``pair_id`` ties exactly one sandbox + one source."""
    cohort = load_cohort(COHORT_PATH)
    by_pair_id_kind: Counter[tuple[str, str]] = Counter()
    for pair in cohort.pairs:
        # The Pair-level validator already enforces matching pair_id and kind
        # on its members; here we cross-check at the cohort level so a future
        # refactor that loosens Pair cannot silently break this gate.
        assert pair.source.pair_id == pair.id
        assert pair.sandbox.pair_id == pair.id
        by_pair_id_kind[(pair.id, pair.source.kind)] += 1
        by_pair_id_kind[(pair.id, pair.sandbox.kind)] += 1
    for pair_id in _EXPECTED_PAIR_IDS:
        assert by_pair_id_kind[(pair_id, "source")] == 1
        assert by_pair_id_kind[(pair_id, "sandbox")] == 1


def test_shipped_cohort_hardware_sandbox_url_matches_spec() -> None:
    """Spec §8.2 pins the hardware sandbox URL; protect against silent edits."""
    cohort = load_cohort(COHORT_PATH)
    pair = next(p for p in cohort.pairs if p.id == "pair_hardware")
    assert pair.source.base_url == "https://hardware.shopify.com"
    assert pair.sandbox.base_url == ("https://shop-arena-51aad95a-126018801413.us-central1.run.app")


# --------------------------------------------------------------------------- #
# Loader — error surface.
# --------------------------------------------------------------------------- #


def test_load_cohort_bytes_round_trips_minimal_payload() -> None:
    payload = b'version: "0.1"\npairs: []\nreal_unpaired: []\n'
    cohort = load_cohort_bytes(payload)
    assert cohort.version == "0.1"
    assert cohort.pairs == ()
    assert cohort.real_unpaired == ()


def test_load_cohort_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_cohort(tmp_path / "does_not_exist.yaml")


def test_load_cohort_bytes_rejects_malformed_yaml() -> None:
    with pytest.raises(CohortLoadError, match="failed to parse"):
        load_cohort_bytes(b"version: 0.1\n  pairs: [\n  - oops")


def test_load_cohort_bytes_rejects_non_mapping_top_level() -> None:
    with pytest.raises(CohortLoadError, match="must be a mapping"):
        load_cohort_bytes(b"- just\n- a\n- list\n")


def test_load_cohort_bytes_rejects_unknown_top_level_field() -> None:
    payload = b'version: "0.1"\npairs: []\nreal_unpaired: []\noops: true\n'
    with pytest.raises(CohortLoadError, match="failed schema validation"):
        load_cohort_bytes(payload)


def test_load_cohort_bytes_rejects_pair_without_matching_pair_id() -> None:
    payload = b"""\
version: "0.1"
pairs:
  - id: pair_hardware
    source:
      label: source/hardware
      base_url: https://hardware.shopify.com
      kind: source
      pair_id: pair_other
    sandbox:
      label: sandbox/hardware
      base_url: http://localhost:4000
      kind: sandbox
      pair_id: pair_hardware
real_unpaired: []
"""
    with pytest.raises(CohortLoadError, match=r"source\.pair_id must equal id"):
        load_cohort_bytes(payload)


def test_load_cohort_bytes_rejects_real_unpaired_with_pair_id() -> None:
    payload = b"""\
version: "0.1"
pairs: []
real_unpaired:
  - label: real/oops
    base_url: https://oops.example.com
    kind: real_unpaired
    pair_id: pair_oops
"""
    with pytest.raises(CohortLoadError, match="pair_id must be None"):
        load_cohort_bytes(payload)
