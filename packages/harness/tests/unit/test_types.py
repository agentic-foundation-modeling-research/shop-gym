"""Round-trip and invariant tests for `harness.types`."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import TypeAdapter, ValidationError

from harness.types import (
    ErrorStep,
    IterationMetadata,
    MessageStep,
    ProtocolCheckResult,
    ScreenshotStep,
    Task,
    TaskList,
    TaskStatus,
    ThoughtStep,
    ToolCallStep,
    ToolResultStep,
    Trajectory,
    TrajectoryStep,
)

_TS = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# Plain value types (frozen dataclasses).
# ---------------------------------------------------------------------------


def test_task_is_frozen_and_hashable() -> None:
    task = Task(id="homepage", status=TaskStatus.PENDING)
    # frozen dataclasses with slots raise FrozenInstanceError on assignment
    with pytest.raises(AttributeError):
        task.priority = 5  # type: ignore[misc]
    # frozen dataclasses with slots are hashable
    assert hash(task) == hash(Task(id="homepage", status=TaskStatus.PENDING))


def test_task_list_by_id_returns_match() -> None:
    a = Task(id="a", status=TaskStatus.PENDING)
    b = Task(id="b", status=TaskStatus.DONE)
    tl = TaskList(tasks=(a, b))
    assert tl.by_id("a") is a
    assert tl.by_id("missing") is None


def test_task_list_with_status_preserves_order() -> None:
    a = Task(id="a", status=TaskStatus.PENDING, priority=1)
    b = Task(id="b", status=TaskStatus.DONE)
    c = Task(id="c", status=TaskStatus.PENDING, priority=3)
    tl = TaskList(tasks=(a, b, c))
    assert tl.with_status(TaskStatus.PENDING) == (a, c)


# ---------------------------------------------------------------------------
# Trajectory step variants — each round-trips through JSON via the union.
# ---------------------------------------------------------------------------


_STEP_ADAPTER: TypeAdapter[TrajectoryStep] = TypeAdapter(TrajectoryStep)


@pytest.mark.parametrize(
    "step",
    [
        ThoughtStep(timestamp=_TS, text="hmm"),
        MessageStep(timestamp=_TS, role="assistant", text="hi"),
        ToolCallStep(
            timestamp=_TS,
            call_id="c1",
            tool="bash",
            arguments={"cmd": "ls", "n": 3},
        ),
        ToolResultStep(timestamp=_TS, call_id="c1", output="ok"),
        ToolResultStep(timestamp=_TS, call_id="c1", output="boom", is_error=True),
        ScreenshotStep(timestamp=_TS, path="screenshots/s1.png"),
        ErrorStep(timestamp=_TS, message="kaboom"),
    ],
)
def test_trajectory_step_round_trips_through_json(step: TrajectoryStep) -> None:
    payload = _STEP_ADAPTER.dump_json(step)
    restored = _STEP_ADAPTER.validate_json(payload)
    assert restored == step


def test_trajectory_step_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        _STEP_ADAPTER.validate_python({"kind": "nope", "timestamp": _TS.isoformat()})


def test_trajectory_step_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ThoughtStep(timestamp=_TS, text="hi", surprise=1)  # type: ignore[call-arg]


def test_message_step_role_is_constrained() -> None:
    with pytest.raises(ValidationError):
        MessageStep(timestamp=_TS, role="weird", text="x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Trajectory container.
# ---------------------------------------------------------------------------


def test_trajectory_round_trips_through_json() -> None:
    traj = Trajectory(
        iter_id="exec-0001",
        runtime="replay",
        started_at=_TS,
        ended_at=_TS + dt.timedelta(seconds=2),
        exit_code=0,
        prompt_sha256="0" * 64,
        steps=(
            ThoughtStep(timestamp=_TS, text="planning"),
            ToolCallStep(timestamp=_TS, call_id="c1", tool="bash", arguments={}),
            ToolResultStep(timestamp=_TS, call_id="c1", output="done"),
        ),
    )
    payload = traj.model_dump_json()
    restored = Trajectory.model_validate_json(payload)
    assert restored == traj
    # tagged union deserializes back to concrete subclasses
    assert isinstance(restored.steps[0], ThoughtStep)
    assert isinstance(restored.steps[1], ToolCallStep)
    assert isinstance(restored.steps[2], ToolResultStep)


def test_trajectory_is_frozen() -> None:
    traj = Trajectory(
        iter_id="plan",
        runtime="replay",
        started_at=_TS,
        ended_at=_TS,
        exit_code=0,
        prompt_sha256="x",
    )
    with pytest.raises(ValidationError):
        traj.exit_code = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Iteration sidecars.
# ---------------------------------------------------------------------------


def test_iteration_metadata_round_trips_planner() -> None:
    meta = IterationMetadata(
        iter_id="plan",
        iter_kind="plan",
        runtime="replay",
        started_at=_TS,
        ended_at=_TS,
    )
    restored = IterationMetadata.model_validate_json(meta.model_dump_json())
    assert restored == meta
    assert restored.selected_task_id is None
    assert restored.completed_task_ids == ()


def test_iteration_metadata_round_trips_executor() -> None:
    meta = IterationMetadata(
        iter_id="exec-0001",
        iter_kind="exec",
        runtime="replay",
        started_at=_TS,
        ended_at=_TS,
        selected_task_id="homepage",
        completed_task_ids=("homepage",),
        blocked_task_ids=(),
        added_task_ids=("followup",),
    )
    restored = IterationMetadata.model_validate_json(meta.model_dump_json())
    assert restored == meta


def test_iteration_metadata_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        IterationMetadata(
            iter_id="x",
            iter_kind="other",  # type: ignore[arg-type]
            runtime="replay",
            started_at=_TS,
            ended_at=_TS,
        )


def test_protocol_check_result_round_trips() -> None:
    res = ProtocolCheckResult(
        iter_id="exec-0001",
        passed=False,
        violations=("resurrected_done_task: homepage",),
    )
    restored = ProtocolCheckResult.model_validate_json(res.model_dump_json())
    assert restored == res
    assert restored.passed is False


def test_protocol_check_result_defaults_to_no_violations() -> None:
    res = ProtocolCheckResult(iter_id="exec-0001", passed=True)
    assert res.violations == ()
