"""Unit tests for :mod:`shop_arena.gen.build.redo` (T5.7).

Covers the implementation-plan acceptance criteria from
``docs/impl/shop_gen_implementation.md`` T5.7 and the spec contract from
``docs/specs/shop_arena/shop_arena.gen.md`` §5.7.3:

* the original ``[x]`` task line is byte-for-byte unchanged,
* a single redo append produces ``<base>_redo_1`` as PENDING,
* a follow-up redo against the same base produces ``<base>_redo_2``,
* errors surface as :class:`shop_arena.gen.build.redo.RedoError` (unknown id,
  non-DONE id) or :class:`harness.plan.parser.InvalidPlanError`
  (corrupted ``plan.md``).

CLI integration is tested separately so this module can stay
filesystem-pure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from harness.plan import TaskStatus, parse
from harness.plan.parser import InvalidPlanError
from shop_arena.gen.build.redo import RedoError, append_redo_task

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

_COMPLETED_PLAN: Final[str] = """\
# Plan — generic apparel storefront

A small apparel store that sells fitted t-shirts and accessories.

## Tasks

- [x] gen_theme — ship the theme tokens [priority: 9]
- [x] gen_navigation — wire the header / footer [priority: 8]
- [x] gen_homepage — render the hero + featured collections [priority: 7]
- [x] gen_collections — collection list / detail [priority: 6]
- [x] gen_product — PDP with variant pickers [priority: 5]
- [x] gen_cart_search — cart drawer + predictive search [priority: 4]
- [x] gen_info_pages — about / contact / policies [priority: 3]
- [x] visual_fix — REQUIRED final task; cross-task cleanup [priority: 2]

## Omitted Areas

- (none)
"""
"""Realistic completed snapshot mirroring the planner.md canonical block."""

_TARGET_TASK_ID: Final[str] = "gen_homepage"
_TARGET_TASK_LINE: Final[str] = (
    "- [x] gen_homepage — render the hero + featured collections [priority: 7]"
)


@pytest.fixture
def plan_path(tmp_path: Path) -> Path:
    """Write the completed-run fixture to a temp ``plan.md`` and return its path."""
    path = tmp_path / "plan.md"
    path.write_text(_COMPLETED_PLAN, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Happy path — T5.7 (a) + (b)
# --------------------------------------------------------------------------- #


def test_append_redo_task_returns_first_redo_suffix(plan_path: Path) -> None:
    """T5.7 (b): the first append produces ``<base>_redo_1``."""
    new_id = append_redo_task(plan_path, _TARGET_TASK_ID)

    assert new_id == f"{_TARGET_TASK_ID}_redo_1"


def test_append_redo_task_preserves_original_done_marker(plan_path: Path) -> None:
    """T5.7 (a): the original ``[x] gen_homepage`` line is untouched."""
    append_redo_task(plan_path, _TARGET_TASK_ID)

    after = plan_path.read_text(encoding="utf-8")
    assert _TARGET_TASK_LINE in after, "original [x] task line was rewritten"


def test_append_redo_task_appends_pending_bullet(plan_path: Path) -> None:
    """The new bullet parses as a PENDING task linked back to the base id."""
    new_id = append_redo_task(plan_path, _TARGET_TASK_ID)

    after = plan_path.read_text(encoding="utf-8")
    plan = parse(after)
    new_task = plan.by_id(new_id)
    assert new_task is not None
    assert new_task.status is TaskStatus.PENDING
    assert new_task.note is not None
    assert _TARGET_TASK_ID in new_task.note


def test_append_redo_task_default_priority_is_one(plan_path: Path) -> None:
    """Default priority sits one below visual_fix (priority 2)."""
    new_id = append_redo_task(plan_path, _TARGET_TASK_ID)

    plan = parse(plan_path.read_text(encoding="utf-8"))
    new_task = plan.by_id(new_id)
    assert new_task is not None
    assert new_task.priority == 1


def test_append_redo_task_preserves_other_sections(plan_path: Path) -> None:
    """Prose, ``## Omitted Areas``, and surrounding blank lines are untouched."""
    before = plan_path.read_text(encoding="utf-8")
    append_redo_task(plan_path, _TARGET_TASK_ID)
    after = plan_path.read_text(encoding="utf-8")

    # The redo flow only adds content; nothing is removed.
    for line in before.splitlines():
        assert line in after.splitlines(), f"line {line!r} disappeared"
    # File still terminates with a newline (the fixture does).
    assert after.endswith("\n")


