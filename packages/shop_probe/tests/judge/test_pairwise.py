"""Tests for ``shop_probe.judge.pairwise`` (T4.5 acceptance — spec §5.5 step 4).

The T4.5 gate from ``docs/impl/web_probe_implementation.md`` reads:

    Check: unit test asserts experimental + control populations are
    disjoint where required and that the 6-real-shop pool is honored.

Coverage:

* :class:`PairwisePair` schema — JSON round-trip, ``extra="forbid"``,
  member-distinctness, kind / pair_id invariants per spec §5.5 step 4.
* :func:`real_shop_pool` — 6 real shops (3 paired sources + 3 unpaired);
  no sandbox in the pool.
* :func:`build_experimental_pairs` — one pair per cohort pair, in order,
  ``(sandbox, source)`` member order.
* :func:`build_control_pairs` — sampled without replacement; only reals
  drawn from the pool; deterministic under seed; rejects negative count
  and counts that exceed the pool.
* :func:`build_task_pairs` — combines both populations; the disjointness
  invariant (no sandbox leaks into control pairs) holds end-to-end.
"""

from __future__ import annotations

import json
import random

import pytest
from pydantic import ValidationError

from shop_probe.judge.pairwise import (
    PairwisePair,
    build_control_pairs,
    build_experimental_pairs,
    build_task_pairs,
    real_shop_pool,
)
from shop_probe.targets import Cohort, Pair, Target, TargetKind

# --------------------------------------------------------------------------- #
# Fixture builders. The shipped ``cohort.yaml`` is a v0.1 stub with TBD URLs
# for hexclad / aloyoga sandboxes and the unpaired reals; we build a
# fully-populated cohort here so tests assert the 6-real-shop invariant
# without depending on those open questions.
# --------------------------------------------------------------------------- #

_PAIR_IDS: tuple[str, str, str] = ("pair_hardware", "pair_hexclad", "pair_aloyoga")


def _target(label: str, kind: TargetKind, pair_id: str | None = None) -> Target:
    return Target(
        label=label,
        base_url=f"https://{label.replace('/', '-')}.example",
        kind=kind,
        pair_id=pair_id,
    )


def _full_cohort() -> Cohort:
    pairs = tuple(
        Pair(
            id=pid,
            source=_target(f"source/{pid}", "source", pid),
            sandbox=_target(f"sandbox/{pid}", "sandbox", pid),
        )
        for pid in _PAIR_IDS
    )
    real_unpaired = tuple(_target(f"real/unpaired_{i}", "real_unpaired") for i in range(3))
    return Cohort(version="0.1", pairs=pairs, real_unpaired=real_unpaired)


# --------------------------------------------------------------------------- #
# PairwisePair schema.
# --------------------------------------------------------------------------- #


def test_pairwise_pair_round_trips_through_json() -> None:
    pair = build_experimental_pairs(_full_cohort())[0]
    payload = pair.model_dump(mode="json")
    assert PairwisePair.model_validate(payload) == pair
    assert PairwisePair.model_validate(json.loads(json.dumps(payload))) == pair


def test_pairwise_pair_rejects_unknown_field() -> None:
    pair = build_experimental_pairs(_full_cohort())[0]
    payload = pair.model_dump(mode="json")
    payload["extra"] = "nope"
    with pytest.raises(ValidationError):
        PairwisePair.model_validate(payload)


def test_pairwise_pair_rejects_unknown_condition() -> None:
    sandbox = _target("sandbox/x", "sandbox", "pair_x")
    source = _target("source/x", "source", "pair_x")
    with pytest.raises(ValidationError):
        PairwisePair.model_validate(
            {
                "pair_id": "pair_x",
                "condition": "weirdo",
                "members": (sandbox.model_dump(), source.model_dump()),
            }
        )


def test_pairwise_pair_rejects_identical_members() -> None:
    real = _target("source/x", "source", "pair_x")
    with pytest.raises(ValidationError):
        PairwisePair(pair_id="control_0", condition="control", members=(real, real))


def test_pairwise_pair_experimental_requires_sandbox_first_then_source() -> None:
    sandbox = _target("sandbox/x", "sandbox", "pair_x")
    source = _target("source/x", "source", "pair_x")
    # Reversed order must fail (we want canonical sandbox-first order).
    with pytest.raises(ValidationError):
        PairwisePair(pair_id="pair_x", condition="experimental", members=(source, sandbox))


