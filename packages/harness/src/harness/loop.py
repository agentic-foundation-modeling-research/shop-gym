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

When `config.run_dir` already exists and is non-empty, the loop enters
*resume mode* (`docs/specs/harness/resume.md`): the workspace is opened
via `Workspace.open` (identity check), partial executor dirs are
quarantined, loop counters are reconstructed from `iters/`, and the
planner is skipped if its trajectory is already on disk.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Final, cast

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
    reconstruct,
)
from harness.telemetry.recovery import scan_iter_dirs
from harness.trajectory import IterationMetadata, ProtocolCheckResult, Trajectory
from harness.verifiers.dispatch import (
    dispatch_verifiers,
    render_feedback_for_prompt,
)
from harness.verifiers.protocol import VerifierRun
from harness.workspace import Workspace

_log = logging.getLogger(__name__)

_HARNESS_CONTROL_HEADER_TEMPLATE: Final[str] = (
    "<<<harness-control>>>\nselected_task_id: {selected_task_id}\n<<<end>>>\n\n"
)
_VERIFIER_FEEDBACK_PLACEHOLDER: Final[str] = "{{verifier_feedback}}"
_VERIFIER_FEEDBACK_FILENAME: Final[str] = "feedback.md"
_TRAJECTORY_FILENAME: Final[str] = "trajectory.json"
_METADATA_FILENAME: Final[str] = "metadata.json"
_PROTOCOL_FILENAME: Final[str] = "protocol.json"
_PLAN_BEFORE_FILENAME: Final[str] = "plan.before.md"
_PLAN_AFTER_FILENAME: Final[str] = "plan.after.md"
_ABORTED_SENTINEL_FILENAME: Final[str] = "aborted.txt"
_EXEC_ITER_ID_RE: Final[re.Pattern[str]] = re.compile(r"^exec-\d{4}$")
_REFUSAL_STATUSES: Final[frozenset[FinalStatus]] = frozenset(
    {
        FinalStatus.PROTOCOL_VIOLATION,
        FinalStatus.INVALID_PLAN,
        FinalStatus.RUNTIME_ERROR,
    }
)


class ResumeRefusedError(Exception):
    """Raised when the prior `final_status` implies the workspace is in a bad state.

    Refusals are governed by `docs/specs/harness/resume.md` §5.5:
    `protocol_violation`, `invalid_plan`, `runtime_error`, and an
    indeterminate prior status all refuse by default. Pass
    ``force=True`` to `run_plan_exec_loop` (CLI: ``--force-resume``)
    to override.

    Attributes:
        run_dir: The workspace path the harness refused to resume.
        prior_status: The terminal `FinalStatus` read from the prior
            run, or ``None`` when neither `run.json` nor
            `reconstruct()` could establish one.
    """

    def __init__(
        self,
        *,
        run_dir: Path,
        prior_status: FinalStatus | None,
    ) -> None:
        self.run_dir = run_dir
        self.prior_status = prior_status
        prior_repr = prior_status.value if prior_status is not None else "unknown"
        super().__init__(
            f"refusing to resume run_dir={run_dir} with prior final_status={prior_repr}; "
            "pass force=True to override (--force-resume)"
        )