def test_append_redo_task_inserts_after_visual_fix(plan_path: Path) -> None:
    """Spec §5.7.3 places the new task after the mandatory ``visual_fix``."""
    new_id = append_redo_task(plan_path, _TARGET_TASK_ID)

    after = plan_path.read_text(encoding="utf-8")
    visual_fix_idx = -1
    new_idx = -1
    for i, line in enumerate(after.splitlines()):
        if "visual_fix" in line and line.startswith("- ["):
            visual_fix_idx = i
        if new_id in line and line.startswith("- ["):
            new_idx = i
    assert visual_fix_idx != -1
    assert new_idx > visual_fix_idx


def test_append_redo_task_with_reason_includes_reason_in_note(plan_path: Path) -> None:
    """The optional ``reason`` is appended to the brief after a colon."""
    new_id = append_redo_task(
        plan_path,
        _TARGET_TASK_ID,
        reason="hero copy referenced a real brand",
    )

    plan = parse(plan_path.read_text(encoding="utf-8"))
    new_task = plan.by_id(new_id)
    assert new_task is not None
    assert new_task.note is not None
    assert "hero copy referenced a real brand" in new_task.note


# --------------------------------------------------------------------------- #
# Suffix increment — T5.7 (c)
# --------------------------------------------------------------------------- #


def test_append_redo_task_increments_suffix_on_followup(plan_path: Path) -> None:
    """T5.7 (c): a follow-up call produces ``<base>_redo_2``."""
    first_id = append_redo_task(plan_path, _TARGET_TASK_ID)
    second_id = append_redo_task(plan_path, _TARGET_TASK_ID)

    assert first_id == f"{_TARGET_TASK_ID}_redo_1"
    assert second_id == f"{_TARGET_TASK_ID}_redo_2"


def test_append_redo_task_increment_skips_gaps(plan_path: Path) -> None:
    """The next suffix is ``max(existing) + 1``, even when earlier siblings are absent."""
    # Drop a hand-authored ``gen_homepage_redo_5`` into the plan.
    text = plan_path.read_text(encoding="utf-8")
    text = text.replace(
        "- [x] visual_fix — REQUIRED final task; cross-task cleanup [priority: 2]\n",
        "- [x] visual_fix — REQUIRED final task; cross-task cleanup [priority: 2]\n"
        "- [x] gen_homepage_redo_5 — earlier manual redo [priority: 1]\n",
    )
    plan_path.write_text(text, encoding="utf-8")

    new_id = append_redo_task(plan_path, _TARGET_TASK_ID)

    assert new_id == f"{_TARGET_TASK_ID}_redo_6"


def test_append_redo_task_independent_bases_do_not_share_counters(plan_path: Path) -> None:
    """Sibling counters are scoped per base id."""
    first_homepage = append_redo_task(plan_path, _TARGET_TASK_ID)
    first_navigation = append_redo_task(plan_path, "gen_navigation")
    second_homepage = append_redo_task(plan_path, _TARGET_TASK_ID)

    assert first_homepage == f"{_TARGET_TASK_ID}_redo_1"
    assert first_navigation == "gen_navigation_redo_1"
    assert second_homepage == f"{_TARGET_TASK_ID}_redo_2"


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #


def test_append_redo_task_rejects_unknown_task(plan_path: Path) -> None:
    with pytest.raises(RedoError) as excinfo:
        append_redo_task(plan_path, "gen_does_not_exist")

    assert "gen_does_not_exist" in str(excinfo.value)


def test_append_redo_task_rejects_pending_task(tmp_path: Path) -> None:
    """Only DONE tasks can be redone — PENDING is still owned by the harness."""
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(
        "## Tasks\n\n- [ ] gen_theme — pending [priority: 9]\n",
        encoding="utf-8",
    )

    with pytest.raises(RedoError) as excinfo:
        append_redo_task(plan_path, "gen_theme")

    assert "pending" in str(excinfo.value).lower()


def test_append_redo_task_rejects_blocked_task(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(
        "## Tasks\n\n- [!] gen_theme — blocked [priority: 9]\n",
        encoding="utf-8",
    )

    with pytest.raises(RedoError):
        append_redo_task(plan_path, "gen_theme")


def test_append_redo_task_surfaces_invalid_plan(tmp_path: Path) -> None:
    """Structural ``plan.md`` errors propagate as :class:`InvalidPlanError`."""
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# no tasks heading here\n", encoding="utf-8")

    with pytest.raises(InvalidPlanError):
        append_redo_task(plan_path, _TARGET_TASK_ID)


def test_append_redo_task_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        append_redo_task(tmp_path / "plan.md", _TARGET_TASK_ID)