def test_pairwise_pair_experimental_requires_pair_id_match() -> None:
    sandbox = _target("sandbox/x", "sandbox", "pair_x")
    source = _target("source/y", "source", "pair_y")
    with pytest.raises(ValidationError):
        PairwisePair(pair_id="pair_x", condition="experimental", members=(sandbox, source))


def test_pairwise_pair_control_rejects_sandbox_member() -> None:
    sandbox = _target("sandbox/x", "sandbox", "pair_x")
    real = _target("real/u", "real_unpaired")
    with pytest.raises(ValidationError):
        PairwisePair(pair_id="control_0", condition="control", members=(sandbox, real))


# --------------------------------------------------------------------------- #
# real_shop_pool.
# --------------------------------------------------------------------------- #


def test_real_shop_pool_is_six_paired_sources_plus_unpaired() -> None:
    cohort = _full_cohort()
    pool = real_shop_pool(cohort)

    assert len(pool) == 6  # noqa: PLR2004 — spec §5.2 fixes pool size at 6.
    paired_source_labels = {p.source.label for p in cohort.pairs}
    unpaired_labels = {t.label for t in cohort.real_unpaired}
    assert {t.label for t in pool} == paired_source_labels | unpaired_labels


def test_real_shop_pool_excludes_sandboxes() -> None:
    """Disjointness invariant: no sandbox in the real pool (spec §5.5 step 4)."""
    cohort = _full_cohort()
    sandbox_labels = {p.sandbox.label for p in cohort.pairs}
    pool_labels = {t.label for t in real_shop_pool(cohort)}
    assert pool_labels.isdisjoint(sandbox_labels)
    for member in real_shop_pool(cohort):
        assert member.kind in {"source", "real_unpaired"}


def test_real_shop_pool_order_is_paired_then_unpaired() -> None:
    cohort = _full_cohort()
    pool = real_shop_pool(cohort)
    expected = tuple(p.source.label for p in cohort.pairs) + tuple(
        t.label for t in cohort.real_unpaired
    )
    assert tuple(t.label for t in pool) == expected


# --------------------------------------------------------------------------- #
# build_experimental_pairs.
# --------------------------------------------------------------------------- #


def test_experimental_pairs_one_per_cohort_pair_in_order() -> None:
    cohort = _full_cohort()
    exp = build_experimental_pairs(cohort)

    assert tuple(p.pair_id for p in exp) == tuple(p.id for p in cohort.pairs)
    for cohort_pair, exp_pair in zip(cohort.pairs, exp, strict=True):
        assert exp_pair.condition == "experimental"
        assert exp_pair.members[0] == cohort_pair.sandbox
        assert exp_pair.members[1] == cohort_pair.source


def test_experimental_pairs_empty_when_no_cohort_pairs() -> None:
    cohort = Cohort(version="0.1", pairs=(), real_unpaired=())
    assert build_experimental_pairs(cohort) == ()


# --------------------------------------------------------------------------- #
# build_control_pairs.
# --------------------------------------------------------------------------- #


def test_control_pairs_sampled_without_replacement() -> None:
    """6-real-shop pool is honored: each real appears in exactly one pair."""
    cohort = _full_cohort()
    ctrl = build_control_pairs(cohort, count=3, rng=random.Random(7))

    member_labels = [m.label for p in ctrl for m in p.members]
    assert len(member_labels) == 6  # noqa: PLR2004 — spec §5.2 fixes pool size at 6.
    assert len(set(member_labels)) == 6  # noqa: PLR2004 — without replacement → 6 distinct.

    pool_labels = {t.label for t in real_shop_pool(cohort)}
    assert set(member_labels) == pool_labels


def test_control_pairs_only_draw_from_real_shop_pool() -> None:
    cohort = _full_cohort()
    sandbox_labels = {p.sandbox.label for p in cohort.pairs}
    ctrl = build_control_pairs(cohort, count=3, rng=random.Random(13))

    for pair in ctrl:
        assert pair.condition == "control"
        for member in pair.members:
            assert member.label not in sandbox_labels
            assert member.kind in {"source", "real_unpaired"}


