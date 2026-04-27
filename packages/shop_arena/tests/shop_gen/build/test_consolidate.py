"""Unit tests for :mod:`shop_gen.build.consolidate` (T5.8).

Covers the implementation-plan acceptance criteria from
``docs/impl/shop_gen_implementation.md`` T5.8 and the spec contract from
``docs/specs/shop_arena/shop_gen.md`` §5.5.4:

* a planner output missing ``consolidate`` is patched to include it,
* an existing ``consolidate`` task is left untouched (any status),
* the appended bullet matches the canonical priority + brief from
  ``planner.md`` §2,
* surrounding plan structure (prose, ``## Omitted Areas``, blank lines,
  trailing newline) is preserved byte-for-byte,
* structural ``plan.md`` errors propagate as
  :class:`harness.plan.parser.InvalidPlanError`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from harness.plan import TaskStatus, parse
from harness.plan.parser import InvalidPlanError
from shop_gen.build.consolidate import (
    CONSOLIDATE_BRIEF,
    CONSOLIDATE_PRIORITY,
    CONSOLIDATE_TASK_ID,
    ensure_consolidate_task,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

_PLAN_WITHOUT_CONSOLIDATE: Final[str] = """\
# Plan — generic apparel storefront

A small apparel store.

## Tasks

- [ ] gen_theme — ship the theme tokens [priority: 9]
- [ ] gen_navigation — wire the header / footer [priority: 8]
- [ ] gen_homepage — render the hero + featured collections [priority: 7]

## Omitted Areas

- (none)
"""
"""Planner snapshot that *forgot* to emit the mandatory ``consolidate`` task."""

_PLAN_WITH_CONSOLIDATE: Final[str] = """\
# Plan — generic apparel storefront

A small apparel store.

## Tasks

- [ ] gen_theme — ship the theme tokens [priority: 9]
- [ ] gen_navigation — wire the header / footer [priority: 8]
- [ ] consolidate — REQUIRED final task; cross-task cleanup [priority: 1]

## Omitted Areas

- (none)
"""
"""Compliant planner snapshot — consolidate is already emitted."""


@pytest.fixture
def plan_path_missing(tmp_path: Path) -> Path:
    """Write the missing-consolidate fixture to a temp ``plan.md`` and return its path."""
    path = tmp_path / "plan.md"
    path.write_text(_PLAN_WITHOUT_CONSOLIDATE, encoding="utf-8")
    return path


@pytest.fixture
def plan_path_with(tmp_path: Path) -> Path:
    """Write the compliant fixture to a temp ``plan.md`` and return its path."""
    path = tmp_path / "plan.md"
    path.write_text(_PLAN_WITH_CONSOLIDATE, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Happy path — T5.8 (orchestrator appends when planner omits)
# --------------------------------------------------------------------------- #


def test_ensure_consolidate_task_appends_when_planner_omits(plan_path_missing: Path) -> None:
    """T5.8: planner output missing ``consolidate`` → orchestrator appends it."""
    new_id = ensure_consolidate_task(plan_path_missing)

    assert new_id == CONSOLIDATE_TASK_ID
    plan = parse(plan_path_missing.read_text(encoding="utf-8"))
    consolidate = plan.by_id(CONSOLIDATE_TASK_ID)
    assert consolidate is not None
    assert consolidate.status is TaskStatus.PENDING


def test_ensure_consolidate_task_appends_with_canonical_priority(
    plan_path_missing: Path,
) -> None:
    """The appended task carries the canonical priority 1 from planner.md §2."""
    ensure_consolidate_task(plan_path_missing)

    plan = parse(plan_path_missing.read_text(encoding="utf-8"))
    consolidate = plan.by_id(CONSOLIDATE_TASK_ID)
    assert consolidate is not None
    assert consolidate.priority == CONSOLIDATE_PRIORITY


def test_ensure_consolidate_task_appends_canonical_brief(plan_path_missing: Path) -> None:
    """The appended bullet's note matches the canonical brief verbatim."""
    ensure_consolidate_task(plan_path_missing)

    plan = parse(plan_path_missing.read_text(encoding="utf-8"))
    consolidate = plan.by_id(CONSOLIDATE_TASK_ID)
    assert consolidate is not None
    assert consolidate.note == CONSOLIDATE_BRIEF


