"""Closed schemas for the rubric.

* :class:`RubricEntry` — one rubric row. The ``type`` field discriminates
  between three runners — ``probe`` (deterministic Playwright check),
  ``capture_judge`` (one LLM call over a screenshot + a11y bundle), and
  ``scale`` (per-page richness metrics + catalog counts).
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

EntryType = Literal["probe", "capture_judge", "scale"]
"""Required discriminator that selects the runner for a rubric entry.

* ``probe`` — deterministic Playwright probe; carries a ``probe`` dotted
  reference and contributes to ``coverage_*`` rollups.
* ``capture_judge`` — one LLM call over a screenshot + accessibility-tree
  bundle slice; carries an inline ``capture_judge`` block. Also
  contributes to ``coverage_*`` rollups.
* ``scale`` — descriptive scale / richness measurement. Reuses the
  capture bundle's per-page stats and reads catalog counts from the
  target's ``data_dir``. Does not contribute to ``coverage_*``.
"""

RubricLevel = Literal["core", "modern", "advanced"]
"""Capability tier for ``probe`` and ``capture_judge`` entries.

* ``core`` — every modern storefront has this.
* ``modern`` — common in 2025-era themes; fidelity signal.
* ``advanced`` — stretch behavior.
"""

PageRef = Literal["home", "collection", "product", "cart", "search"]
"""Fixed 5-page surface every capture-judge entry references.

The :func:`shop_probe.capture.bundle.capture_bundle` runner captures one
:class:`shop_probe.capture.bundle.PageCapture` per ``PageRef`` per shop.
Each ``type: capture_judge`` rubric entry then references a subset of
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
    """Inline task definition for a ``type: capture_judge`` rubric entry.

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
    """One row of the rubric.

    ``extra="forbid"`` means a typo in the YAML (``categroy:`` → unknown
    field) fails the loader rather than silently scoring zero.

    The ``type`` field is the required discriminator. Each type carries
    a different inline-block contract; see ``_check_type_contract`` for
    the matrix:

    * ``probe`` requires ``category``, ``level``, ``weight``, ``probe``;
      ``capture_judge`` is forbidden.
    * ``capture_judge`` requires ``category``, ``level``, ``weight``,
      ``capture_judge``; ``probe`` is forbidden.
    * ``scale`` requires only ``id``, ``type``, ``description``;
      ``category`` / ``level`` / ``weight`` / ``probe`` /
      ``capture_judge`` / ``authenticated`` / ``transactional`` must
      all be unset.

    Attributes:
        id: Stable, dot-separated identifier (e.g.
            ``"product.gallery.thumbnails"``). Must be unique within a
            :class:`Rubric`.
        type: Discriminator that picks the runner (see :data:`EntryType`).
        description: One-line human-readable description of what the
            entry asserts. Surfaces in reports and figures.
        category: Rubric category — required for probe/capture_judge,
            must be unset for scale.
        level: Capability tier — required for probe/capture_judge, must
            be unset for scale.
        weight: Importance weight (1–3) — required for probe/capture_judge,
            must be unset for scale.
        probe: Dotted Python reference to the probe callable (e.g.
            ``"probes.product.gallery_has_thumbnails"``). Required for
            ``type: probe``; must be ``None`` otherwise.
        capture_judge: Inline capture-judge task. Required for
            ``type: capture_judge``; must be ``None`` otherwise.
        authenticated: ``True`` if the entry requires a logged-in
            session. Gated behind ``--include-auth``. Must be unset for
            ``type: scale``.
        transactional: ``True`` if the entry exercises checkout / order
            creation. Gated behind ``--include-auth``. Must be unset for
            ``type: scale``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    type: EntryType
    description: str = Field(min_length=1)
    category: RubricCategory | None = None
    level: RubricLevel | None = None
    weight: int | None = Field(default=None, ge=1, le=3)
    probe: str | None = Field(default=None, min_length=1)
    capture_judge: CaptureJudgeTask | None = None
    authenticated: bool | None = None
    transactional: bool | None = None

    @model_validator(mode="after")
    def _check_type_contract(self) -> RubricEntry:
        """Enforce the per-``type`` contract on inline blocks + tier fields."""
        if self.type in ("probe", "capture_judge"):
            for name, value in (
                ("category", self.category),
                ("level", self.level),
                ("weight", self.weight),
                ("authenticated", self.authenticated),
                ("transactional", self.transactional),
            ):
                if value is None:
                    msg = f"rubric entry {self.id!r}: type={self.type!r} requires {name!r}"
                    raise ValueError(msg)
            if self.type == "probe":
                if self.probe is None:
                    msg = (
                        f"rubric entry {self.id!r}: type='probe' requires a "
                        f"'probe' dotted reference"
                    )
                    raise ValueError(msg)
                if self.capture_judge is not None:
                    msg = (
                        f"rubric entry {self.id!r}: type='probe' must not set "
                        f"'capture_judge'"
                    )
                    raise ValueError(msg)
            else:  # capture_judge
                if self.capture_judge is None:
                    msg = (
                        f"rubric entry {self.id!r}: type='capture_judge' requires "
                        f"an inline 'capture_judge' block"
                    )
                    raise ValueError(msg)
                if self.probe is not None:
                    msg = (
                        f"rubric entry {self.id!r}: type='capture_judge' must not "
                        f"set 'probe'"
                    )
                    raise ValueError(msg)
        else:  # scale
            forbidden = (
                ("category", self.category),
                ("level", self.level),
                ("weight", self.weight),
                ("probe", self.probe),
                ("capture_judge", self.capture_judge),
                ("authenticated", self.authenticated),
                ("transactional", self.transactional),
            )
            for name, value in forbidden:
                if value is not None:
                    msg = (
                        f"rubric entry {self.id!r}: type='scale' must not set "
                        f"{name!r}"
                    )
                    raise ValueError(msg)
        return self


class Rubric(BaseModel):
    """A loaded, validated, content-hashed rubric.

    The ``content_hash`` field is a SHA-256 hex digest over the
    canonical UTF-8 bytes of the source YAML. It pins a specific
    rubric revision into every :class:`ProbeReport` header.

    Attributes:
        version: Rubric version string, e.g. ``"v3"``.
        content_hash: 64-char lowercase hex SHA-256 of the source YAML
            bytes.
        entries: All rubric rows, in source order. Must be non-empty
            and have unique ``id``s. At most one ``type: scale`` entry.
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

    @model_validator(mode="after")
    def _check_at_most_one_scale_entry(self) -> Rubric:
        """Reject rubrics with more than one ``type: scale`` entry.

        The scale runner emits a single :class:`ScaleMetrics` per shop;
        multiple scale entries with different intents are not modeled.
        """
        scale_ids = [e.id for e in self.entries if e.type == "scale"]
        max_scale_entries = 1
        if len(scale_ids) > max_scale_entries:
            msg = (
                f"rubric {self.version!r}: at most one type='scale' entry allowed, "
                f"got {scale_ids!r}"
            )
            raise ValueError(msg)
        return self
