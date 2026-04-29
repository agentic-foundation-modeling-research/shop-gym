"""Hermetic tests for ``shop_probe.agent.runner.run_agent_task`` (T2.3).

The runner orchestrates four moving parts: a Playwright :class:`Page`,
a :class:`ProbeContext`, the :func:`harness.run_plan_exec_loop` call, and
the post-condition (M2: stub ``passed=True``; M3: vision judge). These
tests pin the M2 contract by stubbing the page + the harness loop and
asserting:

* the runner picks the *last* :class:`ScreenshotStep` across iterations
  as the AFTER shot;
* a missing ``precondition_url_attr`` short-circuits to
  ``passed=None`` with an informative note (no harness call);
* the runtime receives the planner / executor prompts derived verbatim
  from ``task.goal``.

The tests do not touch the network, the live ``claude``/``pi`` CLIs, or a
real browser.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from harness import (
    PlanExecLoopConfig,
    PlanExecLoopResult,
    Prompts,
)
from harness.config import FinalStatus
from harness.runtimes.base import AgentRuntime, RuntimeIterationResult
from harness.trajectory import (
    ScreenshotStep,
    ToolCallStep,
)
from harness.trajectory import Trajectory as HarnessTrajectory
from shop_probe.agent import runner as runner_module
from shop_probe.agent.config import AgentRuntimeConfig
from shop_probe.agent.judge import JudgeVerdict
from shop_probe.agent.runner import run_agent_task
from shop_probe.probes._runner import ProbeContext
from shop_probe.rubric.schema import AgentTaskInline

# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


class _StubPage:
    """Minimal Playwright :class:`Page` substitute for hermetic tests.

    Records every ``goto`` call and writes a small placeholder PNG when
    the runner asks for a screenshot.
    """

    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []

    async def goto(self, url: str, *, wait_until: str = "load") -> None:
        self.goto_calls.append((url, wait_until))

    async def screenshot(self, *, path: str) -> None:
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n")


def _agent_task(**overrides: Any) -> AgentTaskInline:
    base: dict[str, Any] = {
        "goal": "Apply any one filter that narrows the visible product list.",
        "judge_prompt": "Did the visible product set narrow?",
        "precondition_url_attr": "sample_collection_url",
    }
    base.update(overrides)
    return AgentTaskInline.model_validate(base)


def _make_ctx(
    *,
    tmp_path: Path,
    sample_collection_url: str | None = "http://localhost/collections/all",
    sample_product_url: str | None = None,
    probe_id: str = "collection.filters.applies_to_results",
) -> tuple[_StubPage, ProbeContext]:
    page = _StubPage()
    ctx = ProbeContext(
        page=page,  # type: ignore[arg-type]
        base_url="http://localhost",
        probe_id=probe_id,
        evidence_root=tmp_path / "evidence",
        sample_product_url=sample_product_url,
        sample_collection_url=sample_collection_url,
        agent_config=AgentRuntimeConfig(step_budget=4, timeout_s=30),
    )
    ctx.evidence_root.mkdir(parents=True, exist_ok=True)
    return page, ctx


def _ts(seconds: int) -> dt.datetime:
    return dt.datetime(2026, 1, 15, 12, 0, seconds, tzinfo=dt.UTC)


def _write_trajectory(
    *,
    iter_dir: Path,
    iter_id: str,
    screenshot_paths: tuple[str, ...],
) -> Path:
    """Persist a fake harness trajectory with one ScreenshotStep per path."""
    iter_dir.mkdir(parents=True, exist_ok=True)
    steps: list[ScreenshotStep | ToolCallStep] = []
    for offset, rel in enumerate(screenshot_paths):
        absolute = iter_dir / rel
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(b"\x89PNG\r\n\x1a\nstub")
        steps.append(
            ScreenshotStep(
                timestamp=_ts(offset + 1),
                path=rel,
            )
        )
    traj = HarnessTrajectory(
        iter_id=iter_id,
        runtime="stub",
        started_at=_ts(0),
        ended_at=_ts(len(screenshot_paths) + 1),
        exit_code=0,
        prompt_sha256="0" * 64,
        steps=tuple(steps),
    )
    traj_path = iter_dir / "trajectory.json"
    traj_path.write_text(
        json.dumps(traj.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return traj_path


def _stub_run_plan_exec_loop_factory(
    *,
    captured_prompts: list[Prompts],
    captured_runtimes: list[AgentRuntime],
    iters: tuple[tuple[str, tuple[str, ...]], ...],
) -> Any:
    """Build a drop-in replacement for :func:`harness.run_plan_exec_loop`.

    The stub captures the rendered prompts + the runtime instance the
    runner constructed, then writes a fake trajectory per ``iters`` entry
    under ``run_dir/iters/<iter_id>/`` and returns a matching
    :class:`PlanExecLoopResult`.
    """

    def _stub(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
    ) -> PlanExecLoopResult:
        captured_prompts.append(config.prompts)
        captured_runtimes.append(runtime)
        config.run_dir.mkdir(parents=True, exist_ok=True)
        rel_paths: list[str] = []
        for iter_id, screenshot_paths in iters:
            iter_dir = config.run_dir / "iters" / iter_id
            _write_trajectory(
                iter_dir=iter_dir,
                iter_id=iter_id,
                screenshot_paths=screenshot_paths,
            )
            rel_paths.append(f"iters/{iter_id}/trajectory.json")
        return PlanExecLoopResult(
            run_dir=config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=1 if rel_paths else 0,
            exec_iter_count=max(len(rel_paths) - 1, 0),
            trajectory_paths=tuple(rel_paths),
        )

    return _stub
    return _stub


def _install_judge_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    passed: bool = True,
    reasoning: str = "ok",
    cost_usd: float = 0.0123,
    model_id: str = "claude-opus-4-7",
) -> list[dict[str, Any]]:
    """Replace ``run_completion_judge`` with a stub recording its call args."""
    captured: list[dict[str, Any]] = []

    async def _stub(
        before_shot: Path,
        after_shot: Path,
        trajectory_text: str,
        judge_prompt: str,
        *,
        model: str = "claude-opus-4-7",
        client: Any | None = None,
    ) -> JudgeVerdict:
        captured.append(
            {
                "before_shot": before_shot,
                "after_shot": after_shot,
                "trajectory_text": trajectory_text,
                "judge_prompt": judge_prompt,
                "model": model,
            }
        )
        return JudgeVerdict(
            passed=passed,
            reasoning=reasoning,
            cost_usd=cost_usd,
            model_id=model_id,
        )

    monkeypatch.setattr(runner_module, "run_completion_judge", _stub)
    return captured


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_runner_picks_last_screenshot_as_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Across two iterations with screenshots, the runner picks the last one."""
    page, ctx = _make_ctx(tmp_path=tmp_path)
    captured_prompts: list[Prompts] = []
    captured_runtimes: list[AgentRuntime] = []
    monkeypatch.setattr(
        runner_module,
        "run_plan_exec_loop",
        _stub_run_plan_exec_loop_factory(
            captured_prompts=captured_prompts,
            captured_runtimes=captured_runtimes,
            iters=(
                ("plan-0000", ("screenshots/before.png",)),
                ("exec-0001", ("screenshots/middle.png",)),
                ("exec-0002", ("screenshots/final.png",)),
            ),
        ),
    )
    monkeypatch.setattr(runner_module, "_build_runtime", lambda cfg: object())
    judge_calls = _install_judge_stub(monkeypatch)

    outcome = asyncio.run(run_agent_task(page=page, ctx=ctx, task=_agent_task()))  # type: ignore[arg-type]

    assert outcome.passed is True
    assert page.goto_calls == [
        ("http://localhost/collections/all", "domcontentloaded"),
    ]
    # Three evidence rows: before, after, harness_run reference.
    expected_evidence_count = 3
    assert len(outcome.evidence) == expected_evidence_count
    before, after, harness = outcome.evidence
    assert before.kind == "screenshot"
    assert before.path.endswith("before-agent.png")
    assert after.kind == "screenshot"
    # The runner must pick the LAST iteration's screenshot, not an earlier one.
    assert after.path.endswith("exec-0002/screenshots/final.png")
    assert harness.kind == "harness_run"
    assert harness.path == f"{ctx.probe_id}/harness"
    # Judge received the AFTER screenshot the runner picked + the inline prompt.
    assert len(judge_calls) == 1
    call = judge_calls[0]
    assert call["after_shot"].as_posix().endswith("exec-0002/screenshots/final.png")
    assert call["judge_prompt"] == "Did the visible product set narrow?"
    # Cost surfaces on ProbeOutcome.extra (T3.2).
    assert outcome.extra.get("judge_cost_usd") == pytest.approx(0.0123)
    assert outcome.extra.get("judge_model") == "claude-opus-4-7"


