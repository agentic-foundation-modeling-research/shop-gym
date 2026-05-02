"""Verifier protocol, context, result, and telemetry value types (spec §5.2 + §9.1).

These types form the contract callers implement when they pass
``PlanExecLoopConfig.verifiers``. The harness owns dispatch, persistence,
and feedback rendering; it owns no domain logic.

Types that cross the filesystem boundary (`VerifierResult`, `VerifierRun`)
are pydantic v2 models so they round-trip through JSON. `VerifierContext`
is also pydantic to keep validation centralised, but it carries the live
`AgentRuntime` Protocol — `arbitrary_types_allowed=True` opts that field
out of structural validation.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from harness.plan.tasks import TaskList
from harness.runtimes.base import AgentRuntime


class Verdict(StrEnum):
    """Outcome of one verifier invocation.

    Values:
        PASS: Verifier accepted the workspace; loop advances.
        FAIL: Blocking; the harness rewrites the selected task's `[x]`
            or `[!]` marker back to `[~]` for the next iteration.
        ADVISORY: Non-blocking. Feedback (if any) is surfaced to the
            next iteration but the marker is left intact.
        ERROR: Set by the harness when the verifier raised. Treated as
            ADVISORY for blocking purposes (does not block).
    """

    PASS = "pass"
    FAIL = "fail"
    ADVISORY = "advisory"
    ERROR = "error"


class VerifierResult(BaseModel):
    """Return value of `Verifier.run`.

    Attributes:
        verdict: One of PASS, FAIL, ADVISORY. The harness may construct
            an ERROR result on its own when `Verifier.run` raises.
        feedback: Markdown surfaced to the next iteration on FAIL and
            (optionally) ADVISORY. Empty string disables surfacing.
        details: Caller-defined structured payload, persisted verbatim
            in the per-verifier telemetry file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Verdict
    feedback: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class VerifierContext(BaseModel):
    """Runtime state handed to each `Verifier.run` invocation.

    Attributes:
        run_dir: Absolute path to the run workspace.
        iter_id: Iteration id whose post-state is being verified, e.g.
            ``"exec-0003"``.
        selected_task_id: Task id the executor was scheduled against.
        plan: Parsed `plan.md` snapshot taken after the iteration ran
            (matches the post-iteration `plan.after.md` bytes).
        artifact_dir: Convenience alias for ``run_dir / "artifact"``.
        runtime: The `AgentRuntime` driving the loop. LLM-based
            verifiers call ``runtime.complete`` (when implemented) to
            reuse the harness's model + auth path.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    run_dir: Path
    iter_id: str
    selected_task_id: str
    plan: TaskList
    artifact_dir: Path
    runtime: AgentRuntime


@runtime_checkable
class Verifier(Protocol):
    """Caller-supplied check dispatched after each executor iteration.

    Implementations live in caller code (e.g. ``shop_arena.gen.build.verifiers``).
    The harness only knows the protocol and the order of registration.

    Attributes:
        name: Filesystem-safe identifier; unique within one
            `PlanExecLoopConfig.verifiers` list. Used as the per-verifier
            telemetry filename and as the section heading in
            ``feedback.md``.
    """

    name: str

    def applies_to(self, task_id: str) -> bool:
        """Return True if the verifier should run for the given selected task."""
        ...

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Run the check against the post-iteration workspace."""
        ...


class VerifierRun(BaseModel):
    """Telemetry summary row for one verifier invocation (spec §5.6).

    Persisted both inside the per-verifier file under
    ``iters/<iter_id>/checks/verifiers/<name>.json`` and aggregated into
    ``run.json``'s ``verifier_runs`` array. The aggregated form drops
    `feedback`/`details` to keep `run.json` small; the per-verifier file
    keeps the full body.

    Attributes:
        iter_id: Iteration id this run is attributed to.
        name: Verifier name (matches `Verifier.name`).
        task_id: Selected task id at the time of dispatch.
        verdict: Final verdict (`PASS`, `FAIL`, `ADVISORY`, or `ERROR`).
        started_at_iso: UTC ISO-8601 timestamp captured before `run()`.
        duration_ms: Wall-clock duration of the `run()` call in
            milliseconds (rounded down to int).
        path: Run-dir-relative path to the per-verifier telemetry file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    iter_id: str
    name: str
    task_id: str
    verdict: Verdict
    started_at_iso: str
    duration_ms: int = Field(ge=0)
    path: str
