"""Frozen fixture tests for ``judge/tasks/v1.yaml`` (T4.3 — spec §5.5, §5.8).

The shipped judge task list is the contract every :class:`JudgeCall`
references via ``content_hash`` per spec §5.8. These tests pin the
version, the SHA-256 over the raw YAML bytes, the task count
(``8 ≤ len ≤ 12`` per spec §5.5 step 1's "~10"), and the spec §5.5
diagnosticity invariants the loader cannot enforce on its own (every
task is multi-page and interaction-heavy; ids are unique and
snake_case).

Edits to ``judge/tasks/v1.yaml`` MUST bump the version string AND
update the ``EXPECTED_V1_HASH`` constant below — that is the whole
point of pinning per spec §5.8.
"""

from __future__ import annotations

from pathlib import Path

from shop_probe.judge.tasks import compute_content_hash, load_judge_tasks

# --------------------------------------------------------------------------- #
# Pinned fixture — bump together with judge/tasks/v1.yaml.
# --------------------------------------------------------------------------- #

V1_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "src"
    / "shop_probe"
    / "judge"
    / "tasks"
    / "v1.yaml"
)

EXPECTED_V1_HASH: str = "4aeee9bacee1d36a6ccd544aafc7591a7e2a4a6be46d9d1d1fb11f5a44d67621"
"""SHA-256 of ``judge/tasks/v1.yaml`` raw bytes. Pin per spec §5.8."""

EXPECTED_V1_VERSION: str = "v1"

EXPECTED_V1_TASK_COUNT: int = 10
"""Spec §5.5 step 1: ``~10`` judge-diagnostic tasks."""


def test_v1_path_exists() -> None:
    assert V1_PATH.is_file(), f"missing judge task list at {V1_PATH}"


def test_v1_pinned_hash() -> None:
    raw = V1_PATH.read_bytes()
    assert compute_content_hash(raw) == EXPECTED_V1_HASH, (
        "judge/tasks/v1.yaml hash drifted. Bump `version` AND update EXPECTED_V1_HASH."
    )


def test_v1_loads_and_pins_metadata() -> None:
    task_set = load_judge_tasks(V1_PATH)
    assert task_set.version == EXPECTED_V1_VERSION
    assert task_set.content_hash == EXPECTED_V1_HASH
    assert len(task_set.tasks) == EXPECTED_V1_TASK_COUNT


def test_v1_task_ids_are_unique_snake_case() -> None:
    task_set = load_judge_tasks(V1_PATH)
    ids = [task.id for task in task_set.tasks]
    assert len(ids) == len(set(ids)), "duplicate task id in v1.yaml"
    # Schema enforces the regex; this assertion guards against future schema laxity.
    for task_id in ids:
        assert task_id == task_id.lower()
        assert " " not in task_id
        assert "-" not in task_id


def test_v1_every_task_is_multi_page_and_interaction_heavy() -> None:
    """Spec §5.5 step 1: visually rich, multi-page, interaction-heavy.

    The schema enforces ``≥ 2`` distinct surfaces and ``≥ 2`` distinct
    interactions per task; this test pins the v1 task list specifically
    against accidental relaxation in code review.
    """
    task_set = load_judge_tasks(V1_PATH)
    for task in task_set.tasks:
        assert len(set(task.surfaces)) >= 2, f"{task.id}: surfaces not multi-page"  # noqa: PLR2004
        assert len(set(task.interactions)) >= 2, (  # noqa: PLR2004
            f"{task.id}: interactions not interaction-heavy"
        )


def test_v1_task_descriptions_have_meaningful_length() -> None:
    """Guard against a future edit collapsing a task to a single word.

    The pairwise judge cites task description in its prompt (spec
    §8.3); empty / one-word descriptions break that contract.
    """
    task_set = load_judge_tasks(V1_PATH)
    for task in task_set.tasks:
        assert len(task.description.strip()) >= 40, f"{task.id}: description too short"  # noqa: PLR2004
        assert len(task.rationale.strip()) >= 20, f"{task.id}: rationale too short"  # noqa: PLR2004


def test_v1_covers_diverse_surfaces() -> None:
    """The task list must collectively touch ≥ 5 storefront surfaces.

    Diversity in covered surfaces is what makes the task list
    *judge-diagnostic* across themes (spec §5.5 step 1). A task list
    that only ever touches collection + product would not exercise
    homepage / search / footer / navigation theme variation.
    """
    task_set = load_judge_tasks(V1_PATH)
    seen_surfaces: set[str] = set()
    for task in task_set.tasks:
        seen_surfaces.update(task.surfaces)
    assert len(seen_surfaces) >= 5, (  # noqa: PLR2004
        f"v1 task list only touches surfaces {sorted(seen_surfaces)}; "
        "spec §5.5 step 1 requires diverse surfaces."
    )


def test_v1_covers_diverse_interactions() -> None:
    """The task list must collectively use ≥ 8 interaction primitives."""
    task_set = load_judge_tasks(V1_PATH)
    seen_interactions: set[str] = set()
    for task in task_set.tasks:
        seen_interactions.update(task.interactions)
    assert len(seen_interactions) >= 8, (  # noqa: PLR2004
        f"v1 task list only uses interactions {sorted(seen_interactions)}; "
        "spec §5.5 step 1 requires interaction-heavy diversity."
    )
