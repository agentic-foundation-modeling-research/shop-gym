"""Per-iteration telemetry helpers and the `run.json` writer (spec §5.7).

This module owns three concerns:

* **Iteration ids and per-iteration directories.** `PLAN_ITER_ID`,
  `exec_iter_id`, and `iter_dir` give every other layer a single source
  of truth for naming the planner directory (`iters/plan/`) and the
  zero-padded executor directories (`iters/exec-0001/`, ...).
* **`run.json` writer.** `RunSummaryWriter.rewrite` atomically replaces
  `run_dir/run.json` after every iteration. The on-disk payload is the
  serialised `PlanExecLoopResult` plus an optional secret-scrubbed
  `config_snapshot`.
* **Crash-tolerant reconstruction.** `reconstruct(run_dir)` rebuilds a
  `PlanExecLoopResult` from the append-only files under `iters/` and
  the current `plan.md`. This is the §5.7 validator that recovers state
  if a process dies mid-run.

No subprocess or runtime concerns live here. See
`docs/specs/harness/plan_exec_loop.md` §5.3, §5.5, and §5.7.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

from harness.config import FinalStatus, PlanExecLoopResult
from harness.plan_parser import InvalidPlanError, parse, select_next
from harness.types import ProtocolCheckResult
from harness.workspace import Workspace, atomic_write_json

PLAN_ITER_ID: Final[str] = "plan"
"""Iteration id of the single planner iteration."""

_EXEC_ITER_ID_RE: Final[re.Pattern[str]] = re.compile(r"^exec-\d{4}$")

_REDACTED: Final[str] = "***REDACTED***"

# Conservative regex matched against dict keys (case-insensitive). Any
# match means the entire value at that key is replaced with the
# redaction sentinel, regardless of nesting. The matcher is
# substring-based on purpose: it errs on the side of redacting a
# false-positive key like ``authorize`` rather than leaking a real
# token.
_SECRET_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"secret|token|password|passwd|api[_-]?key|access[_-]?key|auth|credential",
    re.IGNORECASE,
)


def exec_iter_id(n: int) -> str:
    """Return the canonical executor iteration id for the n-th executor run.

    Args:
        n: 1-indexed executor iteration ordinal.

    Returns:
        ``"exec-NNNN"`` zero-padded to four digits.

    Raises:
        ValueError: If `n` is less than 1.
    """
    if n < 1:
        raise ValueError(f"executor iteration index must be >= 1, got {n}")
    return f"exec-{n:04d}"


def iter_dir(workspace: Workspace, iter_id: str) -> Path:
    """Return the per-iteration directory under `iters/` for `iter_id`.

    Args:
        workspace: The run workspace.
        iter_id: Either `PLAN_ITER_ID` or an `exec-NNNN` id.

    Returns:
        Path to `<run_dir>/iters/<iter_id>/`. The directory is *not*
        created; callers that need it on disk should call `mkdir`.

    Raises:
        ValueError: If `iter_id` is not a recognised planner or executor id.
    """
    if iter_id != PLAN_ITER_ID and _EXEC_ITER_ID_RE.match(iter_id) is None:
        raise ValueError(f"unrecognised iter_id: {iter_id!r}")
    return workspace.iters_dir / iter_id


def scrub_secrets(value: Any) -> Any:
    """Return a deep copy of `value` with secret-shaped dict keys redacted.

    Recurses into mappings and sequences. Any mapping value whose key
    matches `_SECRET_KEY_RE` is replaced with the literal sentinel
    ``"***REDACTED***"``, regardless of the original value's type. All
    other scalars are passed through unchanged.

    The redaction is conservative: it errs on the side of dropping
    plausible secrets rather than letting them leak into `run.json`.
    """
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        out: dict[str, Any] = {}
        for raw_key, sub in mapping.items():
            key = str(raw_key)
            if _SECRET_KEY_RE.search(key):
                out[key] = _REDACTED
            else:
                out[key] = scrub_secrets(sub)
        return out
    if isinstance(value, (list, tuple)):
        seq = cast("list[object] | tuple[object, ...]", value)
        return [scrub_secrets(item) for item in seq]
    return value


class RunSummaryWriter:
    """Atomic writer for `run_dir/run.json` (spec §5.7).

    `run.json` is rewritten in full after every iteration. The payload
    is the serialised `PlanExecLoopResult` augmented with an optional
    ``config_snapshot`` field carrying the secret-free echo of the
    caller-supplied configuration.
    """

    @staticmethod
    def rewrite(
        run_dir: Path,
        *,
        result: PlanExecLoopResult,
        config_snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        """Atomically rewrite `<run_dir>/run.json`.

        Args:
            run_dir: Run workspace root. Must already exist.
            result: Authoritative result for this run, in its current
                state. Serialised verbatim.
            config_snapshot: Optional caller-supplied configuration echo.
                If given, it is deep-copied with `scrub_secrets` and
                stored under the top-level ``config_snapshot`` key.
        """
        payload: dict[str, Any] = result.model_dump(mode="json")
        if config_snapshot is not None:
            payload["config_snapshot"] = scrub_secrets(dict(config_snapshot))
        atomic_write_json(run_dir / "run.json", payload)


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