def run_plan_exec_loop(
    config: PlanExecLoopConfig,
    runtime: AgentRuntime,
    *,
    force: bool = False,
) -> PlanExecLoopResult:
    """Run one plan-then-loop session against `runtime` and `config`.

    Mode is inferred from `config.run_dir`: an empty (or non-existent)
    directory triggers a *fresh* run (`Workspace.create`), and a
    non-empty directory triggers a *resume* (`Workspace.open` plus the
    §5.3 loop-state reconstruction). In both modes the harness drives a
    single planner iteration followed by up to ``config.max_iters``
    executor iterations, selecting the highest-priority PENDING task
    before each one. After every iteration `run.json` is rewritten
    atomically. The terminal `FinalStatus` is determined per spec §5.2.

    Args:
        config: Validated run configuration.
        runtime: Runtime adapter used to execute every iteration.
        force: When `True`, override the §5.5 refusal policy for
            bad-state prior runs (`protocol_violation`, `invalid_plan`,
            `runtime_error`, or indeterminate prior status). Has no
            effect on identity-tuple mismatches and no effect on a
            fresh run.

    Returns:
        A `PlanExecLoopResult` describing the run. The same payload is
        also persisted to ``<run_dir>/run.json``.

    Raises:
        ResumeMismatchError: In resume mode, when the on-disk identity
            tuple disagrees with `config` (`Workspace.open` §5.2).
        ResumeRefusedError: In resume mode, when the prior
            `final_status` implies a bad state and `force` is `False`
            (resume.md §5.5).
    """
    if _is_existing_workspace(config.run_dir):
        workspace = Workspace.open(config.run_dir, config=config)
        prior_status = _read_prior_final_status(workspace.run_dir)
        _enforce_refusal_policy(prior_status, run_dir=workspace.run_dir, force=force)
        _quarantine_partial_iters(workspace, prior_status=prior_status)
        prior_resume_history = _read_prior_resume_history(workspace.run_dir)
    else:
        workspace = Workspace.create(config)
        prior_status = None
        prior_resume_history = []

    config_snapshot = _build_config_snapshot(config)
    state = _LoopState(
        workspace=workspace,
        config=config,
        runtime=runtime,
        config_snapshot=config_snapshot,
        prior_resume_history=prior_resume_history,
    )
    state.restore_from_disk()

    if not state.plan_already_recorded() and not state.run_planner():
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
        prior_resume_history: list[dict[str, Any]],
    ) -> None:
        self._workspace = workspace
        self._config = config
        self._runtime = runtime
        self._config_snapshot = config_snapshot
        self._prior_resume_history = prior_resume_history
        self._attempt_started_at = dt.datetime.now(dt.UTC)
        self._plan_iter_count = 0
        self._exec_iter_count = 0
        self._exec_iter_baseline = 0
        self._trajectory_paths: list[str] = []
        self._final_status: FinalStatus | None = None
        self._verifier_runs: list[VerifierRun] = []
        # Task ids whose executor iteration ended in a recoverable failure
        # (timeout or protocol violation) within this attempt. Held in
        # runner-local state so the loop advances to the next selectable
        # task instead of looping forever. Timeouts leave the task PENDING
        # in `plan.md` (a future resume retries it); protocol violations
        # forcibly mark the task `[!]` BLOCKED in-place.
        self._skipped_task_ids: set[str] = set()
        # Latched when any executor iteration times out. Surfaces TIMEOUT
        # as the run's terminal status even when the loop later drains all
        # other tasks or exhausts its budget.
        self._had_timeout: bool = False

    # ------------------------------------------------------------------
    # Resume hooks
    # ------------------------------------------------------------------

    def restore_from_disk(self) -> None:
        """Reconstruct loop counters from `iters/` content (resume.md §5.3).

        Called once during run setup. On a fresh run this is a no-op
        (the directory has just been created and is empty). On a
        resume the counters are replayed from the same scan
        `telemetry.recovery.scan_iter_dirs` performs, so the
        reconstructed state is consistent with what
        `reconstruct(run_dir)` would produce.

        Also captures `_exec_iter_baseline` so the executor budget check
        treats `config.max_iters` as the *additional* iterations granted
        to this call (resume.md §5 — "Prior executor iterations on disk
        do not count against `max_iters`.").
        """
        plan_count, _exec_dirs, trajectory_paths = scan_iter_dirs(self._workspace)
        self._plan_iter_count = plan_count
        self._exec_iter_count = len(_exec_dirs)
        self._exec_iter_baseline = self._exec_iter_count
        self._trajectory_paths = list(trajectory_paths)

    def plan_already_recorded(self) -> bool:
        """Return True when `iters/plan/trajectory.json` is on disk (resume.md §5.3)."""
        return self._plan_iter_count > 0

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
        """Drive the executor loop until completion, budget, or failure.

        Task selection skips ids in `self._skipped_task_ids` so a single
        runaway task does not stall the rest of the plan; timed-out ids
        stay PENDING in `plan.md` and a future resume retries them.
        Protocol-violating ids are forcibly marked `[!]` BLOCKED in-place
        before being added to the skip set.

        When at least one iteration timed out and the loop would
        otherwise terminate as ``COMPLETED`` or ``BUDGET_EXHAUSTED``, the
        terminal status is overridden to ``TIMEOUT`` so the caller (and
        ``run.json``) reflect that the run did not complete cleanly.
        """
        while True:
            try:
                tasks = _parse_workspace_plan(self._workspace)
            except InvalidPlanError:
                self._final_status = FinalStatus.INVALID_PLAN
                self._rewrite_run_summary()
                return

            selected = _select_next_skipping(tasks, skip=self._skipped_task_ids)
            if selected is None:
                self._final_status = (
                    FinalStatus.TIMEOUT if self._had_timeout else FinalStatus.COMPLETED
                )
                self._rewrite_run_summary()
                return
            if (self._exec_iter_count - self._exec_iter_baseline) >= self._config.max_iters:
                self._final_status = (
                    FinalStatus.TIMEOUT if self._had_timeout else FinalStatus.BUDGET_EXHAUSTED
                )
                self._rewrite_run_summary()
                return

            if not self._run_one_executor(before=tasks, selected=selected):
                return

    def _run_one_executor(self, *, before: TaskList, selected: Task) -> bool:
        """Run a single executor iteration. Returns False on terminal failure.

        ``TIMEOUT`` and ``PROTOCOL_VIOLATION`` are both handled
        non-terminally:

        * ``TIMEOUT`` quarantines the partial iter dir to
          ``iters/<id>.aborted-<N>/`` with a sentinel; the task stays
          PENDING in `plan.md` so a future resume retries it.
        * ``PROTOCOL_VIOLATION`` restores `plan.md` from `plan.before.md`,
          force-marks the selected task `[!]` BLOCKED with a
          ``protocol_violation: <reasons>`` note, and adds it to the
          skip set so the next iteration picks a different task.

        In both cases the failing id is added to ``_skipped_task_ids``
        and the loop continues with the next selectable task.
        ``RUNTIME_ERROR`` continues to terminate the run.
        """
        next_count = self._exec_iter_count + 1
        exec_id = exec_iter_id(next_count)
        exec_dir = iter_dir(self._workspace, exec_id)
        exec_dir.mkdir(parents=True)

        self._workspace.snapshot_plan(exec_dir / _PLAN_BEFORE_FILENAME)

        feedback = self._previous_verifier_feedback(next_count)
        prompt = _compose_executor_prompt(
            self._config.prompts.execute,
            selected.id,
            verifier_feedback=feedback,
        )
        _log.info(
            "invoking %s for %s (task=%s)",
            type(self._runtime).__name__,
            exec_id,
            selected.id,
        )
        outcome = self._invoke_runtime(iter_dir_path=exec_dir, prompt=prompt)
        if outcome.error_status is FinalStatus.TIMEOUT:
            _log.warning(
                "executor iteration %s timed out on task=%s; quarantining and skipping",
                exec_id,
                selected.id,
            )
            _quarantine_iter_dir(
                self._workspace,
                exec_dir,
                reason="timeout",
            )
            self._skipped_task_ids.add(selected.id)
            self._had_timeout = True
            self._rewrite_run_summary()
            return True
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

        dispatch_outcome = dispatch_verifiers(
            verifiers=self._config.verifiers,
            iter_dir=exec_dir,
            iter_id=exec_id,
            run_dir=self._workspace.run_dir,
            selected_task_id=selected.id,
            plan=after,
            artifact_dir=self._workspace.artifact_dir,
            runtime=self._runtime,
            feedback_max_chars=self._config.verifier_feedback_max_chars,
        )
        self._verifier_runs.extend(dispatch_outcome.runs)

        if not protocol_result.passed:
            _log.warning(
                "executor iteration %s on task=%s violated protocol: %s; "
                "marking BLOCKED and continuing",
                exec_id,
                selected.id,
                ", ".join(protocol_result.violations),
            )
            _force_block_selected_task(
                workspace=self._workspace,
                plan_before_path=exec_dir / _PLAN_BEFORE_FILENAME,
                selected_task_id=selected.id,
                reasons=protocol_result.violations,
            )
            self._skipped_task_ids.add(selected.id)
            self._rewrite_run_summary()
            return True

        self._rewrite_run_summary()
        return True

    def _previous_verifier_feedback(self, next_count: int) -> str:
        """Return the previous executor iteration's `feedback.md` body.

        Returns the empty string when no prior iteration exists or when
        the prior dispatch did not write feedback. Truncated per
        ``config.verifier_feedback_max_chars`` (the full body remains on
        disk per spec §5.5).
        """
        if next_count <= 1:
            return ""
        prev_id = exec_iter_id(next_count - 1)
        prev_feedback = (
            iter_dir(self._workspace, prev_id)
            / "checks"
            / "verifiers"
            / _VERIFIER_FEEDBACK_FILENAME
        )
        return render_feedback_for_prompt(
            prev_feedback,
            max_chars=self._config.verifier_feedback_max_chars,
        )

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
            self._final_status = (
                FinalStatus.TIMEOUT if self._had_timeout else FinalStatus.COMPLETED
            )

        return self._rewrite_run_summary()

    def _rewrite_run_summary(self) -> PlanExecLoopResult:
        """Rebuild the `PlanExecLoopResult` and atomically rewrite `run.json`.

        Each rewrite re-renders ``config_snapshot.resume_history`` as
        ``prior_resume_history + [current_attempt]`` so the file always
        reflects the live state of the in-flight attempt (resume.md
        §5.7). Prior attempts' entries are immutable; the tail entry is
        the only one that mutates as the attempt progresses.
        """
        status = self._final_status if self._final_status is not None else FinalStatus.COMPLETED
        result = PlanExecLoopResult(
            run_dir=self._workspace.run_dir,
            final_status=status,
            plan_iter_count=self._plan_iter_count,
            exec_iter_count=self._exec_iter_count,
            trajectory_paths=tuple(self._trajectory_paths),
            tasks_final=_safe_parse_tasks(self._workspace),
            verifier_runs=tuple(self._verifier_runs),
        )
        snapshot = dict(self._config_snapshot)
        snapshot["resume_history"] = [
            *self._prior_resume_history,
            {
                "started_at": self._attempt_started_at.isoformat(),
                "ended_at": dt.datetime.now(dt.UTC).isoformat(),
                "final_status": status.value,
            },
        ]
        RunSummaryWriter.rewrite(
            self._workspace.run_dir,
            result=result,
            config_snapshot=snapshot,
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


def _compose_executor_prompt(
    execute_body: str,
    selected_task_id: str,
    *,
    verifier_feedback: str = "",
) -> str:
    """Prepend the harness-control header and render `{{verifier_feedback}}`.

    The header carries the selected task id (spec §5.5). The optional
    `{{verifier_feedback}}` slot is rendered from the previous
    iteration's `feedback.md` (verifiers spec §5.5). When the executor
    body does not include the placeholder, no injection happens — the
    caller decides whether the agent should see verifier feedback.
    """
    header = _HARNESS_CONTROL_HEADER_TEMPLATE.format(selected_task_id=selected_task_id)
    rendered_body = execute_body.replace(
        _VERIFIER_FEEDBACK_PLACEHOLDER,
        verifier_feedback,
    )
    return header + rendered_body


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


def _select_next_skipping(tasks: TaskList, *, skip: set[str]) -> Task | None:
    """`select_next` variant that pretends task ids in `skip` are not selectable.

    Used to bypass executor tasks that timed out earlier in this attempt
    so the loop can drain the rest of the plan. The skip set is in-memory
    only; `plan.md` is unchanged, so a future resume retries the task
    cleanly.
    """
    if not skip:
        return select_next(tasks)
    filtered = TaskList(tasks=tuple(t for t in tasks.tasks if t.id not in skip))
    return select_next(filtered)


def _safe_parse_tasks(workspace: Workspace) -> tuple[Task, ...]:
    """Parse the live `plan.md`, returning `()` if the snapshot is invalid."""
    try:
        return _parse_workspace_plan(workspace).tasks
    except InvalidPlanError:
        return ()


_TASK_LINE_FOR_REWRITE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<lead>-\s+)\[(?P<marker>.)\](?P<gap>\s+)(?P<id>\S+)(?P<rest>.*)$",
)
_PRIORITY_RE: Final[re.Pattern[str]] = re.compile(r"\[priority:\s*-?\d+\]")