def test_runner_skips_when_precondition_url_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing ``precondition_url_attr`` short-circuits to ``passed=None``."""
    page, ctx = _make_ctx(
        tmp_path=tmp_path,
        sample_product_url=None,
        probe_id="product.variant.swap_updates_state",
    )
    called: list[bool] = []

    def _explode(
        config: PlanExecLoopConfig,
        runtime: AgentRuntime,
    ) -> PlanExecLoopResult:
        called.append(True)
        raise AssertionError("harness must not run when precondition is unset")

    monkeypatch.setattr(runner_module, "run_plan_exec_loop", _explode)

    outcome = asyncio.run(
        run_agent_task(
            page=page,  # type: ignore[arg-type]
            ctx=ctx,
            task=_agent_task(precondition_url_attr="sample_product_url"),
        )
    )

    assert outcome.passed is None
    assert outcome.notes is not None
    assert "sample_product_url" in outcome.notes
    assert called == []
    assert page.goto_calls == []


def test_runner_renders_goal_into_prompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The harness prompts contain ``task.goal`` verbatim in both planner + executor."""
    page, ctx = _make_ctx(tmp_path=tmp_path)
    captured_prompts: list[Prompts] = []
    captured_runtimes: list[AgentRuntime] = []
    monkeypatch.setattr(
        runner_module,
        "run_plan_exec_loop",
        _stub_run_plan_exec_loop_factory(
            captured_prompts=captured_prompts,
            captured_runtimes=captured_runtimes,
            iters=(("plan-0000", ()),),
        ),
    )

    sentinel_runtime: list[AgentRuntime] = []

    class _SentinelRuntime:
        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            raise NotImplementedError

    def _factory(_cfg: AgentRuntimeConfig) -> AgentRuntime:
        instance = _SentinelRuntime()
        sentinel_runtime.append(instance)
        return instance

    monkeypatch.setattr(runner_module, "_build_runtime", _factory)
    _install_judge_stub(monkeypatch)

    goal = "Type 'red' into search and verify predictive results appear."
    asyncio.run(
        run_agent_task(
            page=page,  # type: ignore[arg-type]
            ctx=ctx,
            task=_agent_task(
                goal=goal,
                precondition_url_attr="base_url",
            ),
        )
    )

    assert len(captured_prompts) == 1
    prompts = captured_prompts[0]
    assert goal in prompts.planner
    assert goal in prompts.execute
    # Planner template embeds the precondition URL the runner navigated to.
    assert "http://localhost" in prompts.planner
    # Runtime constructed via the factory was forwarded to the harness.
    assert captured_runtimes == sentinel_runtime
