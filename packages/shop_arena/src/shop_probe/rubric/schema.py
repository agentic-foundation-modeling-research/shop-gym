"""Closed schemas for the axis-A capability-coverage rubric.

* :class:`RubricEntry` — one rubric row.
* :class:`Rubric` — the loaded, hashed rubric (``version`` + ``entries`` +
  ``content_hash``); embedded into every :class:`ProbeReport` header so
  paper figures can be re-rendered unambiguously.

Both models set ``extra="forbid"`` and ``frozen=True``: rubrics are
content-addressable and must round-trip exactly. The module is import
safe — it performs no I/O at import time. YAML loading lives in
``shop_probe.rubric.loader``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RubricLevel = Literal["core", "modern", "advanced", "capture_judge"]
"""Capability tier.

* ``core`` — every modern storefront has this.
* ``modern`` — common in 2025-era themes; fidelity signal.
* ``advanced`` — stretch behavior; deterministic Playwright probes.
* ``capture_judge`` — structural-affordance verdict from one Anthropic
  Messages-API call over a screenshot + accessibility-tree bundle slice.
  Carries an inline ``capture_judge`` block instead of a ``probe`` reference.
"""

PageRef = Literal["home", "collection", "product", "cart", "search"]
"""Fixed 5-page surface every capture-judge entry references.

The :func:`shop_probe.capture.bundle.capture_bundle` runner captures one
:class:`shop_probe.capture.bundle.PageCapture` per ``PageRef`` per shop.
Each ``level: capture_judge`` rubric entry then references a subset of
these pages via :attr:`CaptureJudgeTask.pages`.
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
"""Rubric categories. ``account`` and ``checkout`` are gated behind
``authenticated: true`` / ``transactional: true`` and the
``--include-auth`` flag.
"""


class CaptureJudgeTask(BaseModel):
    """Inline task definition for a ``level: capture_judge`` rubric entry.

    A capture-judge entry asks the vision judge a structural-affordance
    question over a slice of the per-shop page bundle (one screenshot +
    accessibility tree per :class:`PageRef`).

    Attributes:
        judge_prompt: The structural-affordance question handed to the
            judge verbatim, embedded inside the closing instruction that
            asks for ``{"passed": bool, "reasoning": str}``.
        pages: Subset of :data:`PageRef` (in the order the judge should
            see them). Must be non-empty and unique. The dispatcher
            slices the per-shop bundle by this tuple before calling
            :func:`shop_probe.agent.judge.run_capture_judge`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    judge_prompt: str = Field(min_length=1)
    pages: tuple[PageRef, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def _check_unique_pages(self) -> CaptureJudgeTask:
        """Reject capture-judge tasks that list the same page twice."""
        if len(set(self.pages)) != len(self.pages):
            msg = f"capture_judge.pages must be unique, got {self.pages!r}"
            raise ValueError(msg)
        return self


class RubricEntry(BaseModel):
    """One row of the capability rubric.

    ``extra="forbid"`` means a typo in the YAML (``categroy:`` → unknown
    field) fails the loader rather than silently scoring zero.

    Attributes:
        id: Stable, dot-separated probe identifier (e.g.
            ``"product.gallery.thumbnails"``). Must be unique within a
            :class:`Rubric`.
        category: Rubric category (see :data:`RubricCategory`).
        level: Capability tier (see :data:`RubricLevel`).
        weight: Importance weight, integer in ``[1, 3]``. Used in the
            per-category coverage formula
            ``Σ weight·passed / Σ weight``.
        probe: Dotted Python reference to the probe callable, e.g.
            ``"probes.product.gallery_has_thumbnails"``. Required for
            deterministic entries (``core`` / ``modern`` / ``advanced``);
            must be ``None`` for ``capture_judge`` entries — those carry
            an inline :class:`CaptureJudgeTask` block instead.
        capture_judge: Inline capture-judge task definition. Required
            for ``level: capture_judge`` entries; must be ``None``
            otherwise.
        description: One-line human-readable description of what the
            probe asserts. Surfaces in reports and figures.
        authenticated: ``True`` if the probe requires a logged-in
            session. Gated behind ``--include-auth``.
        transactional: ``True`` if the probe exercises checkout / order
            creation. Gated behind ``--include-auth``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    category: RubricCategory
    level: RubricLevel
    weight: int = Field(ge=1, le=3)
    probe: str | None = Field(default=None, min_length=1)
    description: str = Field(min_length=1)
    authenticated: bool
    transactional: bool
    capture_judge: CaptureJudgeTask | None = None

    @model_validator(mode="after")
    def _check_probe_xor_inline_task(self) -> RubricEntry:
        """Enforce the probe / inline-task contract per ``level``.

        * ``capture_judge`` entries: ``capture_judge`` is required and
          ``probe`` must be ``None``.
        * Other levels: ``probe`` is required and ``capture_judge`` must
          be ``None``.
        """
        if self.level == "capture_judge":
            if self.capture_judge is None:
                msg = (
                    f"rubric entry {self.id!r}: level='capture_judge' requires an "
                    f"inline 'capture_judge' block"
                )
                raise ValueError(msg)
            if self.probe is not None:
                msg = (
                    f"rubric entry {self.id!r}: level='capture_judge' must not set "
                    f"'probe' (use the inline 'capture_judge' block instead)"
                )
                raise ValueError(msg)
        else:
            if self.probe is None:
                msg = (
                    f"rubric entry {self.id!r}: level={self.level!r} requires a "
                    f"'probe' dotted reference"
                )
                raise ValueError(msg)
            if self.capture_judge is not None:
                msg = (
                    f"rubric entry {self.id!r}: level={self.level!r} must not set "
                    f"'capture_judge' (only 'capture_judge' entries carry one)"
                )
                raise ValueError(msg)
        return self


class Rubric(BaseModel):
    """A loaded, validated, content-hashed rubric.

    The ``content_hash`` field is a SHA-256 hex digest over the
    canonical UTF-8 bytes of the source YAML. It pins a specific
    rubric revision into every :class:`ProbeReport` header.

    Attributes:
        version: Rubric version string, e.g. ``"v2"``.
        content_hash: 64-char lowercase hex SHA-256 of the source YAML
            bytes.
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
