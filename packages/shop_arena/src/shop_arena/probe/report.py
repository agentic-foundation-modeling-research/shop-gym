"""Closed schemas for the v1.0 ``ProbeReport`` artifact (spec §5.4).

A report bundles three independently-measurable claims about a target
storefront, one per family of the agent's MDP:

* ``observation`` — what the agent perceives (shape metrics + info slots).
* ``action`` — what the agent can do (space metrics + control slots).
* ``transition`` — what happens when the agent acts (scripted Playwright).

Plus a per-page-type ``modality_consistency`` rate (mean over slots of
``verdict_a11y == verdict_screenshot``) which is itself a fidelity property.

All models set ``extra="forbid"`` and ``frozen=True``; the report is the
public contract figures read from. The module is import-safe.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from shop_arena.probe.rubric.schema import Modality, PageType
from shop_arena.probe.targets import Target


class BrowserMeta(BaseModel):
    """Pinned browser/runtime versions embedded in every report header."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_version: str = Field(min_length=1)
    playwright_version: str = Field(min_length=1)
    chromium_version: str = Field(min_length=1)
    user_agent: str = Field(min_length=1)
    viewport: tuple[int, int]
    headless: bool


class ShapeMetrics(BaseModel):
    """``observation.shape`` continuous metrics for one (page_type, modality).

    All fields optional because not every metric is defined on every
    modality (e.g. ``megapixels`` is screenshot-only, ``nodes`` is
    a11y-only). Absent → ``None``; the cohort rollup ignores ``None``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # a11y
    nodes: int | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)
    actionable_count: int | None = Field(default=None, ge=0)

    # screenshot
    megapixels: float | None = Field(default=None, ge=0.0)
    byte_size_kb: float | None = Field(default=None, ge=0.0)


class ActionSpaceMetrics(BaseModel):
    """``action.space`` continuous metrics for one (page_type, modality)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actionable_count: int | None = Field(default=None, ge=0)
    unique_role_name_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class SlotVerdict(BaseModel):
    """One judge call's outcome for an info_slot or control_slot, on one modality."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    present: bool
    name_used: str | None = None
    evidence_locator: str | None = None
    judge_model: str = Field(min_length=1)
    judge_cost_usd: float = Field(ge=0.0)
    reasoning: str | None = None


class TransitionResult(BaseModel):
    """One scripted Playwright transition's 4-bit verdict + latency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_found: bool
    action_executed: bool
    state_changed: bool
    state_changed_as_expected: bool
    latency_ms: int = Field(ge=0)
    notes: str | None = None


class ObservationBlock(BaseModel):
    """``observation`` family results.

    * ``shape[page_type][modality]`` — :class:`ShapeMetrics`.
    * ``info_slots[page_type][slot_id][modality]`` — :class:`SlotVerdict`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    shape: dict[PageType, dict[Modality, ShapeMetrics]] = Field(default_factory=lambda: {})
    info_slots: dict[PageType, dict[str, dict[Modality, SlotVerdict]]] = Field(
        default_factory=lambda: {}
    )


class ActionBlock(BaseModel):
    """``action`` family results."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    space: dict[PageType, dict[Modality, ActionSpaceMetrics]] = Field(
        default_factory=lambda: {}
    )
    control_slots: dict[PageType, dict[str, dict[Modality, SlotVerdict]]] = Field(
        default_factory=lambda: {}
    )


class ProbeReport(BaseModel):
    """Closed report emitted per target per run (spec §5.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Header.
    target: Target
    rubric_version: str = Field(min_length=1)
    rubric_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_version: str = Field(min_length=1)
    runtime: BrowserMeta
    timestamp: datetime

    # Family blocks.
    observation: ObservationBlock = Field(default_factory=ObservationBlock)
    action: ActionBlock = Field(default_factory=ActionBlock)
    transition: dict[PageType, dict[str, TransitionResult]] = Field(
        default_factory=lambda: {}
    )

    # Cross-modal consistency per page type, mean over slots ∈ [0, 1].
    modality_consistency: dict[PageType, float] = Field(default_factory=lambda: {})

    # Cost rollup over every judge call this report issued.
    total_judge_cost_usd: float = Field(default=0.0, ge=0.0)
