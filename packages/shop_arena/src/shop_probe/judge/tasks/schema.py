"""Closed schemas for the axis-C judge task list.

Implements the typed contract for ``judge/tasks/v1.yaml`` referenced by
``docs/specs/shop_arena/web_probe.md`` §5.5 step 1 + §5.5.1:

* :class:`JudgeTask` — one judge-diagnostic task (the natural-language
  agent prompt plus diagnostic metadata used to argue diagnosticity in
  the paper).
* :class:`JudgeTaskSet` — the loaded, hashed task list (``version`` +
  ``tasks`` + ``content_hash``); pinned per :class:`ProbeReport` so the
  pairwise-judge run is reproducible (spec §5.8).

The task list is **independent** from the 108-task ShopGuru benchmark
per spec §5.5.1 — these tasks are tuned for *judge diagnosticity*
(visually rich, multi-page, interaction-heavy), not for behavioural
fidelity scoring.

Both models set ``extra="forbid"`` and ``frozen=True``: the task list is
content-addressable and must round-trip exactly. The module is import
safe — it performs no I/O at import time. YAML loading lives in
``shop_probe.judge.tasks.loader``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

JudgeTaskSurface = Literal[
    "homepage",
    "collection",
    "product",
    "search",
    "cart",
    "footer",
    "navigation",
    "account",
]
"""Storefront surfaces a judge task is expected to traverse.

Used to enforce the spec §5.5 step 1 requirement that each task is
*multi-page* — :class:`JudgeTask` requires at least two distinct
surfaces. Auth / checkout surfaces (``account``) only appear once
authenticated probes ship in v1.1 (spec §5.9); they are kept in the
literal so v1.1 task additions need no schema bump.
"""

JudgeTaskInteraction = Literal[
    "filter",
    "sort",
    "paginate",
    "open_pdp",
    "variant_select",
    "add_to_cart",
    "update_quantity",
    "remove_from_cart",
    "open_cart_drawer",
    "search_query",
    "follow_recommendation",
    "locale_switch",
    "currency_switch",
    "gallery_navigate",
    "review_filter",
    "megamenu_navigate",
    "footer_navigate",
    "scroll",
]
"""Interaction primitives a judge task may exercise.

Used to enforce the spec §5.5 step 1 requirement that each task is
*interaction-heavy* — :class:`JudgeTask` requires at least two distinct
interactions. Adding a new interaction is intentionally a schema bump
so new task families are surfaced in review.
"""


class JudgeTask(BaseModel):
    """One judge-diagnostic task.

    Mirrors the YAML shape in ``judge/tasks/v1.yaml``. ``extra="forbid"``
    means a typo in the YAML (``rationle:`` → unknown field) fails the
    loader rather than silently dropping the field.

    Attributes:
        id: Stable, snake_case task identifier (e.g.
            ``"filter_pdp_variant_cart_locale"``). Must be unique within
            a :class:`JudgeTaskSet`. Used as the join key in
            :class:`shop_probe.report.JudgeCall`.
        description: Natural-language agent prompt the harness hands to
            the agent runtime. The *only* field the agent sees.
        surfaces: Distinct storefront surfaces the task is expected to
            traverse. Length ≥ 2 enforces the spec §5.5 step 1
            "multi-page" requirement.
        interactions: Distinct interaction primitives the task is
            expected to exercise. Length ≥ 2 enforces the spec §5.5 step
            1 "interaction-heavy" requirement.
        rationale: One-sentence explanation of why the task is
            judge-diagnostic. Surfaces in paper supplement / review;
            does not enter the agent prompt.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    surfaces: tuple[JudgeTaskSurface, ...] = Field(min_length=2)
    interactions: tuple[JudgeTaskInteraction, ...] = Field(min_length=2)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_surfaces_unique(self) -> JudgeTask:
        """Reject tasks that list the same surface twice."""
        if len(set(self.surfaces)) != len(self.surfaces):
            msg = f"judge task {self.id!r}: duplicate entry in surfaces"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_interactions_unique(self) -> JudgeTask:
        """Reject tasks that list the same interaction twice."""
        if len(set(self.interactions)) != len(self.interactions):
            msg = f"judge task {self.id!r}: duplicate entry in interactions"
            raise ValueError(msg)
        return self


class JudgeTaskSet(BaseModel):
    """A loaded, validated, content-hashed judge task list.

    The ``content_hash`` field is a SHA-256 hex digest over the
    canonical UTF-8 bytes of the source YAML. It pins a specific task
    list revision into every :class:`shop_probe.report.ProbeReport`
    so judge calls can be re-attributed unambiguously (spec §5.8).

    Per spec §5.5 step 1 the task list ships ~10 tasks tuned for judge
    diagnosticity. ``8 ≤ len(tasks) ≤ 12`` formalises the "~10".

    Attributes:
        version: Task-list version string, e.g. ``"v1"``. Frozen per
            spec §5.8 — changes bump this.
        content_hash: 64-char lowercase hex SHA-256 of the source YAML
            bytes. Reviewers reproducing the report recompute this and
            compare.
        tasks: All judge tasks, in source order. Must be in ``[8, 12]``
            and have unique ``id``s.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tasks: tuple[JudgeTask, ...] = Field(min_length=8, max_length=12)

    @model_validator(mode="after")
    def _check_unique_task_ids(self) -> JudgeTaskSet:
        """Reject task lists that reuse an id."""
        seen: set[str] = set()
        for task in self.tasks:
            if task.id in seen:
                msg = f"judge task list {self.version!r}: duplicate task id {task.id!r}"
                raise ValueError(msg)
            seen.add(task.id)
        return self
