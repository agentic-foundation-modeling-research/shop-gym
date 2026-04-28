"""Blinded pairwise pair construction (T4.5 — spec §5.5 step 4).

The axis-C judge consumes two pair populations per task (spec §5.5 step 4):

* **Experimental pairs** — one ``(sandbox_i, source_i)`` per ``pair_id`` in
  the cohort (3 per task in v1). The judge's pick rate on these pairs is
  the headline indistinguishability number.
* **Control pairs** — ``(real_a, real_b)`` pairs sampled without
  replacement from the 6-real-shop pool (3 per task in v1). The pool is
  the union of paired sources and unpaired reals (spec §5.2). Both
  members of a control pair are real, so no answer is correct — the
  judge's pick distribution is the diagnostic noise floor.

Per spec §5.5 step 5 the judge sees both populations under the same
prompt and does not know which condition it is in. That isolation is
enforced by callers (T4.6 / T4.7 wiring); this module is concerned only
with constructing the pairs.

Position randomization (spec §5.5 step 5) and the swap-consistency check
(spec §5.5 step 6) are downstream of pair construction. This module
returns canonical, unswapped pairs so those layers have a stable input
to operate on.

The module is import-safe — no I/O at import time. Sampling
non-determinism is fully controlled by the caller-supplied
:class:`random.Random` instance (or ``seed`` int) so cohort runs are
reproducible.
"""

from __future__ import annotations

import random
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shop_probe.targets import Cohort, Target

PairCondition = Literal["experimental", "control"]
"""Whether a pair is an experimental ``(sandbox, source)`` pair or a control
``(real, real)`` pair (spec §5.5 step 4)."""