def _force_block_selected_task(
    *,
    workspace: Workspace,
    plan_before_path: Path,
    selected_task_id: str,
    reasons: tuple[str, ...],
) -> None:
    """Restore `plan.md` from `plan.before.md` and force-mark a task `[!]` BLOCKED.

    The agent's plan-mutating side effects from the violating iteration
    are reversed by copying the pre-iteration snapshot back into place;
    the harness then rewrites the line that owns ``selected_task_id`` so
    its status marker becomes ``!`` and its trailing note records the
    protocol violation. The next iteration sees the task BLOCKED and the
    executor loop picks a different task.

    Falls back to writing a minimal valid plan.md when ``plan.before.md``
    is missing or the target line cannot be located — in either case the
    next iteration will re-plan rather than re-pick the same broken task.
    """
    if plan_before_path.is_file():
        text = plan_before_path.read_text(encoding="utf-8")
    else:
        text = workspace.plan_md.read_text(encoding="utf-8")

    note = "protocol_violation: " + (", ".join(reasons) if reasons else "unspecified")
    new_lines: list[str] = []
    rewritten = False
    for line in text.splitlines():
        match = _TASK_LINE_FOR_REWRITE_RE.match(line)
        if match is None or match.group("id") != selected_task_id:
            new_lines.append(line)
            continue
        rest = match.group("rest")
        priority_match = _PRIORITY_RE.search(rest)
        priority_tag = priority_match.group(0) if priority_match is not None else ""
        new_line = (
            f"{match.group('lead')}[!]{match.group('gap')}{selected_task_id}"
        )
        if priority_tag:
            new_line += f" {priority_tag}"
        new_line += f" — {note}"
        new_lines.append(new_line)
        rewritten = True

    if not rewritten:
        # Couldn't locate the line — fall back to a minimal plan so the
        # loop can re-plan from scratch on the next iteration.
        text = "## Tasks\n\n"
    else:
        text = "\n".join(new_lines)
        if not text.endswith("\n"):
            text += "\n"

    workspace.plan_md.write_text(text, encoding="utf-8")


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
    """Return a JSON-safe echo of `config` for `run.json`'s `config_snapshot`.

    The ``verifiers`` field is excluded because verifier instances are
    caller-owned objects (typically with bound runtime references) and
    are not JSON-serialisable. The numeric ``verifier_feedback_max_chars``
    is preserved.
    """
    return config.model_dump(mode="json", exclude={"verifiers"})


