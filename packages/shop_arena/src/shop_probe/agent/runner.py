"""Generic agent-driven probe runner (v1.3 — impl plan T2.1).

The runner is the single coroutine every ``level: agent_driven`` rubric
entry routes through. It owns the boilerplate the inline ``agent_task``
block does *not* describe:

1. Resolve the precondition URL off :class:`ProbeContext` (one of
   ``base_url``, ``sample_collection_url``, ``sample_product_url``).
2. Navigate the Playwright :class:`Page` and capture a ``before-agent``
   screenshot via :meth:`ProbeContext.screenshot`.
3. Build a harness :class:`PlanExecLoopConfig` with ``run_dir`` rooted
   under ``ctx.evidence_root/<probe_id>/harness/`` and prompts inlined
   from ``task.goal``; spawn the configured runtime
   (``claude_code`` / ``pi``); run :func:`harness.run_plan_exec_loop`.
4. Walk the persisted trajectories newest-first to find the last
   :class:`ScreenshotStep` and project it as the ``after-agent``
   :class:`EvidenceRef`. Falls back to the BEFORE shot when the agent
   emitted no screenshots.
5. Return a :class:`ProbeOutcome` whose ``evidence`` is
   ``(before_shot, after_shot, harness_run)`` and whose ``passed`` is a
   placeholder ``True`` — M3 swaps in the real
   :class:`shop_probe.agent.judge.JudgeVerdict`.

The harness loop is synchronous (``run_plan_exec_loop``); the runner
hops onto a worker thread via :func:`asyncio.to_thread` so the calling
event loop (and the live Playwright session) stay responsive.

This module performs no I/O at import time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from playwright.async_api import Page

from harness import (
    PlanExecLoopConfig,
    PlanExecLoopResult,
    Prompts,
    run_plan_exec_loop,
)
from harness.runtimes import AgentRuntime, get_runtime
from harness.trajectory import ScreenshotStep, ToolCallStep
from harness.trajectory import Trajectory as HarnessTrajectory
from shop_probe.agent.config import AgentRuntimeConfig
from shop_probe.agent.judge import JudgeVerdict, run_completion_judge
from shop_probe.probes._runner import ProbeContext, ProbeOutcome
from shop_probe.report import EvidenceRef
from shop_probe.rubric.schema import AgentTaskInline

PLANNER_TEMPLATE: Final[str] = """\
You are an autonomous shopping agent on the storefront at {url}.
Your task: {goal}

Use the playwright-browser skill to navigate and interact. Plan up to {step_budget}
steps. Persist screenshots and trajectory under the harness run_dir
(relative paths only — do NOT use ARTIFACT_DIR or /var/folders).
Stop when the task is complete.
"""
"""Planner-iteration prompt (impl plan Appendix A)."""

EXECUTOR_TEMPLATE: Final[str] = """\
Continue working toward: {goal}

Use the playwright-browser skill. Take a screenshot before exiting so the
judge can verify the after-state.
"""
"""Executor-iteration prompt (impl plan Appendix A)."""

_AGENTS_MD: Final[str] = (
    "# v1.3 agent-driven probe\n\n"
    "You drive a Shopify-shaped storefront via the playwright-browser skill.\n"
    "Save all artifacts to relative paths under the harness run_dir; never\n"
    "use ARTIFACT_DIR or /var/folders/ — the wrapper denies those paths.\n"
    "Use built-in skill commands; do not access internal Playwright objects\n"
    "via ``run-code``.\n"
)
"""AGENTS.md body installed in the harness workspace.