def test_ensure_consolidate_task_inserts_after_existing_tasks(
    plan_path_missing: Path,
) -> None:
    """The new bullet lands after the last existing ``## Tasks`` bullet."""
    ensure_consolidate_task(plan_path_missing)

    after = plan_path_missing.read_text(encoding="utf-8")
    last_existing_idx = -1
    consolidate_idx = -1
    for i, line in enumerate(after.splitlines()):
        if "gen_homepage" in line and line.startswith("- ["):
            last_existing_idx = i
        if CONSOLIDATE_TASK_ID in line and line.startswith("- ["):
            consolidate_idx = i
    assert last_existing_idx != -1
    assert consolidate_idx > last_existing_idx


def test_ensure_consolidate_task_preserves_prose_and_omitted_areas(
    plan_path_missing: Path,
) -> None:
    """Prose, ``## Omitted Areas``, blank lines, and the trailing newline are untouched."""
    before = plan_path_missing.read_text(encoding="utf-8")
    ensure_consolidate_task(plan_path_missing)
    after = plan_path_missing.read_text(encoding="utf-8")

    # Every original line still appears (only an addition is allowed).
    for line in before.splitlines():
        assert line in after.splitlines(), f"line {line!r} disappeared"
    # File still terminates with a newline.
    assert after.endswith("\n")
    # The ``## Omitted Areas`` section is still present.
    assert "## Omitted Areas" in after


# --------------------------------------------------------------------------- #
# No-op path — planner already emitted consolidate
# --------------------------------------------------------------------------- #


def test_ensure_consolidate_task_returns_none_when_already_present(
    plan_path_with: Path,
) -> None:
    """When ``consolidate`` is already in the plan the helper is a no-op."""
    before = plan_path_with.read_text(encoding="utf-8")

    result = ensure_consolidate_task(plan_path_with)
    after = plan_path_with.read_text(encoding="utf-8")

    assert result is None
    # File is unchanged byte-for-byte.
    assert before == after


def test_ensure_consolidate_task_no_op_for_done_consolidate(tmp_path: Path) -> None:
    """An already-DONE ``consolidate`` task is also treated as satisfied."""
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(
        "## Tasks\n\n"
        "- [x] gen_theme — done [priority: 9]\n"
        "- [x] consolidate — already-done [priority: 1]\n",
        encoding="utf-8",
    )
    before = plan_path.read_text(encoding="utf-8")

    result = ensure_consolidate_task(plan_path)
    after = plan_path.read_text(encoding="utf-8")

    assert result is None
    assert before == after


# --------------------------------------------------------------------------- #
# Stub-plan path — empty ``## Tasks`` section (Workspace.create scaffold)
# --------------------------------------------------------------------------- #


def test_ensure_consolidate_task_inserts_after_heading_when_no_tasks(tmp_path: Path) -> None:
    """An empty ``## Tasks`` section gets the new bullet right after the heading."""
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Plan\n\n## Tasks\n", encoding="utf-8")

    new_id = ensure_consolidate_task(plan_path)

    assert new_id == CONSOLIDATE_TASK_ID
    plan = parse(plan_path.read_text(encoding="utf-8"))
    consolidate = plan.by_id(CONSOLIDATE_TASK_ID)
    assert consolidate is not None
    assert consolidate.priority == CONSOLIDATE_PRIORITY


# --------------------------------------------------------------------------- #
# Idempotency — repeated calls
# --------------------------------------------------------------------------- #


def test_ensure_consolidate_task_is_idempotent(plan_path_missing: Path) -> None:
    """Calling the helper twice in a row leaves a single ``consolidate`` task."""
    ensure_consolidate_task(plan_path_missing)
    after_first = plan_path_missing.read_text(encoding="utf-8")

    second = ensure_consolidate_task(plan_path_missing)
    after_second = plan_path_missing.read_text(encoding="utf-8")

    assert second is None
    assert after_first == after_second
    plan = parse(after_second)
    consolidate_count = sum(1 for t in plan.tasks if t.id == CONSOLIDATE_TASK_ID)
    assert consolidate_count == 1


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #


def test_ensure_consolidate_task_surfaces_invalid_plan(tmp_path: Path) -> None:
    """Structural ``plan.md`` errors propagate as :class:`InvalidPlanError`."""
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# no tasks heading here\n", encoding="utf-8")

    with pytest.raises(InvalidPlanError):
        ensure_consolidate_task(plan_path)


def test_ensure_consolidate_task_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ensure_consolidate_task(tmp_path / "plan.md")
