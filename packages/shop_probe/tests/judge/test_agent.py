"""End-to-end tests for `shop_probe.judge.agent` (T4.2 — spec §5.5 step 2).

The harness lifecycle is exercised here against the localhost SandboxShop
fixture in ``tests/_sandbox.py`` with a stub :class:`AgentRuntime` that
drives a real Playwright session — same shape as the production runtime
the spec calls for but without a live LLM. The shape of the projected
:class:`Trajectory` (paired tool_call / tool_result steps + screenshots
+ a11y snapshots + reasoning) is what the blinded pairwise judge later
consumes, so this test pins it down.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from playwright.async_api import Browser, async_playwright

from harness.runtimes.base import RuntimeIterationResult
from harness.trajectory import (
    ScreenshotStep,
    ThoughtStep,
    ToolCallStep,
    ToolResultStep,
)
from harness.trajectory import (
    Trajectory as HarnessTrajectory,
)
from shop_probe.judge.agent import run_judge_agent
from shop_probe.judge.tasks import JudgeTask
from shop_probe.judge.trajectory import Trajectory
from shop_probe.report import BrowserMeta
from shop_probe.targets import Target

# Make the localhost SandboxShop fixture importable.
_TESTS_ROOT = Path(__file__).resolve().parent.parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _sandbox import SandboxShop  # noqa: E402

_TS_BASE: Final[dt.datetime] = dt.datetime(2026, 1, 15, 12, 0, 0, tzinfo=dt.UTC)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def sandbox_url() -> Iterator[str]:
    """Spin up a fresh SandboxShop server for one test."""
    with SandboxShop() as base_url:
        yield base_url


def _judge_task() -> JudgeTask:
    """A minimal JudgeTask exercising the localhost fixture."""
    return JudgeTask(
        id="navigate_collection_pdp",
        description=(
            "Open the storefront, navigate to the all-products collection, and open the sample PDP."
        ),
        surfaces=("homepage", "collection", "product"),
        interactions=("open_pdp", "scroll"),
        rationale="Localhost end-to-end fixture for the agent runner.",
    )


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.0.0 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


# --------------------------------------------------------------------------- #
# Stub Playwright-driven AgentRuntime
# --------------------------------------------------------------------------- #


class _PlaywrightStubRuntime:
    """`AgentRuntime` that drives real Playwright against ``base_url``.

    Mirrors what a production runtime would do — open a browser context,
    execute a navigation per executor iteration, capture screenshot +
    a11y snapshot, emit thought / tool_call / tool_result / screenshot
    steps — without calling out to an LLM.

    The planner iteration writes a fixed ``plan.md`` describing two
    PENDING navigation tasks; each subsequent executor iteration picks
    the next PENDING task, performs the navigation, and marks it ``[x]``.
    """

    _PLAN_MD: Final[str] = "# Plan\n\n## Tasks\n- [ ] homepage\n- [ ] open_collection\n"

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url
        # Map executor task id → relative URL to navigate to.
        self._nav: Final[dict[str, str]] = {
            "homepage": "/",
            "open_collection": "/collections/all",
        }
        self._iter_index = 0

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del run_dir, timeout
        if self._iter_index == 0:
            (iter_dir.parent.parent / "plan.md").write_text(self._PLAN_MD, encoding="utf-8")
            trajectory = HarnessTrajectory(
                iter_id=iter_dir.name,
                runtime="playwright_stub",
                started_at=_TS_BASE,
                ended_at=_TS_BASE + dt.timedelta(seconds=1),
                exit_code=0,
                prompt_sha256="0" * 64,
                steps=(),
            )
            self._iter_index += 1
            return RuntimeIterationResult(trajectory=trajectory)

        # Executor iteration: pick the selected task id from the harness
        # control header the loop prepended.
        selected = _selected_task_id(prompt)
        nav_path = self._nav[selected]
        steps = asyncio.run(
            _drive_playwright_step(
                base_url=self._base_url,
                nav_path=nav_path,
                iter_dir=iter_dir,
                call_id=f"call-{self._iter_index:04d}",
                started_at=_TS_BASE + dt.timedelta(seconds=self._iter_index * 2),
            )
        )

        # Mark the selected task done.
        plan_path = iter_dir.parent.parent / "plan.md"
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_path.write_text(
            plan_text.replace(f"- [ ] {selected}", f"- [x] {selected}"),
            encoding="utf-8",
        )

        trajectory = HarnessTrajectory(
            iter_id=iter_dir.name,
            runtime="playwright_stub",
            started_at=_TS_BASE + dt.timedelta(seconds=self._iter_index * 2),
            ended_at=_TS_BASE + dt.timedelta(seconds=self._iter_index * 2 + 1),
            exit_code=0,
            prompt_sha256="0" * 64,
            steps=steps,
        )
        self._iter_index += 1
        return RuntimeIterationResult(trajectory=trajectory)


def _selected_task_id(prompt: str) -> str:
    """Pull the selected task id out of the harness control header."""
    for line in prompt.splitlines():
        if line.startswith("selected_task_id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"prompt missing selected_task_id header: {prompt!r}")


async def _drive_playwright_step(
    *,
    base_url: str,
    nav_path: str,
    iter_dir: Path,
    call_id: str,
    started_at: dt.datetime,
) -> tuple[
    ThoughtStep | ToolCallStep | ToolResultStep | ScreenshotStep,
    ...,
]:
    """Run one Playwright navigation; return the harness trajectory steps."""
    screenshots_dir = iter_dir / "screenshots"
    a11y_dir = iter_dir / "a11y"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    a11y_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshots_dir / f"{call_id}.png"
    a11y_path = a11y_dir / f"{call_id}.json"

    target_url = f"{base_url}{nav_path}"
    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            try:
                page = await context.new_page()
                await page.goto(target_url, wait_until="domcontentloaded")
                await page.screenshot(path=str(screenshot_path))
                snapshot = await page.locator("body").aria_snapshot()
                title = await page.title()
            finally:
                await context.close()
        finally:
            await browser.close()

    a11y_path.write_text(
        json.dumps({"aria_snapshot": snapshot or ""}, indent=2),
        encoding="utf-8",
    )

    thought = ThoughtStep(
        timestamp=started_at,
        text=f"Navigate to {nav_path} to advance the plan.",
    )
    call = ToolCallStep(
        timestamp=started_at + dt.timedelta(milliseconds=10),
        call_id=call_id,
        tool="navigate",
        arguments={"url": target_url, "selector": "body"},
    )
    result = ToolResultStep(
        timestamp=started_at + dt.timedelta(milliseconds=210),
        call_id=call_id,
        output=f"navigated to {target_url}; title={title!r}",
        is_error=False,
    )
    screenshot = ScreenshotStep(
        timestamp=started_at + dt.timedelta(milliseconds=220),
        path=f"screenshots/{call_id}.png",
    )
    return (thought, call, screenshot, result)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_run_judge_agent_persists_validated_trajectory(
    tmp_path: Path,
    sandbox_url: str,
) -> None:
    """End-to-end: drive the harness loop, persist a Trajectory, and re-validate."""
    target = Target(
        label="sandbox/localhost_run1",
        base_url=sandbox_url,
        kind="sandbox",
        pair_id="pair_localhost",
    )
    task = _judge_task()
    runtime = _PlaywrightStubRuntime(base_url=sandbox_url)
    output_path = tmp_path / "trajectory.json"

    trajectory = run_judge_agent(
        target=target,
        task=task,
        runtime=runtime,
        runner_version="0.0.0",
        browser_meta=_browser_meta(),
        run_dir=tmp_path / "run",
        output_path=output_path,
        max_iters=4,
        timeout_s=30.0,
    )

    # Trajectory header — pinned by the closed schema.
    assert trajectory.target == target
    assert trajectory.task_id == task.id
    assert trajectory.runner_version == "0.0.0"
    assert trajectory.runtime.viewport == (1280, 800)
    assert trajectory.final_status == "completed"
    assert trajectory.anonymized is False

    # Two PENDING tasks, two paired (call, result) → two TrajectoryStep rows.
    expected_step_count = 2
    assert len(trajectory.steps) == expected_step_count
    homepage_step, collection_step = trajectory.steps
    assert homepage_step.index == 0
    assert collection_step.index == 1
    assert homepage_step.action.kind == "navigate"
    assert collection_step.action.kind == "navigate"
    assert homepage_step.action.value == f"{sandbox_url}/"
    assert collection_step.action.value == f"{sandbox_url}/collections/all"
    # Reasoning surfaced from the preceding ThoughtStep.
    assert "Navigate to" in homepage_step.reasoning
    # Description is non-empty (closed schema requires it).
    assert homepage_step.action.description
    # Duration is non-negative and reflects the (call, result) gap.
    assert homepage_step.duration_ms >= 0
    # Observation URL is the navigated URL (read off the call arguments).
    assert homepage_step.observation.url == f"{sandbox_url}/"
    # Screenshot evidence path is rooted under iters/exec-NNNN/screenshots/.
    assert homepage_step.observation.screenshot.path.startswith("iters/exec-0001/screenshots/")
    assert homepage_step.observation.a11y_snapshot.path.startswith("iters/exec-0001/a11y/")

    # Files referenced by EvidenceRef paths exist on disk under run_dir.
    run_dir = tmp_path / "run"
    for step in trajectory.steps:
        assert (run_dir / step.observation.screenshot.path).is_file()
        assert (run_dir / step.observation.a11y_snapshot.path).is_file()

    # Persisted JSON re-validates against the closed schema.
    assert output_path.is_file()
    re_loaded = Trajectory.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert re_loaded == trajectory


def test_run_judge_agent_writes_evidence_under_run_dir(
    tmp_path: Path,
    sandbox_url: str,
) -> None:
    """Evidence paths are relative to ``run_dir`` so reports stay relocatable."""
    target = Target(
        label="sandbox/localhost_run2",
        base_url=sandbox_url,
        kind="sandbox",
        pair_id="pair_localhost",
    )
    task = _judge_task()
    runtime = _PlaywrightStubRuntime(base_url=sandbox_url)

    trajectory = run_judge_agent(
        target=target,
        task=task,
        runtime=runtime,
        runner_version="0.0.0",
        browser_meta=_browser_meta(),
        run_dir=tmp_path / "run",
        output_path=tmp_path / "trajectory.json",
        max_iters=4,
        timeout_s=30.0,
    )

    for step in trajectory.steps:
        # Paths are POSIX-relative — no leading slash, no Windows separators.
        assert not step.observation.screenshot.path.startswith("/")
        assert "\\" not in step.observation.screenshot.path
        assert not step.observation.a11y_snapshot.path.startswith("/")
        assert "\\" not in step.observation.a11y_snapshot.path