The body encodes the project-level ``playwright-browser`` skill conventions
captured in ``CLAUDE.md`` so every runtime sees them up front.
"""

_ARG_TRUNCATE: Final[int] = 80
"""Per-argument character cap for the judge trajectory rendering."""


def _build_runtime(cfg: AgentRuntimeConfig) -> AgentRuntime:
    """Construct the harness runtime adapter for ``cfg``.

    Args:
        cfg: Resolved per-probe runtime configuration.

    Returns:
        A live :class:`AgentRuntime` (``claude_code`` or ``pi``) ready to
        be passed into :func:`harness.run_plan_exec_loop`.
    """
    if cfg.runtime == "claude_code":
        return get_runtime("claude_code", model=cfg.model)
    return get_runtime("pi", model=cfg.model)


def _resolve_start_url(ctx: ProbeContext, attr: str) -> str | None:
    """Read the precondition URL off ``ctx``.

    Args:
        ctx: Per-probe context the dispatcher built.
        attr: One of ``"base_url"`` / ``"sample_collection_url"`` /
            ``"sample_product_url"`` (validated upstream by the
            :class:`AgentTaskInline` schema).

    Returns:
        The URL string, or ``None`` when the attribute is unset on
        ``ctx`` (the runner converts that into a ``passed=None`` outcome).
    """
    if attr == "base_url":
        return ctx.base_url
    if attr == "sample_collection_url":
        return ctx.sample_collection_url
    return ctx.sample_product_url


def _last_screenshot_path(*, run_dir: Path, result: PlanExecLoopResult) -> Path | None:
    """Walk persisted trajectories newest-first; return the last screenshot path.

    Mirrors the harness on-disk contract: every iteration's
    ``trajectory.json`` lives at ``iters/<iter_id>/trajectory.json`` and
    its :class:`ScreenshotStep.path` rows are relative to that iteration
    directory.

    Args:
        run_dir: Root of the harness workspace.
        result: Return value of :func:`harness.run_plan_exec_loop`.

    Returns:
        Absolute path to the last screenshot the agent captured, or
        ``None`` when no iteration emitted one.
    """
    for relpath in reversed(result.trajectory_paths):
        traj_path = run_dir / relpath
        if not traj_path.is_file():
            continue
        traj = HarnessTrajectory.model_validate_json(
            traj_path.read_text(encoding="utf-8"),
        )
        iter_dir = traj_path.parent
        for step in reversed(traj.steps):
            if isinstance(step, ScreenshotStep):
                absolute = iter_dir / step.path
                if absolute.is_file():
                    return absolute
    return None


def _project_trajectory(*, run_dir: Path, result: PlanExecLoopResult) -> str:
    """Render the harness trajectories under ``run_dir`` as compact judge text.

    The output is a per-iteration block listing each :class:`ToolCallStep`
    (tool name + a short argument summary) and the last navigated URL
    observed in the iteration's ``goto``-flavoured tool calls. Other step
    kinds (thoughts, messages, screenshots, errors) are intentionally
    skipped so the judge prompt stays compact: it sees what the agent
    *did*, not what it said.

    Args:
        run_dir: Root of the harness workspace.
        result: Return value of :func:`harness.run_plan_exec_loop`.

    Returns:
        Compact multi-line text rendering. Empty string when no
        trajectories were persisted (defensive — the judge prompt
        renders this inside a fenced code block either way).
    """
    blocks: list[str] = []
    for relpath in result.trajectory_paths:
        traj_path = run_dir / relpath
        if not traj_path.is_file():
            continue
        traj = HarnessTrajectory.model_validate_json(
            traj_path.read_text(encoding="utf-8"),
        )
        lines: list[str] = [f"# iter {traj.iter_id} (runtime={traj.runtime})"]
        last_url: str | None = None
        for step in traj.steps:
            if not isinstance(step, ToolCallStep):
                continue
            args_preview = _summarise_tool_args(step.arguments)
            lines.append(f"- {step.tool}({args_preview})")
            url = step.arguments.get("url")
            if isinstance(url, str) and url:
                last_url = url
        if last_url is not None:
            lines.append(f"final_url: {last_url}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _summarise_tool_args(arguments: Mapping[str, object]) -> str:
    """Render ``arguments`` as a compact ``key=value`` comma-joined string.

    Long string values are truncated to 80 characters so a single noisy
    payload (e.g. a base64 screenshot in a tool argument) cannot bloat
    the judge prompt.

    Args:
        arguments: The :attr:`ToolCallStep.arguments` mapping.

    Returns:
        Compact ``key=value, key=value`` rendering, or ``""`` when the
        mapping is empty.
    """
    parts: list[str] = []
    for key, value in arguments.items():
        text = repr(value) if not isinstance(value, str) else value
        if len(text) > _ARG_TRUNCATE:
            text = text[: _ARG_TRUNCATE - 1] + "…"
        parts.append(f"{key}={text}")
    return ", ".join(parts)


async def run_agent_task(
    page: Page,
    ctx: ProbeContext,
    task: AgentTaskInline,
) -> ProbeOutcome:
    """Run one agent-driven probe end-to-end (M2 skeleton).

    Resolves the precondition URL, captures BEFORE, drives the harness
    plan/exec loop with the inline ``goal``, and stitches AFTER off the
    last :class:`ScreenshotStep`. The verdict is a placeholder ``True``;
    M3 (impl plan T3.2) replaces it with the real
    :class:`shop_probe.agent.judge.JudgeVerdict`.

    Args:
        page: Live Playwright :class:`Page` (handed over by
            :class:`shop_probe.probes._runner.ProbeRunner`).
        ctx: Per-probe context. ``ctx.agent_config`` carries the
            CLI-resolved :class:`AgentRuntimeConfig`; falls back to
            module defaults when ``None``.
        task: Inline rubric block from a ``level: agent_driven`` entry.

    Returns:
        A :class:`ProbeOutcome`. ``passed`` is ``None`` when the
        precondition URL is unset on ``ctx`` (deterministic
        not-applicable convention); otherwise ``True`` (M2 placeholder)
        with the BEFORE / AFTER screenshots and a ``harness_run``
        evidence reference to the workspace directory.
    """
    cfg = ctx.agent_config or AgentRuntimeConfig()
    start_url = _resolve_start_url(ctx, task.precondition_url_attr)
    if start_url is None:
        return ProbeOutcome(
            passed=None,
            notes=(
                f"agent task skipped: precondition_url_attr"
                f"={task.precondition_url_attr!r} is unset on ProbeContext"
            ),
        )

    await page.goto(start_url, wait_until="domcontentloaded")
    before_shot = await ctx.screenshot("before-agent")

    step_budget = task.step_budget or cfg.step_budget
    timeout_s = task.timeout_s or cfg.timeout_s
    run_dir = ctx.evidence_root / ctx.probe_id / "harness"
    # Workspace.create requires run_dir to be empty or absent; ensure the
    # parent exists so the harness can mkdir(run_dir) cleanly itself.
    run_dir.parent.mkdir(parents=True, exist_ok=True)

    config = PlanExecLoopConfig(
        run_dir=run_dir,
        prompts=Prompts(
            planner=PLANNER_TEMPLATE.format(
                url=start_url,
                goal=task.goal,
                step_budget=step_budget,
            ),
            execute=EXECUTOR_TEMPLATE.format(goal=task.goal),
        ),
        agents_md=_AGENTS_MD,
        max_iters=step_budget,
        timeout=float(timeout_s),
    )
    runtime = _build_runtime(cfg)
    result = await asyncio.to_thread(run_plan_exec_loop, config, runtime)

    after_path = _last_screenshot_path(run_dir=run_dir, result=result)
    if after_path is not None:
        after_rel = after_path.relative_to(ctx.evidence_root)
        after_shot = EvidenceRef(kind="screenshot", path=after_rel.as_posix())
        after_absolute = after_path
    else:
        after_shot = before_shot
        after_absolute = ctx.evidence_root / before_shot.path

    harness_ref = EvidenceRef(
        kind="harness_run",
        path=run_dir.relative_to(ctx.evidence_root).as_posix(),
    )

    before_absolute = ctx.evidence_root / before_shot.path
    trajectory_text = _project_trajectory(run_dir=run_dir, result=result)
    verdict: JudgeVerdict = await run_completion_judge(
        before_absolute,
        after_absolute,
        trajectory_text,
        judge_prompt=task.judge_prompt,
        model=cfg.judge_model,
    )
    return ProbeOutcome(
        passed=verdict.passed,
        evidence=(before_shot, after_shot, harness_ref),
        notes=None if verdict.passed else verdict.reasoning,
        extra={
            "judge_cost_usd": verdict.cost_usd,
            "judge_model": verdict.model_id,
        },
    )
