"""Target and Cohort schemas for ShopProbe.

Implements the typed I/O contract documented in
``docs/specs/shop_arena/web_probe.md`` §5.2:

* :class:`Target` — a deployed storefront under test (sandbox, source, or
  unpaired real). The ``pair_id`` field links a ``sandbox`` row to its
  paired ``source`` row and is ``None`` on ``real_unpaired`` rows.
* :class:`Pair` — one ``(source, sandbox)`` calibration pair.
* :class:`Cohort` — the v1 cohort: 3 sandbox/source pairs + 3 unpaired
  real shops; mirrors the YAML structure sketched in spec §8.2.

The module is import-safe: it performs no I/O at import time. YAML
loading lives in a sibling module added in T2.4 (spec §7 M2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TargetKind = Literal["sandbox", "source", "real_unpaired"]
"""Storefront role within the cohort (spec §5.2).

* ``sandbox`` — a SandboxShop served by ``shop_backend``.
* ``source`` — the production storefront a sandbox was calibrated on.
* ``real_unpaired`` — a production storefront with no paired sandbox;
  contributes to the real-shop reference population.
"""


class Target(BaseModel):
    """A deployed storefront under test.

    See spec §5.2. The ``pair_id`` field is required to be a non-empty
    string on ``sandbox`` and ``source`` rows, and required to be
    ``None`` on ``real_unpaired`` rows.

    Attributes:
        label: Human-readable identifier, e.g. ``"sandbox/hardware_run123"``,
            ``"source/hardware"``, ``"real/aloyoga"``.
        base_url: Base URL of the storefront. Crawls and probes are
            rooted here.
        kind: Storefront role (see :data:`TargetKind`).
        pair_id: Pair identifier shared with the corresponding ``source``
            (resp. ``sandbox``) row. ``None`` iff ``kind`` is
            ``real_unpaired``.
        notes: Free-form operator notes; ``None`` if unset.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    kind: TargetKind
    pair_id: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_pair_id_matches_kind(self) -> Target:
        """Enforce the ``pair_id`` ↔ ``kind`` invariant from spec §5.2."""
        if self.kind == "real_unpaired":
            if self.pair_id is not None:
                msg = (
                    f"target {self.label!r}: pair_id must be None when "
                    f"kind='real_unpaired' (got {self.pair_id!r})"
                )
                raise ValueError(msg)
        elif self.pair_id is None or not self.pair_id:
            msg = (
                f"target {self.label!r}: pair_id is required and must be "
                f"non-empty when kind={self.kind!r}"
            )
            raise ValueError(msg)
        return self


class Pair(BaseModel):
    """One ``(source, sandbox)`` calibration pair.

    Mirrors the per-pair YAML block from spec §8.2. Both members must
    share ``pair_id == id`` and have the matching :attr:`Target.kind`.

    Attributes:
        id: Stable pair identifier, e.g. ``"pair_hardware"``. Used as
            the ``pair_id`` on both members.
        source: The production storefront row (``kind="source"``).
        sandbox: The SandboxShop row (``kind="sandbox"``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    source: Target
    sandbox: Target

    @model_validator(mode="after")
    def _check_members(self) -> Pair:
        """Enforce kind + pair_id consistency between ``id`` and members."""
        if self.source.kind != "source":
            msg = f"pair {self.id!r}: source.kind must be 'source' (got {self.source.kind!r})"
            raise ValueError(msg)
        if self.sandbox.kind != "sandbox":
            msg = f"pair {self.id!r}: sandbox.kind must be 'sandbox' (got {self.sandbox.kind!r})"
            raise ValueError(msg)
        if self.source.pair_id != self.id:
            msg = f"pair {self.id!r}: source.pair_id must equal id (got {self.source.pair_id!r})"
            raise ValueError(msg)
        if self.sandbox.pair_id != self.id:
            msg = f"pair {self.id!r}: sandbox.pair_id must equal id (got {self.sandbox.pair_id!r})"
            raise ValueError(msg)
        return self


class Cohort(BaseModel):
    """The v1 ShopProbe cohort.

    Mirrors the YAML structure in spec §8.2: a version string, a list
    of sandbox/source pairs, and a list of unpaired real shops.

    Cross-pair invariants enforced here:

    * pair ids are unique within the cohort;
    * every ``real_unpaired`` entry has the matching kind (already
      enforced at the :class:`Target` level).

    Attributes:
        version: Cohort schema version (e.g. ``"0.1"``).
        pairs: Sandbox/source pairs (3 in the v1 cohort).
        real_unpaired: Unpaired real shops contributing to the
            real-shop reference population (3 in the v1 cohort).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    pairs: tuple[Pair, ...] = ()
    real_unpaired: tuple[Target, ...] = ()

    @model_validator(mode="after")
    def _check_unique_pair_ids(self) -> Cohort:
        """Reject cohorts that reuse a pair id across multiple pairs."""
        seen: set[str] = set()
        for pair in self.pairs:
            if pair.id in seen:
                msg = f"cohort: duplicate pair id {pair.id!r}"
                raise ValueError(msg)
            seen.add(pair.id)
        return self

    @model_validator(mode="after")
    def _check_real_unpaired_kind(self) -> Cohort:
        """Reject ``real_unpaired`` entries whose kind disagrees."""
        for target in self.real_unpaired:
            if target.kind != "real_unpaired":
                msg = (
                    f"cohort: real_unpaired entry {target.label!r} has "
                    f"kind={target.kind!r}; expected 'real_unpaired'"
                )
                raise ValueError(msg)
        return self