# ---------------------------------------------------------------------------
# Resume helpers (resume.md §§4.1, 5.4, 5.5)
# ---------------------------------------------------------------------------


def _is_existing_workspace(run_dir: Path) -> bool:
    """Return True iff `run_dir` is an existing, non-empty directory.

    Drives the resume-mode branch in `run_plan_exec_loop`: an empty or
    non-existent directory falls through to `Workspace.create`. Symbolic
    targets that are not directories fall through to fresh-mode and let
    `Workspace.create` raise its own error.
    """
    if not run_dir.exists() or not run_dir.is_dir():
        return False
    return any(run_dir.iterdir())


def _read_prior_final_status(run_dir: Path) -> FinalStatus | None:
    """Best-effort read of the prior run's `final_status` (resume.md §5.5).

    The harness rewrites `run.json` after every iteration, so its
    ``final_status`` is the most recent in-memory status the prior
    process flushed. If `run.json` is missing or malformed, fall back to
    `reconstruct(run_dir)`. Both failures collapse to ``None`` and the
    refusal policy treats that as indeterminate.
    """
    run_summary_path = run_dir / "run.json"
    payload: Any = None
    if run_summary_path.is_file():
        try:
            payload = json.loads(run_summary_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = None
    if isinstance(payload, dict):
        status_value = cast("dict[str, Any]", payload).get("final_status")
        if isinstance(status_value, str):
            try:
                return FinalStatus(status_value)
            except ValueError:
                pass
    try:
        return reconstruct(run_dir).final_status
    except (FileNotFoundError, OSError, ValueError):
        return None


def _read_prior_resume_history(run_dir: Path) -> list[dict[str, Any]]:
    """Best-effort read of `config_snapshot.resume_history` from prior `run.json`.

    Returns an empty list when `run.json` is missing, malformed, or has
    no `resume_history` field. The harness always extends this list by
    exactly one entry per attempt (resume.md §5.7), so a missing prior
    list is equivalent to a fresh single-entry history. Any non-dict
    entries in the prior list are dropped defensively to keep the
    rewritten payload schema-clean.
    """
    run_summary_path = run_dir / "run.json"
    if not run_summary_path.is_file():
        return []
    try:
        payload = json.loads(run_summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, dict):
        return []
    snapshot = cast("dict[str, Any]", payload).get("config_snapshot")
    if not isinstance(snapshot, dict):
        return []
    history = cast("dict[str, Any]", snapshot).get("resume_history")
    if not isinstance(history, list):
        return []
    typed_history = cast("list[Any]", history)
    return [cast("dict[str, Any]", entry) for entry in typed_history if isinstance(entry, dict)]


def _enforce_refusal_policy(
    prior_status: FinalStatus | None,
    *,
    run_dir: Path,
    force: bool,
) -> None:
    """Raise `ResumeRefusedError` if the prior status implies a bad state.

    See resume.md §5.5. `protocol_violation`, `invalid_plan`,
    `runtime_error`, and an indeterminate prior status (``None``) all
    refuse by default. ``force=True`` overrides every refusal.
    `completed`, `timeout`, and `budget_exhausted` always allow.
    """
    if force:
        return
    if prior_status is None or prior_status in _REFUSAL_STATUSES:
        raise ResumeRefusedError(run_dir=run_dir, prior_status=prior_status)


def _quarantine_partial_iters(
    workspace: Workspace,
    *,
    prior_status: FinalStatus | None,
) -> None:
    """Rename partial iter dirs to `<id>.aborted-<N>/` and drop a sentinel (§5.4).

    Runs once before either the planner-skip branch or the executor
    loop. A directory under ``iters/`` is "partial" when its name is a
    recognized iter id (``plan`` or ``exec-NNNN``) and it contains no
    ``trajectory.json``. The chosen ``N`` is the smallest positive
    integer that makes the destination unique, so repeated resume
    attempts append fresh quarantine dirs without colliding.

    The spec only mentions executor dirs explicitly, but a partial
    ``iters/plan/`` would otherwise cause `run_planner` to fail when it
    tries to create the directory; quarantining it is the natural
    extension and preserves the rule "every healthy iter dir
    corresponds to exactly one subprocess".

    Args:
        workspace: The workspace under resume.
        prior_status: Best-effort prior `final_status` (used in the
            sentinel body). May be ``None`` when neither `run.json` nor
            `reconstruct()` could establish one.
    """
    iters_dir = workspace.iters_dir
    if not iters_dir.is_dir():
        return
    resume_ts = dt.datetime.now(dt.UTC)
    for entry in sorted(iters_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if not _is_iter_dir_name(entry.name):
            continue
        if (entry / _TRAJECTORY_FILENAME).is_file():
            continue
        target = _next_aborted_path(iters_dir, entry.name)
        entry.rename(target)
        sentinel = (
            f"resume_at: {resume_ts.isoformat()}\n"
            f"prior_final_status: "
            f"{prior_status.value if prior_status is not None else 'unknown'}\n"
        )
        (target / _ABORTED_SENTINEL_FILENAME).write_text(sentinel, encoding="utf-8")


def _is_iter_dir_name(name: str) -> bool:
    """Return True if `name` is a recognized iter-dir id (`plan` or `exec-NNNN`)."""
    return name == PLAN_ITER_ID or _EXEC_ITER_ID_RE.match(name) is not None


def _next_aborted_path(iters_dir: Path, base_name: str) -> Path:
    """Return the next free `iters/<base>.aborted-<N>` path (N >= 1)."""
    counter = 1
    while True:
        candidate = iters_dir / f"{base_name}.aborted-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def _quarantine_iter_dir(workspace: Workspace, iter_dir_path: Path, *, reason: str) -> None:
    """Move a partial iter dir to `<id>.aborted-<N>/` with a sentinel.

    Mirrors :func:`_quarantine_partial_iters` but acts on a single dir
    mid-run (e.g. when the executor times out and the harness wants to
    free the canonical iter slot for the next selectable task).

    The dir is expected to be partial — no ``trajectory.json`` present —
    so resume's :func:`telemetry.recovery.scan_iter_dirs` will already
    ignore it; the rename only matters because the next iteration
    expects to ``mkdir`` its own dir at the canonical id and a stale
    partial would block that.

    Args:
        workspace: The active workspace.
        iter_dir_path: The iter dir to quarantine. Its parent must be
            ``workspace.iters_dir``.
        reason: Short tag written into the sentinel (e.g. ``"timeout"``).
    """
    iters_dir = workspace.iters_dir
    base_name = iter_dir_path.name
    target = _next_aborted_path(iters_dir, base_name)
    iter_dir_path.rename(target)
    sentinel = f"aborted_at: {dt.datetime.now(dt.UTC).isoformat()}\nreason: {reason}\n"
    (target / _ABORTED_SENTINEL_FILENAME).write_text(sentinel, encoding="utf-8")
