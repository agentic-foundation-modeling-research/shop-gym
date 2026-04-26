"""Plan + Exec orchestration loop (spec §5.2).

`run_plan_exec_loop(config, runtime)` runs one planner iteration followed
by zero or more executor iterations against a single workspace. The loop
owns:

* iteration lifecycle (spawn-via-runtime, snapshot, telemetry persistence),
* the workspace state machine between iterations (parse `plan.md`, select
  the next PENDING task, run protocol checks),
* deriving the terminal `FinalStatus` and rewriting `run.json` after every
  iteration.

The runtime owns: the actual subprocess spawn, the LLM/tool stack, and
the in-iteration log → `Trajectory` conversion. See
`docs/specs/harness/plan_exec_loop.md` §§5.2-5.7.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Final

from harness.config import FinalStatus, PlanExecLoopConfig, PlanExecLoopResult
from harness.plan.parser import InvalidPlanError, PlanDiff, diff, parse, select_next
from harness.plan.protocol import run_protocol_checks
from harness.plan.tasks import Task, TaskList
from harness.runtimes.base import AgentRuntime, RuntimeIterationResult
from harness.seed import check_seed
from harness.telemetry import (
    PLAN_ITER_ID,
    RunSummaryWriter,
    exec_iter_id,
    iter_dir,
)
from harness.trajectory import IterationMetadata, ProtocolCheckResult, Trajectory
from harness.workspace import Workspace

_log = logging.getLogger(__name__)

_HARNESS_CONTROL_HEADER_TEMPLATE: Final[str] = (
    "<<<harness-control>>>\nselected_task_id: {selected_task_id}\n<<<end>>>\n\n"
)
_TRAJECTORY_FILENAME: Final[str] = "trajectory.json"
_METADATA_FILENAME: Final[str] = "metadata.json"
_PROTOCOL_FILENAME: Final[str] = "protocol.json"
_PLAN_BEFORE_FILENAME: Final[str] = "plan.before.md"
_PLAN_AFTER_FILENAME: Final[str] = "plan.after.md"


def run_plan_exec_loop(
    config: PlanExecLoopConfig,
    runtime: AgentRuntime,
) -> PlanExecLoopResult:
    """Run one plan-then-loop session against `runtime` and `config`.

    The harness creates the workspace, runs a single planner iteration,
    then runs up to ``config.max_iters`` executor iterations, selecting
    the highest-priority PENDING task before each one. After every
    iteration `run.json` is rewritten atomically. The terminal
    `FinalStatus` is determined per spec §5.2.

    Args:
        config: Validated run configuration.
        runtime: Runtime adapter used to execute every iteration.

    Returns:
        A `PlanExecLoopResult` describing the run. The same payload is
        also persisted to ``<run_dir>/run.json``.
    """
    workspace = Workspace.create(config)
    config_snapshot = _build_config_snapshot(config)
    state = _LoopState(
        workspace=workspace, config=config, runtime=runtime, config_snapshot=config_snapshot
    )

    if not state.run_planner():
        return state.finalize()
    state.run_executor_loop()
    return state.finalize()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


class _LoopState:
    """Mutable bookkeeping shared between planner and executor phases.

    Kept local to this module — the public API is the free function
    `run_plan_exec_loop`. Encapsulating the state machine here keeps the
    iteration helpers small and lets `finalize` derive the terminal
    result from one place.
    """

    def __init__(
        self,
        *,
        workspace: Workspace,
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
        config_snapshot: dict[str, Any],
    ) -> None:
        self._workspace = workspace
        self._config = config
        self._runtime = runtime
        self._config_snapshot = config_snapshot
        self._plan_iter_count = 0
        self._exec_iter_count = 0
        self._trajectory_paths: list[str] = []
        self._final_status: FinalStatus | None = None

    # ------------------------------------------------------------------
    # Planner
    # ------------------------------------------------------------------

    def run_planner(self) -> bool:
        """Run the single planner iteration. Returns False on terminal failure."""
        plan_dir = iter_dir(self._workspace, PLAN_ITER_ID)
        plan_dir.mkdir(parents=True)
        self._workspace.snapshot_plan(plan_dir / _PLAN_BEFORE_FILENAME)

        prompt = self._config.prompts.planner
        _log.info("invoking %s for plan iter", type(self._runtime).__name__)
        outcome = self._invoke_runtime(iter_dir_path=plan_dir, prompt=prompt)
        if outcome.error_status is not None:
            self._final_status = outcome.error_status
            self._rewrite_run_summary()
            return False

        assert outcome.trajectory is not None  # guaranteed by error_status is None
        self._workspace.snapshot_plan(plan_dir / _PLAN_AFTER_FILENAME)
        _write_trajectory(plan_dir, outcome.trajectory)
        self._plan_iter_count = 1
        self._trajectory_paths.append(f"iters/{PLAN_ITER_ID}/{_TRAJECTORY_FILENAME}")

        seed_result = _seed_check_or_none(self._workspace, PLAN_ITER_ID)
        if seed_result is not None:
            _write_protocol_result(plan_dir, seed_result)
            if not seed_result.passed:
                _write_metadata(
                    plan_dir,
                    IterationMetadata(
                        iter_id=PLAN_ITER_ID,
                        iter_kind="plan",
                        runtime=outcome.trajectory.runtime,
                        started_at=outcome.trajectory.started_at,
                        ended_at=outcome.trajectory.ended_at,
                    ),
                )
                self._final_status = FinalStatus.PROTOCOL_VIOLATION
                self._rewrite_run_summary()
                return False

        try:
            after_tasks = _parse_workspace_plan(self._workspace)
        except InvalidPlanError:
            _write_metadata(
                plan_dir,
                IterationMetadata(
                    iter_id=PLAN_ITER_ID,
                    iter_kind="plan",
                    runtime=outcome.trajectory.runtime,
                    started_at=outcome.trajectory.started_at,
                    ended_at=outcome.trajectory.ended_at,
                ),
            )
            self._final_status = FinalStatus.INVALID_PLAN
            self._rewrite_run_summary()
            return False

        _write_metadata(
            plan_dir,
            IterationMetadata(
                iter_id=PLAN_ITER_ID,
                iter_kind="plan",
                runtime=outcome.trajectory.runtime,
                started_at=outcome.trajectory.started_at,
                ended_at=outcome.trajectory.ended_at,
            ),
        )
        # Sanity-check planner output for resurrected ids against the
        # (empty) before-state. With an empty `before` this can't fail,
        # but keeping the call here makes the planner phase symmetric
        # with the executor phase if the spec ever permits seeded plans.
        try:
            diff(TaskList(tasks=()), after_tasks)
        except InvalidPlanError:
            self._final_status = FinalStatus.INVALID_PLAN
            self._rewrite_run_summary()
            return False

        self._rewrite_run_summary()
        return True

    # ------------------------------------------------------------------
    # Executor loop
    # ------------------------------------------------------------------

    def run_executor_loop(self) -> None:
        """Drive the executor loop until completion, budget, or failure."""
        while True:
            try:
                tasks = _parse_workspace_plan(self._workspace)
            except InvalidPlanError:
                self._final_status = FinalStatus.INVALID_PLAN
                self._rewrite_run_summary()
                return

            selected = select_next(tasks)
            if selected is None:
                self._final_status = FinalStatus.COMPLETED
                self._rewrite_run_summary()
                return
            if self._exec_iter_count >= self._config.max_iters:
                self._final_status = FinalStatus.BUDGET_EXHAUSTED
                self._rewrite_run_summary()
                return

            if not self._run_one_executor(before=tasks, selected=selected):
                return

    def _run_one_executor(self, *, before: TaskList, selected: Task) -> bool:
        """Run a single executor iteration. Returns False on terminal failure."""
        next_count = self._exec_iter_count + 1
        exec_id = exec_iter_id(next_count)
        exec_dir = iter_dir(self._workspace, exec_id)
        exec_dir.mkdir(parents=True)

        self._workspace.snapshot_plan(exec_dir / _PLAN_BEFORE_FILENAME)

        prompt = _compose_executor_prompt(self._config.prompts.execute, selected.id)
        _log.info(
            "invoking %s for %s (task=%s)",
            type(self._runtime).__name__,
            exec_id,
            selected.id,
        )
        outcome = self._invoke_runtime(iter_dir_path=exec_dir, prompt=prompt)
        if outcome.error_status is not None:
            self._final_status = outcome.error_status
            self._rewrite_run_summary()
            return False

        assert outcome.trajectory is not None
        self._workspace.snapshot_plan(exec_dir / _PLAN_AFTER_FILENAME)
        _write_trajectory(exec_dir, outcome.trajectory)
        self._exec_iter_count = next_count
        self._trajectory_paths.append(f"iters/{exec_id}/{_TRAJECTORY_FILENAME}")

        try:
            after = _parse_workspace_plan(self._workspace)
            plan_diff = diff(before, after)
        except InvalidPlanError:
            self._final_status = FinalStatus.INVALID_PLAN
            self._rewrite_run_summary()
            return False

        plan_protocol_result = run_protocol_checks(
            iter_id=exec_id,
            before=before,
            after=after,
            selected_task_id=selected.id,
        )
        seed_result = _seed_check_or_none(self._workspace, exec_id)
        protocol_result = _merge_protocol_results(
            iter_id=exec_id,
            results=(plan_protocol_result, seed_result),
        )
        _write_protocol_result(exec_dir, protocol_result)
        _write_metadata(
            exec_dir,
            _build_exec_metadata(
                iter_id=exec_id,
                trajectory=outcome.trajectory,
                selected_task_id=selected.id,
                plan_diff=plan_diff,
            ),
        )

        if not protocol_result.passed:
            self._final_status = FinalStatus.PROTOCOL_VIOLATION
            self._rewrite_run_summary()
            return False

        self._rewrite_run_summary()
        return True

    # ------------------------------------------------------------------
    # Runtime + summary helpers
    # ------------------------------------------------------------------

    def _invoke_runtime(self, *, iter_dir_path: Path, prompt: str) -> _IterationOutcome:
        """Invoke the runtime, normalising prompt_sha256 and trapping errors."""
        try:
            result = self._runtime.run_iteration(
                run_dir=self._workspace.run_dir,
                iter_dir=iter_dir_path,
                prompt=prompt,
                timeout=self._config.timeout,
            )
        except subprocess.TimeoutExpired:
            return _IterationOutcome(error_status=FinalStatus.TIMEOUT)
        except Exception:  # any runtime exception aborts the run as RUNTIME_ERROR
            return _IterationOutcome(error_status=FinalStatus.RUNTIME_ERROR)
        return _IterationOutcome(trajectory=_normalize_trajectory(result, prompt))

    def finalize(self) -> PlanExecLoopResult:
        """Build the final `PlanExecLoopResult` and ensure `run.json` is current."""
        # If the loop reached this point without setting a status (no
        # planner phase failure, no terminal in the executor loop), it is
        # a completed run — the executor loop only exits via an explicit
        # status assignment, but defensive coverage keeps mypy/pyright
        # happy and protects against future control-flow changes.
        if self._final_status is None:
            self._final_status = FinalStatus.COMPLETED

        return self._rewrite_run_summary()

    def _rewrite_run_summary(self) -> PlanExecLoopResult:
        """Rebuild the `PlanExecLoopResult` and atomically rewrite `run.json`."""
        status = self._final_status if self._final_status is not None else FinalStatus.COMPLETED
        result = PlanExecLoopResult(
            run_dir=self._workspace.run_dir,
            final_status=status,
            plan_iter_count=self._plan_iter_count,
            exec_iter_count=self._exec_iter_count,
            trajectory_paths=tuple(self._trajectory_paths),
            tasks_final=_safe_parse_tasks(self._workspace),
        )
        RunSummaryWriter.rewrite(
            self._workspace.run_dir,
            result=result,
            config_snapshot=self._config_snapshot,
        )
        return result


class _IterationOutcome:
    """Internal result of a single runtime invocation.

    Either `trajectory` is set (successful run) or `error_status` is set
    (terminal failure). Never both.
    """

    __slots__ = ("error_status", "trajectory")

    def __init__(
        self,
        *,
        trajectory: Trajectory | None = None,
        error_status: FinalStatus | None = None,
    ) -> None:
        self.trajectory = trajectory
        self.error_status = error_status


def _compose_executor_prompt(execute_body: str, selected_task_id: str) -> str:
    """Prepend the fixed `<<<harness-control>>>` header to the executor prompt."""
    header = _HARNESS_CONTROL_HEADER_TEMPLATE.format(selected_task_id=selected_task_id)
    return header + execute_body


def _normalize_trajectory(result: RuntimeIterationResult, prompt: str) -> Trajectory:
    """Override the trajectory's `prompt_sha256` with the harness-computed digest.

    The harness controls which prompt the runtime received; recomputing
    the digest here decouples telemetry correctness from each runtime's
    fidelity at filling in this field.
    """
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if result.trajectory.prompt_sha256 == digest:
        return result.trajectory
    return result.trajectory.model_copy(update={"prompt_sha256": digest})


def _parse_workspace_plan(workspace: Workspace) -> TaskList:
    """Parse the live `plan.md`. Empty content yields an empty task list."""
    text = workspace.plan_md.read_text(encoding="utf-8")
    if not text.strip():
        return TaskList(tasks=())
    return parse(text)


def _safe_parse_tasks(workspace: Workspace) -> tuple[Task, ...]:
    """Parse the live `plan.md`, returning `()` if the snapshot is invalid."""
    try:
        return _parse_workspace_plan(workspace).tasks
    except InvalidPlanError:
        return ()


def _write_trajectory(iter_dir_path: Path, trajectory: Trajectory) -> None:
    """Persist `trajectory.json` in stable pretty-printed form."""
    payload = trajectory.model_dump(mode="json")
    (iter_dir_path / _TRAJECTORY_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_metadata(iter_dir_path: Path, metadata: IterationMetadata) -> None:
    """Persist `metadata.json` for one iteration."""
    payload = metadata.model_dump(mode="json")
    (iter_dir_path / _METADATA_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_protocol_result(iter_dir_path: Path, result: ProtocolCheckResult) -> None:
    """Persist `checks/protocol.json` for one iteration (planner or executor)."""
    checks_dir = iter_dir_path / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)
    payload = result.model_dump(mode="json")
    (checks_dir / _PROTOCOL_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _seed_check_or_none(workspace: Workspace, iter_id: str) -> ProtocolCheckResult | None:
    """Run the seed-immutability check if a manifest is present, else `None`.

    Spec: `docs/specs/harness/seed_immutability.md`. The check is a no-op
    when ``config.artifact_seed_dir`` was not provided.
    """
    if workspace.seed_manifest is None:
        return None
    return check_seed(workspace.seed_manifest, workspace.artifact_dir, iter_id=iter_id)


def _merge_protocol_results(
    *,
    iter_id: str,
    results: tuple[ProtocolCheckResult | None, ...],
) -> ProtocolCheckResult:
    """Concatenate violations from one or more `ProtocolCheckResult`s.

    Order is preserved across the input tuple, so plan-protocol violations
    appear first and seed violations after — matching the order callers
    pass them in. ``None`` entries are skipped, letting callers thread an
    optional seed result without conditional branching.
    """
    violations: list[str] = []
    for result in results:
        if result is None:
            continue
        violations.extend(result.violations)
    return ProtocolCheckResult(
        iter_id=iter_id,
        passed=not violations,
        violations=tuple(violations),
    )


def _build_exec_metadata(
    *,
    iter_id: str,
    trajectory: Trajectory,
    selected_task_id: str,
    plan_diff: PlanDiff,
) -> IterationMetadata:
    """Assemble an executor `IterationMetadata` from runtime + diff outputs."""
    return IterationMetadata(
        iter_id=iter_id,
        iter_kind="exec",
        runtime=trajectory.runtime,
        started_at=trajectory.started_at,
        ended_at=trajectory.ended_at,
        selected_task_id=selected_task_id,
        completed_task_ids=plan_diff.completed_task_ids,
        blocked_task_ids=plan_diff.blocked_task_ids,
        added_task_ids=plan_diff.added_task_ids,
    )


def _build_config_snapshot(config: PlanExecLoopConfig) -> dict[str, Any]:
    """Return a JSON-safe echo of `config` for `run.json`'s `config_snapshot`."""
    return config.model_dump(mode="json")