def test_control_pairs_members_are_distinct_within_pair() -> None:
    cohort = _full_cohort()
    for seed in range(20):
        ctrl = build_control_pairs(cohort, count=3, rng=random.Random(seed))
        for pair in ctrl:
            assert pair.members[0].label != pair.members[1].label


def test_control_pairs_deterministic_under_same_seed() -> None:
    cohort = _full_cohort()
    a = build_control_pairs(cohort, count=3, rng=random.Random(42))
    b = build_control_pairs(cohort, count=3, rng=random.Random(42))
    assert a == b


def test_control_pairs_different_seed_yields_different_partition() -> None:
    cohort = _full_cohort()
    a = build_control_pairs(cohort, count=3, rng=random.Random(1))
    b = build_control_pairs(cohort, count=3, rng=random.Random(2))
    assert a != b


def test_control_pairs_count_zero_yields_empty() -> None:
    cohort = _full_cohort()
    assert build_control_pairs(cohort, count=0, rng=random.Random(0)) == ()


def test_control_pairs_rejects_negative_count() -> None:
    cohort = _full_cohort()
    with pytest.raises(ValueError, match="non-negative"):
        build_control_pairs(cohort, count=-1, rng=random.Random(0))


def test_control_pairs_rejects_count_exceeding_pool() -> None:
    cohort = _full_cohort()  # pool size = 6 → max count = 3.
    with pytest.raises(ValueError, match="real-shop pool"):
        build_control_pairs(cohort, count=4, rng=random.Random(0))


# --------------------------------------------------------------------------- #
# build_task_pairs — the T4.5 gate check.
# --------------------------------------------------------------------------- #


def test_build_task_pairs_default_three_experimental_three_control() -> None:
    cohort = _full_cohort()
    pairs = build_task_pairs(cohort, seed=0)

    exp = [p for p in pairs if p.condition == "experimental"]
    ctrl = [p for p in pairs if p.condition == "control"]
    assert len(exp) == 3  # noqa: PLR2004 — spec §5.5 step 4 fixes 3 experimental.
    assert len(ctrl) == 3  # noqa: PLR2004 — spec §5.5 step 4 fixes 3 control.
    # Experimental population precedes control population in the canonical
    # output (the wiring layer randomizes presentation order downstream).
    assert [p.condition for p in pairs] == [
        "experimental",
        "experimental",
        "experimental",
        "control",
        "control",
        "control",
    ]


def test_build_task_pairs_disjointness_invariants() -> None:
    """T4.5 gate: experimental + control populations are disjoint where required.

    "Disjoint where required" per spec §5.5 step 4:

    * No sandbox appears in any control pair (sandboxes are not part of
      the real-shop pool).
    * Within each control pair, the two members are distinct (sampled
      without replacement).
    * Across the control population, no real shop is reused (sampled
      without replacement from the 6-real pool).
    """
    cohort = _full_cohort()
    sandbox_labels = {p.sandbox.label for p in cohort.pairs}
    pool_labels = {t.label for t in real_shop_pool(cohort)}

    pairs = build_task_pairs(cohort, seed=99)
    control_pairs = [p for p in pairs if p.condition == "control"]

    # No sandbox leaks into the control population.
    control_member_labels: list[str] = []
    for pair in control_pairs:
        for member in pair.members:
            assert member.label not in sandbox_labels, (
                f"sandbox {member.label!r} leaked into control pair {pair.pair_id!r}"
            )
            assert member.label in pool_labels
            control_member_labels.append(member.label)

    # Sampled without replacement: every real used at most once.
    assert len(control_member_labels) == len(set(control_member_labels))


def test_build_task_pairs_deterministic_under_same_seed() -> None:
    cohort = _full_cohort()
    a = build_task_pairs(cohort, seed=5)
    b = build_task_pairs(cohort, seed=5)
    assert a == b


def test_build_task_pairs_control_count_override() -> None:
    cohort = _full_cohort()
    pairs = build_task_pairs(cohort, seed=0, control_count=2)
    ctrl = [p for p in pairs if p.condition == "control"]
    assert len(ctrl) == 2  # noqa: PLR2004 — control_count override under test.
    # 4 distinct reals drawn from the 6-pool.
    members = {m.label for p in ctrl for m in p.members}
    assert len(members) == 4  # noqa: PLR2004 — 2 control pairs * 2 members.
