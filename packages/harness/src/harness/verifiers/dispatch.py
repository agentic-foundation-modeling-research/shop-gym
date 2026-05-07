"""Per-iteration verifier dispatch (spec §5.3).

Called from `harness.loop` after the executor protocol checks have been
written. Filters the registered verifier list by ``applies_to``, runs each
match sequentially with timing + exception trapping, persists per-verifier
telemetry, and (when at least one verifier produced feedback) writes
``feedback.md`` so the next iteration's prompt can render it.

Blocking semantics (verifier-spec §5.3 step 4):

* any FAIL ⇒ block: rewrite ``[x]``/``[!]`` for ``selected_task_id`` →
  ``[~]`` in `plan.md` so the executor loop re-selects it.
* PASS / ADVISORY / ERROR ⇒ advance: marker is left intact.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from harness.plan.tasks import TaskList
from harness.runtimes.base import AgentRuntime
from harness.verifiers.protocol import (
    Verdict,
    Verifier,
    VerifierContext,
    VerifierResult,
    VerifierRun,
)

_log = logging.getLogger(__name__)

_VERIFIER_DIRNAME = "verifiers"
_FEEDBACK_FILENAME = "feedback.md"
_TASK_LINE_RE = re.compile(r"^(-\s+\[)([ ~x!])(\]\s+)(\S+)(.*)$")


class DispatchOutcome:
    """Aggregate result of one round of verifier dispatch.

    Attributes:
        runs: Per-verifier telemetry rows in dispatch (registration) order.
        blocking: True iff at least one verifier returned `FAIL`.
        wrote_feedback: True iff ``feedback.md`` was rewritten.
    """

    __slots__ = ("blocking", "runs", "wrote_feedback")

    def __init__(
        self,
        *,
        runs: tuple[VerifierRun, ...],
        blocking: bool,
        wrote_feedback: bool,
    ) -> None:
        self.runs = runs
        self.blocking = blocking
        self.wrote_feedback = wrote_feedback


def dispatch_verifiers(
    *,
    verifiers: Sequence[Verifier],
    iter_dir: Path,
    iter_id: str,
    run_dir: Path,
    selected_task_id: str,
    plan: TaskList,
    artifact_dir: Path,
    runtime: AgentRuntime,
    feedback_max_chars: int,
) -> DispatchOutcome:
    """Run every applicable verifier and persist its outcome.

    Args:
        verifiers: Caller-registered verifier sequence in invocation
            order. May be empty (no-op).
        iter_dir: Per-iteration directory; ``checks/verifiers/`` lands
            beneath it.
        iter_id: Iteration id this dispatch attributes to.
        run_dir: Workspace root; copied verbatim into each verifier's
            `VerifierContext`.
        selected_task_id: Task the executor was scheduled against.
        plan: Parsed post-iteration `plan.md` snapshot.
        artifact_dir: Convenience alias passed to verifiers.
        runtime: Live `AgentRuntime` so LLM-based verifiers can reuse
            ``runtime.complete``.
        feedback_max_chars: Truncation budget honoured when rendering
            ``feedback.md`` for the next iteration's prompt slot.

    Returns:
        A `DispatchOutcome` summarising the round.
    """
    if not verifiers:
        return DispatchOutcome(runs=(), blocking=False, wrote_feedback=False)

    applicable = [v for v in verifiers if v.applies_to(selected_task_id)]
    if not applicable:
        return DispatchOutcome(runs=(), blocking=False, wrote_feedback=False)

    checks_dir = iter_dir / "checks" / _VERIFIER_DIRNAME
    checks_dir.mkdir(parents=True, exist_ok=True)

    runs: list[VerifierRun] = []
    feedback_sections: list[tuple[str, str]] = []
    blocking = False

    for verifier in applicable:
        ctx = VerifierContext(
            run_dir=run_dir,
            iter_id=iter_id,
            selected_task_id=selected_task_id,
            plan=plan,
            artifact_dir=artifact_dir,
            runtime=runtime,
        )
        started_at = dt.datetime.now(dt.UTC)
        started_perf = time.perf_counter()
        try:
            result = verifier.run(ctx)
        except Exception as exc:
            _log.warning(
                "verifier %r raised during %s: %s",
                verifier.name,
                iter_id,
                exc,
            )
            result = VerifierResult(verdict=Verdict.ERROR, feedback=str(exc))
        duration_ms = int((time.perf_counter() - started_perf) * 1000)

        rel_path = f"iters/{iter_id}/checks/{_VERIFIER_DIRNAME}/{verifier.name}.json"
        _write_verifier_record(
            path=checks_dir / f"{verifier.name}.json",
            iter_id=iter_id,
            name=verifier.name,
            task_id=selected_task_id,
            result=result,
            started_at=started_at,
            duration_ms=duration_ms,
        )

        runs.append(
            VerifierRun(
                iter_id=iter_id,
                name=verifier.name,
                task_id=selected_task_id,
                verdict=result.verdict,
                started_at_iso=started_at.isoformat(),
                duration_ms=duration_ms,
                path=rel_path,
            )
        )
        if result.verdict is Verdict.FAIL:
            blocking = True
        if result.verdict in (Verdict.FAIL, Verdict.ADVISORY) and result.feedback:
            feedback_sections.append((verifier.name, result.feedback))

    wrote_feedback = False
    if feedback_sections:
        _write_feedback_md(
            checks_dir / _FEEDBACK_FILENAME,
            sections=feedback_sections,
        )
        wrote_feedback = True

    if blocking:
        rewrite_selected_task_marker(run_dir / "plan.md", selected_task_id)

    if blocking and feedback_max_chars <= 0:
        # Truncation budget of zero or negative is rejected upstream by
        # `PlanExecLoopConfig`; defensive guard so a future direct call
        # cannot silently surface unbounded feedback.
        raise ValueError("feedback_max_chars must be positive when verifiers run")

    return DispatchOutcome(
        runs=tuple(runs),
        blocking=blocking,
        wrote_feedback=wrote_feedback,
    )


def render_feedback_for_prompt(
    feedback_path: Path,
    *,
    max_chars: int,
) -> str:
    """Read `feedback.md` and return its (possibly truncated) body.

    Returns the empty string when the file is absent so callers can
    inject the result into a prompt template unconditionally.
    """
    if not feedback_path.is_file():
        return ""
    body = feedback_path.read_text(encoding="utf-8")
    if max_chars <= 0 or len(body) <= max_chars:
        return body
    return body[:max_chars] + "\n[...truncated]"


def rewrite_selected_task_marker(plan_md_path: Path, selected_task_id: str) -> None:
    """Rewrite `[x]` or `[!]` → `[~]` for `selected_task_id` in `plan.md`.

    Preserves task brief, priority, note trailer, and any other
    line-level metadata. Lines that do not match the expected task-line
    shape are left untouched. The whole-file rewrite is atomic via
    `Path.replace`.

    Args:
        plan_md_path: Path to the live `plan.md`.
        selected_task_id: Task id whose marker should be rewritten.
    """
    if not plan_md_path.is_file():
        return
    original = plan_md_path.read_text(encoding="utf-8")
    new_lines: list[str] = []
    changed = False
    for line in original.splitlines(keepends=True):
        match = _TASK_LINE_RE.match(line.rstrip("\n"))
        if match is None:
            new_lines.append(line)
            continue
        marker, ident = match.group(2), match.group(4)
        if ident != selected_task_id:
            new_lines.append(line)
            continue
        if marker not in ("x", "!"):
            new_lines.append(line)
            continue
        rebuilt = f"{match.group(1)}~{match.group(3)}{ident}{match.group(5)}"
        # Re-attach the trailing newline if present in the original line.
        if line.endswith("\n"):
            rebuilt += "\n"
        new_lines.append(rebuilt)
        changed = True
    if not changed:
        return
    tmp = plan_md_path.with_suffix(plan_md_path.suffix + ".tmp")
    tmp.write_text("".join(new_lines), encoding="utf-8")
    tmp.replace(plan_md_path)


def _write_verifier_record(
    *,
    path: Path,
    iter_id: str,
    name: str,
    task_id: str,
    result: VerifierResult,
    started_at: dt.datetime,
    duration_ms: int,
) -> None:
    """Persist one per-verifier telemetry file."""
    payload: dict[str, Any] = {
        "iter_id": iter_id,
        "name": name,
        "task_id": task_id,
        "verdict": result.verdict.value,
        "started_at": started_at.isoformat(),
        "duration_ms": duration_ms,
        "feedback": result.feedback,
        "details": result.details,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_feedback_md(path: Path, *, sections: list[tuple[str, str]]) -> None:
    """Concatenate per-verifier feedback under `## <name>` headers.

    The full (untruncated) body lands on disk; truncation only happens
    at prompt render time per spec §5.5.
    """
    parts: list[str] = []
    for name, body in sections:
        parts.append(f"## {name}\n")
        parts.append(body.rstrip() + "\n")
    path.write_text("\n".join(parts), encoding="utf-8")
