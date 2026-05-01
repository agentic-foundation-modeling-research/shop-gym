"""Closed schemas for the v1.0 rubric.

The rubric is organized around three **families** that map to the
components of an agent's MDP — ``observation`` / ``action`` /
``transition`` — and a small set of **kinds** that select the runner.

* ``observation`` — what the agent perceives.
  - ``shape`` (mechanical, both modalities)
  - ``info_slot`` (LLM judge, one slot per entry)
* ``action`` — what the agent can do.
  - ``space`` (mechanical, action-space metrics)
  - ``control_slot`` (LLM judge, one control per entry)
* ``transition`` — what happens when the agent acts.
  - ``scripted`` (Playwright; modality-agnostic)

See ``docs/specs/shop_arena/shop_probe.md`` §5.6 for the YAML shape and
§5.2 for the family/kind matrix.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Family = Literal["observation", "action", "transition"]
"""Required discriminator selecting the MDP component this entry measures."""

Kind = Literal["shape", "info_slot", "space", "control_slot", "scripted"]
"""Subfamily discriminator that picks the runner.

* ``shape`` — observation-shape mechanical metrics (no LLM, both modalities).
* ``info_slot`` — observation info-slot judge call (one modality per call).
* ``space`` — action-space mechanical metrics.
* ``control_slot`` — action control-slot judge call.
* ``scripted`` — Playwright transition script.
"""

PageType = Literal["homepage", "collection", "product", "search", "cart"]
"""Canonical page surfaces the rubric runs against (spec §5.1)."""

Modality = Literal["a11y", "screenshot"]
"""Agent observation channel.

* ``a11y`` — accessibility-tree JSON (text-based agents).
* ``screenshot`` — rendered viewport PNG (vision agents).

Family ``transition`` is modality-agnostic and never carries this field.
"""


class RubricEntry(BaseModel):
    """One row of the rubric.

    The shape depends on ``kind``:

    * ``shape`` / ``space`` — mechanical, runs on every page in
      ``page_types`` for every modality in ``modalities``.
    * ``info_slot`` / ``control_slot`` — judge call; ``page_type``,
      ``modalities`` and ``prompt`` are required.
    * ``scripted`` — Playwright transition; ``page_type``, ``script`` and
      ``expected_change`` are required; ``modalities`` is forbidden.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    family: Family
    kind: Kind
    description: str | None = None

    # Mechanical (kind in {shape, space}): one entry covers many pages.
    page_types: tuple[PageType, ...] | None = None

    # Judge / scripted (kind in {info_slot, control_slot, scripted}):
    # one entry → one page.
    page_type: PageType | None = None

    # Observation/action only. Forbidden on transition.
    modalities: tuple[Modality, ...] | None = None

    # Judge slots only.
    prompt: str | None = Field(default=None, min_length=1)

    # Scripted transitions only.
    script: str | None = Field(default=None, min_length=1)
    expected_change: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_kind_contract(self) -> RubricEntry:
        family_kind = {
            "observation": ("shape", "info_slot"),
            "action": ("space", "control_slot"),
            "transition": ("scripted",),
        }
        allowed = family_kind[self.family]
        if self.kind not in allowed:
            msg = (
                f"rubric entry {self.id!r}: family={self.family!r} requires "
                f"kind in {allowed!r}, got {self.kind!r}"
            )
            raise ValueError(msg)

        if self.kind in ("shape", "space"):
            if not self.page_types:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} requires "
                    f"non-empty 'page_types'"
                )
                raise ValueError(msg)
            if self.page_type is not None:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} must not "
                    f"set 'page_type' (use 'page_types')"
                )
                raise ValueError(msg)
            if not self.modalities:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} requires "
                    f"non-empty 'modalities'"
                )
                raise ValueError(msg)
            if self.prompt is not None or self.script is not None:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} must not "
                    f"set 'prompt' or 'script'"
                )
                raise ValueError(msg)
        elif self.kind in ("info_slot", "control_slot"):
            if self.page_type is None:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} requires 'page_type'"
                )
                raise ValueError(msg)
            if self.page_types is not None:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} must not "
                    f"set 'page_types'"
                )
                raise ValueError(msg)
            if not self.modalities:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} requires "
                    f"non-empty 'modalities'"
                )
                raise ValueError(msg)
            if self.prompt is None:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} requires 'prompt'"
                )
                raise ValueError(msg)
            if self.script is not None:
                msg = (
                    f"rubric entry {self.id!r}: kind={self.kind!r} must not set 'script'"
                )
                raise ValueError(msg)
        else:  # scripted
            if self.page_type is None:
                msg = f"rubric entry {self.id!r}: kind='scripted' requires 'page_type'"
                raise ValueError(msg)
            if self.page_types is not None:
                msg = (
                    f"rubric entry {self.id!r}: kind='scripted' must not set 'page_types'"
                )
                raise ValueError(msg)
            if self.modalities is not None:
                msg = (
                    f"rubric entry {self.id!r}: kind='scripted' must not set "
                    f"'modalities' (transitions are modality-agnostic)"
                )
                raise ValueError(msg)
            if self.script is None or self.expected_change is None:
                msg = (
                    f"rubric entry {self.id!r}: kind='scripted' requires "
                    f"'script' and 'expected_change'"
                )
                raise ValueError(msg)
            if self.prompt is not None:
                msg = (
                    f"rubric entry {self.id!r}: kind='scripted' must not set 'prompt'"
                )
                raise ValueError(msg)
        return self


class Rubric(BaseModel):
    """A loaded, validated, content-hashed rubric.

    ``content_hash`` is the SHA-256 hex digest of the source YAML bytes,
    embedded in every :class:`shop_probe.report.ProbeReport` header so a
    figure regression is traceable to a specific rubric revision.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[RubricEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_entry_ids(self) -> Rubric:
        seen: set[str] = set()
        for entry in self.entries:
            if entry.id in seen:
                msg = f"rubric {self.version!r}: duplicate entry id {entry.id!r}"
                raise ValueError(msg)
            seen.add(entry.id)
        return self
