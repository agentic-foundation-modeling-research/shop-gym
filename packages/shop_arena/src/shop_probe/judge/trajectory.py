"""Closed schema for axis-C agent trajectories (T4.1 — spec §5.5).

The ``web_probe`` axis-C judge consumes one ``Trajectory`` per (target,
task) pair: an ordered sequence of ``(action, observation, reasoning)``
tuples plus per-step screenshots and accessibility-tree snapshots, written
to disk by the agent runner (T4.2) and later anonymized for blinded
pairwise scoring (T4.4).

This module defines the typed contract for that artifact:

* :class:`TrajectoryAction` — what the agent told the storefront to do.
* :class:`TrajectoryObservation` — what the storefront returned, anchored
  to a screenshot + a11y snapshot per spec §5.5 step 2.
* :class:`TrajectoryStep` — one ``(action, observation, reasoning)``
  tuple — the unit the spec anchors the judge artifact at.
* :class:`Trajectory` — the closed JSON document persisted per agent run.

All models set ``extra="forbid"`` and ``frozen=True`` so judge-input
drift surfaces immediately at validation time rather than as a silent
scoring regression. The module is import-safe — it performs no I/O at
import time.

Anonymization (spec §5.5 step 3, T4.4) operates on a populated
``Trajectory`` and produces another populated ``Trajectory`` with brand
strings, distinctive product names, URLs, and theme identifiers
rewritten; the ``anonymized`` flag records the post-rewrite state. Both
forms validate against this schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shop_probe.report import BrowserMeta, EvidenceRef
from shop_probe.targets import Target

TrajectoryStatus = Literal["completed", "failed", "timeout", "abandoned"]
"""Outcome of an agent run on one target (spec §5.5 step 2).

* ``completed`` — the agent reached a terminal state on the task.
* ``failed`` — the agent surfaced an error before terminating.
* ``timeout`` — the harness or runtime hit the per-task time budget.
* ``abandoned`` — the operator cancelled the run before it finished.
"""


class TrajectoryAction(BaseModel):
    """One action the agent issued against the storefront (spec §5.5 step 2).

    Captures the structural shape the judge sees — kind, target selector,
    optional input value, plus a human-readable description — decoupled
    from the harness's internal tool-call telemetry shape (which lives in
    ``packages/harness``). The wrapper in T4.2 is responsible for
    projecting harness ``ToolCallStep`` rows into this shape.

    Attributes:
        kind: Action kind (e.g. ``"click"``, ``"type"``, ``"navigate"``,
            ``"wait"``, ``"scroll"``, ``"submit"``). Free-form so new
            harness tools can be projected without a schema bump.
        selector: CSS / ARIA-role selector the action targeted, or
            ``None`` when the action is not anchored to a single locator
            (e.g. a ``"navigate"`` step).
        value: Input text or destination URL for ``"type"`` /
            ``"navigate"`` actions; ``None`` otherwise.
        description: Human-readable one-line description used by the
            judge prompt template (spec §8.3 example).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1)
    selector: str | None = None
    value: str | None = None
    description: str = Field(min_length=1)


class TrajectoryObservation(BaseModel):
    """Observation captured immediately after one action (spec §5.5 step 2).

    Spec §5.5 mandates per-step screenshots and accessibility-tree
    snapshots; both are required by this schema and stored as
    :class:`EvidenceRef` rows so storage paths remain relocatable
    alongside :class:`shop_probe.report.ProbeReport` evidence.

    Attributes:
        url: URL visible to the agent after the action. ``None`` when
            the action did not navigate, or when the URL was scrubbed
            during anonymization (spec §5.5 step 3).
        title: Document title observed after the action; ``None`` when
            unavailable or scrubbed during anonymization.
        screenshot: PNG capture of the viewport after the action.
        a11y_snapshot: Accessibility-tree snapshot after the action.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str | None = None
    title: str | None = None
    screenshot: EvidenceRef
    a11y_snapshot: EvidenceRef


class TrajectoryStep(BaseModel):
    """One ``(action, observation, reasoning)`` tuple (spec §5.5 step 2).

    The tuple is the unit the spec anchors the judge artifact at; the
    ``reasoning`` field is the agent's stated rationale for the action
    and may be empty for runtimes that do not surface inner reasoning.

    Attributes:
        index: 0-indexed step number within the parent
            :class:`Trajectory`. Distinct from list position so the
            schema survives partial trajectories (e.g. dropped frames
            during anonymization audit).
        action: The action issued (see :class:`TrajectoryAction`).
        observation: The observation captured immediately after the
            action (see :class:`TrajectoryObservation`).
        reasoning: Agent's stated rationale for the action. May be empty.
        duration_ms: Wall-clock duration from action issue to
            observation capture, in milliseconds.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    action: TrajectoryAction
    observation: TrajectoryObservation
    reasoning: str = ""
    duration_ms: int = Field(ge=0)


class Trajectory(BaseModel):
    """One agent run on one target, persisted as judge input (spec §5.5).

    The closed schema for the artifact the blinded pairwise judge consumes
    after anonymization (spec §5.5 step 3, T4.4). Each ``Trajectory`` is
    keyed by ``(target, task_id)`` and carries the ordered
    ``(action, observation, reasoning)`` tuples plus per-step screenshots,
    accessibility-tree snapshots, and an optional full-run HAR capture
    for the spec §5.8 reproducibility audit.

    ``extra="forbid"`` + ``frozen=True`` mean schema drift surfaces at
    validation time rather than as a silent judge-input regression.

    Attributes:
        target: The storefront the agent ran against. After
            anonymization the ``label`` and ``base_url`` fields are
            rewritten to brand-free placeholders; ``anonymized`` records
            that state.
        task_id: Identifier of the judge task from
            ``judge/tasks/v1.yaml`` (spec §5.5 step 1).
        runner_version: ``shop_probe`` runner version that produced the
            trajectory.
        runtime: Pinned browser/runtime versions (see
            :class:`BrowserMeta`); identical to the ``ProbeReport``
            metadata so reviewers can correlate axis-A and axis-C runs.
        started_at: When the agent run started; should be timezone-aware.
        ended_at: When the agent run ended; ``ended_at >= started_at``
            is enforced by the validator.
        steps: Ordered ``(action, observation, reasoning)`` tuples. May
            be empty for trajectories that timed out before the first
            action.
        har: Full HAR network capture for the run (spec §5.8); ``None``
            when HAR capture was disabled.
        final_status: Terminal state of the run (see
            :data:`TrajectoryStatus`).
        anonymized: ``True`` once spec §5.5 step 3 anonymization (T4.4)
            has been applied; the judge only ever sees ``anonymized=True``
            trajectories.
        notes: Free-form operator notes; ``None`` if unset.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: Target
    task_id: str = Field(min_length=1)
    runner_version: str = Field(min_length=1)
    runtime: BrowserMeta
    started_at: datetime
    ended_at: datetime
    steps: tuple[TrajectoryStep, ...] = ()
    har: EvidenceRef | None = None
    final_status: TrajectoryStatus
    anonymized: bool = False
    notes: str | None = None

    def model_post_init(self, __context: object) -> None:
        """Enforce ``ended_at >= started_at`` (spec §5.5 step 2 invariant)."""
        if self.ended_at < self.started_at:
            msg = (
                f"trajectory {self.task_id!r} on {self.target.name!r}: "
                f"ended_at ({self.ended_at.isoformat()}) precedes "
                f"started_at ({self.started_at.isoformat()})"
            )
            raise ValueError(msg)
