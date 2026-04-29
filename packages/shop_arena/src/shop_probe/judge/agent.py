"""Judge axis-C agent runner (T4.2 — spec §5.5 step 2).

Wraps the :mod:`harness` plan/exec loop with a Playwright-driven runtime
and projects the per-iteration harness telemetry into the closed
:class:`shop_probe.judge.Trajectory` schema (T4.1) that the blinded
pairwise judge later consumes (spec §5.5 steps 3-5).

The orchestration this module owns:

1. Build the planner + executor :class:`harness.Prompts` from the
   :class:`Target` and :class:`JudgeTask`.
2. Invoke :func:`harness.run_plan_exec_loop` with the caller's
   :class:`AgentRuntime`. The runtime is responsible for actually driving
   Playwright against ``target.base_url`` — production runs use
   ``claude_code`` / ``pi`` with a Playwright tool stack; tests use the
   stub runtime in ``tests/judge/test_agent.py``.
3. Walk every iteration's ``trajectory.json``, pair ``ToolCallStep`` rows
   with their matching ``ToolResultStep`` rows, attach the most recent
   reasoning + screenshot, and emit one :class:`TrajectoryStep` per pair.
4. Persist the projected :class:`Trajectory` as JSON next to the harness
   workspace so anonymization (T4.4) and pair construction (T4.5) can
   read it back.

Evidence-path convention: paths in the projected trajectory are stored
relative to the harness ``run_dir``. Screenshots come from
:class:`harness.ScreenshotStep` rows the runtime emits. Accessibility-
tree snapshots are looked up at ``iters/<iter_id>/a11y/<call_id>.json``;
when the runtime does not write one we record the
:class:`ToolResultStep.output` as the snapshot body so the schema's
required ``a11y_snapshot`` field is always populated.

This module performs no I/O at import time.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Final

from harness import (
    AgentRuntime,
    PlanExecLoopConfig,
    PlanExecLoopResult,
    Prompts,
    run_plan_exec_loop,
)
from harness.config import FinalStatus
from harness.trajectory import (
    MessageStep,
    ScreenshotStep,
    ThoughtStep,
    ToolCallStep,
    ToolResultStep,
)
from harness.trajectory import (
    Trajectory as HarnessTrajectory,
)
from shop_probe.judge.tasks import JudgeTask
from shop_probe.judge.trajectory import (
    Trajectory,
    TrajectoryAction,
    TrajectoryObservation,
    TrajectoryStatus,
    TrajectoryStep,
)
from shop_probe.report import BrowserMeta, EvidenceRef
from shop_probe.targets import Target

DEFAULT_AGENTS_MD: Final[str] = (
    "# Judge agent — Playwright storefront task runner\n\n"
    "You are an agent driving a storefront via a Playwright tool\n"
    "stack. Use the provided tools to complete each PENDING task in `plan.md`\n"
    "against the configured target URL. After every storefront action capture a\n"
    "screenshot AND an accessibility-tree snapshot before marking the task `[x]`.\n"
    "Do not navigate to URLs outside the target origin.\n"
)
"""AGENTS.md body installed in the harness workspace by default.

Production runs typically supply a richer body via the ``agents_md``
argument; this default is the minimum text the harness contract
requires (non-empty) plus the spec §5.5 step 2 capture invariants.
"""

_FINAL_STATUS_MAP: Final[dict[FinalStatus, TrajectoryStatus]] = {
    FinalStatus.COMPLETED: "completed",
    FinalStatus.BUDGET_EXHAUSTED: "completed",
    FinalStatus.INVALID_PLAN: "failed",
    FinalStatus.PROTOCOL_VIOLATION: "failed",
    FinalStatus.TIMEOUT: "timeout",
    FinalStatus.RUNTIME_ERROR: "failed",
}
"""Map harness :class:`FinalStatus` to :data:`TrajectoryStatus`.