class PairwisePair(BaseModel):
    """One pair fed to the blinded pairwise judge (spec §5.5 step 4).

    Canonical (unswapped) form. The presentation layer (T4.6) is
    responsible for randomizing A/B order and recording ``truth`` on the
    resulting :class:`shop_probe.report.JudgeCall`.

    Invariants enforced at validation time:

    * Members are distinct (no shop paired with itself).
    * For ``condition="experimental"``: ``members[0].kind == "sandbox"``,
      ``members[1].kind == "source"``, and both share ``pair_id ==
      pair_id``.
    * For ``condition="control"``: both members have kind in
      ``{"source", "real_unpaired"}`` — i.e. no sandbox leaks into the
      control population (the spec §5.5 step 4 disjointness invariant).

    Attributes:
        pair_id: Stable identifier for the pair. Equal to the cohort
            ``pair_id`` for experimental pairs, e.g. ``"pair_1"``;
            an opaque ``"control_<i>"`` token for control pairs.
        condition: Pair population (see :data:`PairCondition`).
        members: The two storefronts presented to the judge, in
            canonical order (sandbox-first for experimental, sample
            order for control).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: str = Field(min_length=1)
    condition: PairCondition
    members: tuple[Target, Target]

    @model_validator(mode="after")
    def _check_members(self) -> PairwisePair:
        """Enforce the spec §5.5 step 4 invariants."""
        first, second = self.members
        if first.label == second.label:
            msg = f"pair {self.pair_id!r}: members must be distinct (got {first.label!r} twice)"
            raise ValueError(msg)
        if self.condition == "experimental":
            if first.kind != "sandbox":
                msg = (
                    f"pair {self.pair_id!r}: experimental members[0].kind must be "
                    f"'sandbox' (got {first.kind!r} on {first.label!r})"
                )
                raise ValueError(msg)
            if second.kind != "source":
                msg = (
                    f"pair {self.pair_id!r}: experimental members[1].kind must be "
                    f"'source' (got {second.kind!r} on {second.label!r})"
                )
                raise ValueError(msg)
            if first.pair_id != self.pair_id or second.pair_id != self.pair_id:
                msg = (
                    f"pair {self.pair_id!r}: experimental member pair_ids must "
                    f"equal pair_id (got sandbox={first.pair_id!r}, "
                    f"source={second.pair_id!r})"
                )
                raise ValueError(msg)
        else:
            for member in (first, second):
                if member.kind not in {"source", "real_unpaired"}:
                    msg = (
                        f"pair {self.pair_id!r}: control members must have kind in "
                        f"{{'source', 'real_unpaired'}} (got {member.kind!r} on "
                        f"{member.label!r})"
                    )
                    raise ValueError(msg)
        return self


def real_shop_pool(cohort: Cohort) -> tuple[Target, ...]:
    """Return the 6-real-shop pool (spec §5.2).

    The pool is the union of paired sources (in cohort.pairs order) and
    unpaired reals (in cohort.real_unpaired order). Sandboxes are
    excluded — that exclusion is the spec §5.5 step 4 disjointness
    invariant control pairs rely on.

    Args:
        cohort: The validated cohort.

    Returns:
        Pool of real targets, in stable order.
    """
    return tuple(pair.source for pair in cohort.pairs) + tuple(cohort.real_unpaired)


def build_experimental_pairs(cohort: Cohort) -> tuple[PairwisePair, ...]:
    """Build experimental ``(sandbox, source)`` pairs (spec §5.5 step 4).

    Deterministic — one pair per ``pair_id`` in cohort order. No
    randomization (the spec §5.5 step 5 A/B randomization is downstream
    of this).

    Args:
        cohort: The validated cohort.

    Returns:
        One :class:`PairwisePair` per cohort pair, with members in
        ``(sandbox, source)`` order.
    """
    return tuple(
        PairwisePair(
            pair_id=pair.id,
            condition="experimental",
            members=(pair.sandbox, pair.source),
        )
        for pair in cohort.pairs
    )


def build_control_pairs(
    cohort: Cohort,
    *,
    count: int = 3,
    rng: random.Random,
) -> tuple[PairwisePair, ...]:
    """Sample control ``(real, real)`` pairs without replacement (spec §5.5 step 4).

    The pool is the 6 real shops returned by :func:`real_shop_pool`.
    Sampling is without replacement *across the returned pairs*: every
    real shop appears in at most one pair, so for ``count == 3`` the
    pool is partitioned exactly. Within each pair the two members are
    distinct by construction.

    Args:
        cohort: The validated cohort.
        count: Number of control pairs to construct (3 in v1).
        rng: Random source. Pass ``random.Random(seed)`` for
            reproducible sampling across cohort runs.

    Returns:
        ``count`` control pairs sampled from the real-shop pool.

    Raises:
        ValueError: ``count`` is negative, or ``2 * count`` exceeds the
            real-shop pool size.
    """
    if count < 0:
        msg = f"control pair count must be non-negative (got {count})"
        raise ValueError(msg)
    pool = list(real_shop_pool(cohort))
    if 2 * count > len(pool):
        msg = (
            f"control pair count {count} requires {2 * count} reals; "
            f"cohort real-shop pool has {len(pool)}"
        )
        raise ValueError(msg)
    rng.shuffle(pool)
    pairs: list[PairwisePair] = []
    for i in range(count):
        first = pool[2 * i]
        second = pool[2 * i + 1]
        pairs.append(
            PairwisePair(
                pair_id=f"control_{i}",
                condition="control",
                members=(first, second),
            )
        )
    return tuple(pairs)


def build_task_pairs(
    cohort: Cohort,
    *,
    seed: int,
    control_count: int = 3,
) -> tuple[PairwisePair, ...]:
    """Build the full pair population for one judge task (spec §5.5 step 4).

    Concatenates :func:`build_experimental_pairs` (deterministic) with
    :func:`build_control_pairs` (seeded). The combined sequence is the
    per-task input the judge wiring (T4.6) hands to the prompt
    template. The judge does not see the ``condition`` field — that is
    the diagnostic axis used at scoring time (spec §5.5 step 7).

    Args:
        cohort: The validated cohort.
        seed: Seed for the control-pair sampler. Embed alongside the
            judge run metadata so the partition is reproducible.
        control_count: Number of control pairs (3 in v1).

    Returns:
        Experimental pairs (in cohort order) followed by control pairs
        (in sample order).
    """
    rng = random.Random(seed)
    return build_experimental_pairs(cohort) + build_control_pairs(
        cohort, count=control_count, rng=rng
    )
