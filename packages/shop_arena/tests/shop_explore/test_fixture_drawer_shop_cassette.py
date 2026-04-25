"""Structural validation for the ``fixture_drawer_shop`` replay cassette (T2.5).

Asserts the hand-crafted cassette under
``tests/shop_explore/cassettes/fixture_drawer_shop/`` matches the harness
§5.6 minimal cassette shape (a `Trajectory` JSON + an evolving
``workspace_after/`` overlay) and the ShopExplore §5.5 / §5.7 contracts:

* every iteration parses as a valid :class:`harness.types.Trajectory`,
* the planner ``workspace_after/plan.md`` is parseable and contains the
  four expected tasks in priority order,
* every executor iteration's ``workspace_after/`` flips its selected
  task to ``[x]`` and writes ``parts/<task>.md`` +
  ``parts/<task>.caps.json`` + ``evidence/<task>/`` files,
* the four ``parts/*.caps.json`` fragments deep-merge into a complete
  :class:`shop_explore.capabilities.Capabilities` document with no
  conflicts.

This is the gate for T2.5; the replay-driven pipeline test (T2.6) is
authored separately.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.plan_parser import parse as parse_plan
from harness.types import TaskStatus, Trajectory
from shop_explore.capabilities import Capabilities, merge_fragments

CASSETTE_DIR = Path(__file__).resolve().parent / "cassettes" / "fixture_drawer_shop"

EXPECTED_PLAN_TASK_IDS: tuple[str, ...] = (
    "homepage_sections",
    "cart_drawer",
    "search_predictive",
    "collection_filters",
)
EXPECTED_PRIORITIES: dict[str, int] = {
    "homepage_sections": 8,
    "cart_drawer": 7,
    "search_predictive": 6,
    "collection_filters": 5,
}
EXPECTED_HOMEPAGE_SECTION_COUNT = 5
EXEC_TASK_BY_ITER: dict[str, str] = {
    "exec-0001": "homepage_sections",
    "exec-0002": "cart_drawer",
    "exec-0003": "search_predictive",
    "exec-0004": "collection_filters",
}


def _load_trajectory(iter_dir: Path) -> Trajectory:
    payload = json.loads((iter_dir / "trajectory.json").read_text(encoding="utf-8"))
    return Trajectory.model_validate(payload)


def test_cassette_root_layout_is_complete() -> None:
    """Every documented iter dir is present with a ``workspace_after/``."""
    expected_iters = ("plan", *EXEC_TASK_BY_ITER.keys())
    for iter_id in expected_iters:
        iter_dir = CASSETTE_DIR / iter_id
        assert iter_dir.is_dir(), f"missing iter dir: {iter_dir}"
        assert (iter_dir / "trajectory.json").is_file(), f"missing trajectory.json under {iter_dir}"
        assert (iter_dir / "workspace_after").is_dir(), f"missing workspace_after/ under {iter_dir}"


def test_every_trajectory_parses_as_harness_trajectory() -> None:
    """All five `trajectory.json` files validate against `harness.types.Trajectory`."""
    for iter_id in ("plan", *EXEC_TASK_BY_ITER.keys()):
        traj = _load_trajectory(CASSETTE_DIR / iter_id)
        assert traj.iter_id == iter_id
        assert traj.exit_code == 0
        assert len(traj.steps) >= 1


def test_planner_workspace_after_writes_four_tasks_in_priority_order() -> None:
    """The planner overlay seeds the canonical four-task plan with descending priorities."""
    plan_md = (CASSETTE_DIR / "plan" / "workspace_after" / "plan.md").read_text(encoding="utf-8")
    tasks = parse_plan(plan_md).tasks
    assert tuple(t.id for t in tasks) == EXPECTED_PLAN_TASK_IDS
    assert all(t.status is TaskStatus.PENDING for t in tasks)
    assert {t.id: t.priority for t in tasks} == EXPECTED_PRIORITIES


def test_executor_overlays_progressively_check_off_their_task() -> None:
    """Each executor's plan.md flips exactly its selected task to `[x]` and leaves the rest."""
    expected_done: list[str] = []
    for iter_id, task_id in EXEC_TASK_BY_ITER.items():
        expected_done.append(task_id)
        plan_md = (CASSETTE_DIR / iter_id / "workspace_after" / "plan.md").read_text(
            encoding="utf-8"
        )
        tasks = parse_plan(plan_md).tasks
        assert tuple(t.id for t in tasks) == EXPECTED_PLAN_TASK_IDS
        for task in tasks:
            if task.id in expected_done:
                assert task.status is TaskStatus.DONE, (
                    f"{iter_id}: expected {task.id} done, got {task.status.value}"
                )
            else:
                assert task.status is TaskStatus.PENDING, (
                    f"{iter_id}: expected {task.id} pending, got {task.status.value}"
                )


def test_each_executor_writes_parts_and_evidence_for_its_task() -> None:
    """Each exec overlay must drop `parts/<task>.{md,caps.json}` and `evidence/<task>/*`."""
    for iter_id, task_id in EXEC_TASK_BY_ITER.items():
        artifact = CASSETTE_DIR / iter_id / "workspace_after" / "artifact"
        part_md = artifact / "parts" / f"{task_id}.md"
        part_json = artifact / "parts" / f"{task_id}.caps.json"
        evidence_dir = artifact / "evidence" / task_id

        assert part_md.is_file(), f"missing parts markdown: {part_md}"
        assert part_md.read_text(encoding="utf-8").strip(), f"empty parts markdown: {part_md}"

        assert part_json.is_file(), f"missing caps fragment: {part_json}"
        # Fragment is itself a JSON object that round-trips through Capabilities.
        fragment = json.loads(part_json.read_text(encoding="utf-8"))
        assert isinstance(fragment, dict) and fragment, (
            f"caps fragment must be a non-empty JSON object: {part_json}"
        )
        Capabilities.model_validate(fragment)

        assert evidence_dir.is_dir(), f"missing evidence dir: {evidence_dir}"
        evidence_files = [p for p in evidence_dir.rglob("*") if p.is_file()]
        assert evidence_files, f"evidence dir is empty: {evidence_dir}"


def test_caps_fragments_merge_into_complete_capabilities_without_conflicts(
    tmp_path: Path,
) -> None:
    """All four fragments deep-merge into a Capabilities document with zero conflicts."""
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    for iter_id, task_id in EXEC_TASK_BY_ITER.items():
        src = (
            CASSETTE_DIR
            / iter_id
            / "workspace_after"
            / "artifact"
            / "parts"
            / f"{task_id}.caps.json"
        )
        (parts_dir / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    capabilities, conflicts = merge_fragments(parts_dir)

    assert conflicts == []
    # Spot-check the headline capability claims the fixture is meant to advertise.
    assert capabilities.cart.type == "drawer"
    assert capabilities.search.has_predictive is True
    assert capabilities.site_shell.has_mega_menu is True
    assert capabilities.intl.has_locale_switcher is True
    assert capabilities.collection.filters == ["size", "color", "price"]
    assert capabilities.collection.sort == [
        "featured",
        "price_asc",
        "price_desc",
        "newest",
    ]
    assert capabilities.homepage.section_count == EXPECTED_HOMEPAGE_SECTION_COUNT