``BUDGET_EXHAUSTED`` is treated as ``completed`` because the harness
ran the configured budget without a runtime fault — the trajectory is
still scoreable, just truncated. Anything that aborted before normal
termination maps to ``failed`` so the judge can drop it.
"""


def _build_prompts(target: Target, task: JudgeTask) -> Prompts:
    """Render the planner + executor prompts for one judge task.

    Args:
        target: Storefront under test (the agent's only navigation root).
        task: Judge-diagnostic task whose ``description`` is the agent
            prompt body per spec §5.5 step 1.

    Returns:
        A frozen :class:`harness.Prompts` bundle.
    """
    planner = (
        f"Target URL: {target.base_url}\n"
        f"Task ({task.id}): {task.description}\n"
        f"Surfaces to traverse: {', '.join(task.surfaces)}\n"
        f"Interactions to exercise: {', '.join(task.interactions)}\n\n"
        "Write `plan.md` with one PENDING task per discrete browsing step.\n"
        "Use snake_case task ids (e.g. `homepage`, `open_collection`,\n"
        "`apply_filter`). Do not run any actions in this iteration."
    )
    execute = (
        f"Target URL: {target.base_url}\n"
        f"Task ({task.id}): {task.description}\n\n"
        "Use Playwright tools to perform the next PENDING task in `plan.md`.\n"
        "After each tool call capture a screenshot AND an accessibility-tree\n"
        "snapshot. Mark the task `[x]` and self-check before exiting."
    )
    return Prompts(planner=planner, execute=execute)


def run_judge_agent(
    *,
    target: Target,
    task: JudgeTask,
    runtime: AgentRuntime,
    runner_version: str,
    browser_meta: BrowserMeta,
    run_dir: Path,
    output_path: Path,
    agents_md: str = DEFAULT_AGENTS_MD,
    max_iters: int = 8,
    timeout_s: float = 300.0,
) -> Trajectory:
    """Run one judge-agent invocation; persist + return the projected Trajectory.

    Wraps :func:`harness.run_plan_exec_loop` with a Playwright-driven
    ``runtime`` and projects the resulting per-iteration telemetry into
    the closed :class:`Trajectory` schema (spec §5.5 step 2).

    Args:
        target: Storefront under test. Recorded on the trajectory header.
        task: Judge-diagnostic task from ``judge/tasks/v1.yaml``.
        runtime: Caller-supplied :class:`AgentRuntime` driving Playwright
            against ``target.base_url``. Production runs use
            ``claude_code`` / ``pi`` with a Playwright tool stack.
        runner_version: ``shop_probe`` runner version embedded in the
            trajectory header for reproducibility (spec §5.8).
        browser_meta: Pinned browser/runtime metadata embedded in the
            trajectory header (spec §5.5 + §5.8).
        run_dir: Path the harness owns as its workspace. Must be empty
            or absent at call time; created by the harness.
        output_path: Where to persist the projected ``Trajectory`` JSON.
            Parent directories are created if missing.
        agents_md: AGENTS.md body installed in the harness workspace.
            Defaults to :data:`DEFAULT_AGENTS_MD`.
        max_iters: Maximum number of executor iterations (planner is
            outside this budget).
        timeout_s: Per-iteration wall-clock timeout in seconds.

    Returns:
        The projected :class:`Trajectory`. The same value is also
        persisted to ``output_path`` as indented JSON.
    """
    started_at = dt.datetime.now(dt.UTC)
    config = PlanExecLoopConfig(
        run_dir=run_dir,
        prompts=_build_prompts(target, task),
        agents_md=agents_md,
        max_iters=max_iters,
        timeout=timeout_s,
    )
    result = run_plan_exec_loop(config, runtime)
    ended_at = dt.datetime.now(dt.UTC)

    trajectory = _project_trajectory(
        target=target,
        task=task,
        runner_version=runner_version,
        browser_meta=browser_meta,
        run_dir=run_dir,
        result=result,
        started_at=started_at,
        ended_at=ended_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(trajectory.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return trajectory


def _project_trajectory(
    *,
    target: Target,
    task: JudgeTask,
    runner_version: str,
    browser_meta: BrowserMeta,
    run_dir: Path,
    result: PlanExecLoopResult,
    started_at: dt.datetime,
    ended_at: dt.datetime,
) -> Trajectory:
    """Project all harness iterations into one :class:`Trajectory`.

    Pairs each :class:`ToolCallStep` with its matching
    :class:`ToolResultStep` (matched on ``call_id``); attaches the most
    recent reasoning text (from preceding :class:`ThoughtStep` or
    assistant :class:`MessageStep` rows) and the most recent screenshot
    (from preceding :class:`ScreenshotStep` rows) seen in the same
    iteration. Unmatched calls are dropped so a half-finished iteration
    cannot leak partial steps into the judge artifact.
    """
    steps: list[TrajectoryStep] = []
    pending_call: ToolCallStep | None = None
    pending_call_iter: str | None = None
    pending_reasoning: list[str] = []
    pending_screenshot: ScreenshotStep | None = None
    step_index = 0
    error_note: str | None = None

    for relpath in result.trajectory_paths:
        traj_path = run_dir / relpath
        if not traj_path.is_file():
            continue
        htraj = HarnessTrajectory.model_validate_json(traj_path.read_text(encoding="utf-8"))
        iter_id = htraj.iter_id
        # Reset per-iteration buffers so reasoning / screenshots from a
        # prior iteration cannot bleed into this one.
        pending_call = None
        pending_call_iter = None
        pending_reasoning = []
        pending_screenshot = None
        for hstep in htraj.steps:
            if isinstance(hstep, ThoughtStep):
                pending_reasoning.append(hstep.text)
            elif isinstance(hstep, MessageStep):
                if hstep.role == "assistant":
                    pending_reasoning.append(hstep.text)
            elif isinstance(hstep, ScreenshotStep):
                pending_screenshot = hstep
            elif isinstance(hstep, ToolCallStep):
                pending_call = hstep
                pending_call_iter = iter_id
            elif isinstance(hstep, ToolResultStep):
                if (
                    pending_call is None
                    or pending_call.call_id != hstep.call_id
                    or pending_call_iter is None
                ):
                    pending_call = None
                    pending_call_iter = None
                    pending_reasoning = []
                    pending_screenshot = None
                    continue
                step = _build_step(
                    index=step_index,
                    iter_id=pending_call_iter,
                    run_dir=run_dir,
                    call=pending_call,
                    output=hstep,
                    screenshot=pending_screenshot,
                    reasoning=" ".join(t for t in pending_reasoning if t).strip(),
                )
                steps.append(step)
                step_index += 1
                pending_call = None
                pending_call_iter = None
                pending_reasoning = []
                pending_screenshot = None
            else:
                # ErrorStep — preserved as a free-form note on the trajectory.
                error_note = hstep.message

    final_status: TrajectoryStatus = _FINAL_STATUS_MAP[result.final_status]
    notes: str | None = error_note
    return Trajectory(
        target=target,
        task_id=task.id,
        runner_version=runner_version,
        runtime=browser_meta,
        started_at=started_at,
        ended_at=ended_at,
        steps=tuple(steps),
        final_status=final_status,
        anonymized=False,
        notes=notes,
    )


def _build_step(
    *,
    index: int,
    iter_id: str,
    run_dir: Path,
    call: ToolCallStep,
    output: ToolResultStep,
    screenshot: ScreenshotStep | None,
    reasoning: str,
) -> TrajectoryStep:
    """Assemble one :class:`TrajectoryStep` from a paired (call, result).

    Args:
        index: 0-indexed position within the projected trajectory.
        iter_id: Harness ``iter_id`` the (call, result) pair came from;
            used to root evidence paths so reports stay relocatable.
        run_dir: Harness workspace root; evidence ``EvidenceRef.path``
            values are written relative to this.
        call: The :class:`ToolCallStep` issued by the agent.
        output: The matching :class:`ToolResultStep`.
        screenshot: Most recent :class:`ScreenshotStep` seen before the
            ``output``; ``None`` when the runtime did not capture one,
            in which case a deterministic placeholder path is recorded.
        reasoning: Concatenated thought/assistant-message text seen
            before the call; passed through verbatim.

    Returns:
        A frozen :class:`TrajectoryStep` ready to land in the closed
        :class:`Trajectory`.
    """
    iter_dir = run_dir / "iters" / iter_id
    screenshot_rel = (
        (Path("iters") / iter_id / screenshot.path).as_posix()
        if screenshot is not None
        else (Path("iters") / iter_id / "screenshots" / f"{call.call_id}.png").as_posix()
    )
    a11y_path = iter_dir / "a11y" / f"{call.call_id}.json"
    if not a11y_path.is_file():
        # Fallback: persist the tool-result body as the a11y snapshot so
        # the closed schema's required field is always populated.
        a11y_path.parent.mkdir(parents=True, exist_ok=True)
        a11y_path.write_text(output.output, encoding="utf-8")
    a11y_rel = (Path("iters") / iter_id / "a11y" / f"{call.call_id}.json").as_posix()

    duration_ms = int(max((output.timestamp - call.timestamp).total_seconds() * 1000.0, 0.0))
    action = TrajectoryAction(
        kind=call.tool,
        selector=_string_arg(call.arguments, "selector"),
        value=_string_arg(call.arguments, "value")
        or _string_arg(call.arguments, "url")
        or _string_arg(call.arguments, "text"),
        description=_describe_call(call),
    )
    observation = TrajectoryObservation(
        url=_string_arg(call.arguments, "url"),
        title=None,
        screenshot=EvidenceRef(kind="screenshot", path=screenshot_rel),
        a11y_snapshot=EvidenceRef(kind="a11y_snapshot", path=a11y_rel),
    )
    return TrajectoryStep(
        index=index,
        action=action,
        observation=observation,
        reasoning=reasoning,
        duration_ms=duration_ms,
    )


def _string_arg(arguments: dict[str, object], key: str) -> str | None:
    """Return ``arguments[key]`` if it is a non-empty string, else ``None``."""
    value = arguments.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _describe_call(call: ToolCallStep) -> str:
    """Render a one-line human description for a tool call.

    The resulting string is non-empty (the closed schema requires it) and
    deterministic given identical input — both important for the judge
    prompt template (spec §8.3) which embeds it verbatim.
    """
    parts: list[str] = [call.tool]
    selector = _string_arg(call.arguments, "selector")
    if selector is not None:
        parts.append(f"selector={selector!r}")
    url = _string_arg(call.arguments, "url")
    if url is not None:
        parts.append(f"url={url!r}")
    value = _string_arg(call.arguments, "value") or _string_arg(call.arguments, "text")
    if value is not None:
        parts.append(f"value={value!r}")
    return " ".join(parts)
