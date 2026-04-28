"""Closed schemas for the axis-A capability-coverage rubric.

Implements the typed contract documented in
``docs/specs/shop_arena/web_probe.md`` §5.3 and §5.8:

* :class:`RubricEntry` — one rubric row (the YAML example in spec §5.3).
* :class:`Rubric` — the loaded, hashed rubric (``version`` + ``entries`` +
  ``content_hash``); embedded into every :class:`ProbeReport` header per
  spec §5.6 / §5.8.

Both models set ``extra="forbid"`` and ``frozen=True``: rubrics are
content-addressable and must round-trip exactly. The module is import
safe — it performs no I/O at import time. YAML loading lives in
``shop_probe.rubric.loader``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RubricLevel = Literal["core", "modern", "advanced"]
"""Capability tier (spec §5.3).

* ``core`` — every modern Shopify storefront has this.
* ``modern`` — common in 2025-era themes; fidelity signal.
* ``advanced`` — stretch behavior; dropped from v1 per spec §5.3.
"""

RubricCategory = Literal[
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
    "account",
    "checkout",
]
"""v1 rubric categories (spec §5.3 table) plus the v1.1 auth + checkout slice (T7.4).

v1 ships the first 11 categories. ``account`` and ``checkout`` ship in v1.1
behind ``authenticated: true`` / ``transactional: true`` and are gated behind
``shop-probe run --include-auth`` per spec §5.9.
"""


class RubricEntry(BaseModel):
    """One row of the capability rubric.

    Mirrors the YAML schema in spec §5.3 verbatim. ``extra="forbid"``
    means a typo in the YAML (``categroy:`` → unknown field) fails the
    loader rather than silently scoring zero.

    Attributes:
        id: Stable, dot-separated probe identifier (e.g.
            ``"product.gallery.thumbnails"``). Must be unique within a
            :class:`Rubric`.
        category: One of the 11 v1 categories (see :data:`RubricCategory`).
        level: Capability tier (see :data:`RubricLevel`).
        weight: Importance weight, integer in ``[1, 3]``. Used in the
            per-category coverage formula
            ``Σ weight·passed / Σ weight`` (spec §5.3).
        probe: Dotted Python reference to the probe callable, e.g.
            ``"probes.product.gallery_has_thumbnails"``. Resolved by the
            runner at execution time.
        description: One-line human-readable description of what the
            probe asserts. Surfaces in reports and figures.
        authenticated: ``True`` if the probe requires a logged-in
            session. Always ``False`` in v1 (spec §5.9 — auth probes
            ship in v1.1).
        transactional: ``True`` if the probe exercises checkout / order
            creation. Always ``False`` in v1 (spec §5.9).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    category: RubricCategory
    level: RubricLevel
    weight: int = Field(ge=1, le=3)
    probe: str = Field(min_length=1)
    description: str = Field(min_length=1)
    authenticated: bool
    transactional: bool


class Rubric(BaseModel):
    """A loaded, validated, content-hashed rubric.

    The ``content_hash`` field is a SHA-256 hex digest over the
    canonical UTF-8 bytes of the source YAML. It pins a specific
    rubric revision into every :class:`ProbeReport` header so that
    paper figures can be re-rendered unambiguously (spec §5.8).

    Attributes:
        version: Rubric version string, e.g. ``"v1"``. Frozen per spec
            §5.8 — changes bump this.
        content_hash: 64-char lowercase hex SHA-256 of the source YAML
            bytes. Reviewers reproducing the report recompute this and
            compare.
        entries: All rubric rows, in source order. Must be non-empty
            and have unique ``id``s.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[RubricEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_entry_ids(self) -> Rubric:
        """Reject rubrics that reuse an entry id."""
        seen: set[str] = set()
        for entry in self.entries:
            if entry.id in seen:
                msg = f"rubric {self.version!r}: duplicate entry id {entry.id!r}"
                raise ValueError(msg)
            seen.add(entry.id)
        return self
