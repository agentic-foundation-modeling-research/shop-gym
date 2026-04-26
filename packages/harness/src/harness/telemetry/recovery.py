"""Crash-tolerant `PlanExecLoopResult` reconstruction (spec §5.7).

`reconstruct(run_dir)` rebuilds a `PlanExecLoopResult` from the
append-only files under `iters/` plus the current `plan.md`. The
reconstruction is purely derived from telemetry; it never reads
`run.json`. If the harness process dies mid-run, a caller can still
produce a defensible result summary from disk.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from harness.config import FinalStatus, PlanExecLoopResult
from harness.plan.parser import InvalidPlanError, parse, select_next
from harness.telemetry.ids import PLAN_ITER_ID
from harness.trajectory import ProtocolCheckResult
from harness.workspace import Workspace

_EXEC_ITER_ID_RE: Final[re.Pattern[str]] = re.compile(r"^exec-\d{4}$")


def reconstruct(run_dir: Path) -> PlanExecLoopResult:
    """Rebuild a `PlanExecLoopResult` from `<run_dir>/iters/` plus `plan.md`.

    The reconstruction is purely derived from append-only telemetry and
    the current plan snapshot; it never reads `run.json` itself. This is
    the §5.7 crash-recovery validator: if the harness process dies
    mid-run, a caller can still produce a defensible result summary
    from disk.

    Inferred ``final_status``:

    * `INVALID_PLAN` if `plan.md` exists but fails the parser.
    * `PROTOCOL_VIOLATION` if any executor's
      ``checks/protocol.json`` reports ``passed=false``.
    * `COMPLETED` if `plan.md` parses and no PENDING tasks remain.
    * `BUDGET_EXHAUSTED` otherwise.

    Args:
        run_dir: Path to a run workspace produced by `Workspace.create`.

    Returns:
        A `PlanExecLoopResult` whose iteration counts and trajectory
        paths reflect the on-disk state.

    Raises:
        FileNotFoundError: If `<run_dir>/iters/` does not exist.
    """
    workspace = Workspace(run_dir=run_dir)
    if not workspace.iters_dir.is_dir():
        raise FileNotFoundError(f"missing iters/ under run_dir: {run_dir}")

    plan_iter_count, exec_iter_dirs, trajectory_paths = _scan_iter_dirs(workspace)
    exec_iter_count = len(exec_iter_dirs)

    plan_text = workspace.plan_md.read_text(encoding="utf-8") if workspace.plan_md.is_file() else ""
    try:
        task_list = parse(plan_text) if plan_text.strip() else None
    except InvalidPlanError:
        return PlanExecLoopResult(
            run_dir=run_dir,
            final_status=FinalStatus.INVALID_PLAN,
            plan_iter_count=plan_iter_count,
            exec_iter_count=exec_iter_count,
            trajectory_paths=tuple(trajectory_paths),
            tasks_final=(),
        )

    if _any_protocol_violation(exec_iter_dirs):
        return PlanExecLoopResult(
            run_dir=run_dir,
            final_status=FinalStatus.PROTOCOL_VIOLATION,
            plan_iter_count=plan_iter_count,
            exec_iter_count=exec_iter_count,
            trajectory_paths=tuple(trajectory_paths),
            tasks_final=task_list.tasks if task_list is not None else (),
        )

    tasks_final = task_list.tasks if task_list is not None else ()
    pending_remaining = task_list is not None and select_next(task_list) is not None
    final_status = FinalStatus.BUDGET_EXHAUSTED if pending_remaining else FinalStatus.COMPLETED
    return PlanExecLoopResult(
        run_dir=run_dir,
        final_status=final_status,
        plan_iter_count=plan_iter_count,
        exec_iter_count=exec_iter_count,
        trajectory_paths=tuple(trajectory_paths),
        tasks_final=tasks_final,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _scan_iter_dirs(workspace: Workspace) -> tuple[int, list[Path], list[str]]:
    """Walk `iters/` and return (plan_iter_count, exec_dirs, trajectory_paths).

    Only iteration directories with a written `trajectory.json` are
    counted; an iteration that crashed before emitting telemetry is
    skipped so the reconstructed result satisfies the
    `PlanExecLoopResult` invariants.
    """
    iters_dir = workspace.iters_dir
    plan_dir = iters_dir / PLAN_ITER_ID
    plan_iter_count = 1 if (plan_dir / "trajectory.json").is_file() else 0

    exec_dirs = sorted(
        (p for p in iters_dir.iterdir() if p.is_dir() and _EXEC_ITER_ID_RE.match(p.name)),
        key=lambda p: p.name,
    )
    exec_dirs = [d for d in exec_dirs if (d / "trajectory.json").is_file()]

    trajectory_paths: list[str] = []
    if plan_iter_count:
        trajectory_paths.append(f"iters/{PLAN_ITER_ID}/trajectory.json")
    for d in exec_dirs:
        trajectory_paths.append(f"iters/{d.name}/trajectory.json")
    return plan_iter_count, exec_dirs, trajectory_paths


def _any_protocol_violation(exec_dirs: list[Path]) -> bool:
    """Return True if any executor's `checks/protocol.json` failed."""
    for d in exec_dirs:
        protocol_path = d / "checks" / "protocol.json"
        if not protocol_path.is_file():
            continue
        result = ProtocolCheckResult.model_validate_json(protocol_path.read_text(encoding="utf-8"))
        if not result.passed:
            return True
    return False
