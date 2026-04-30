"""Unit tests for :class:`shop_gen.build.verifiers.visual_judge.VisualJudgeVerifier`.

Covers the M1 scope from impl plan T1.4: per-task lifecycle (no
retry-budget, no fan-out). The verifier is exercised against a stub
:class:`~harness.runtimes.base.AgentRuntime` that fabricates a
``verdict.json`` body directly inside the sub-workspace, plus a stub
:class:`~shop_gen.final_eval.playwright_smoke.DevServerFactory` that
records enter / exit lifecycle counts so the spec-mandated teardown
invariant is observable from the test.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from harness.plan.tasks import TaskList
from harness.runtimes.base import RuntimeIterationResult
from harness.trajectory import Trajectory
from harness.verifiers import Verdict, VerifierContext
from harness.verifiers.dispatch import dispatch_verifiers
from shop_gen.build.verifiers.visual_judge import VisualJudgeVerifier

# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


@dataclass
class _StubDevServer:
    """Recording :class:`DevServerFactory` stub.

    Tracks enters / exits so the test can assert the lifecycle is
    balanced even when the runtime raises.
    """

    base_url: str = "http://127.0.0.1:8000"
    enters: int = 0
    exits: int = 0
    last_hydrogen_dir: Path | None = None

    def __call__(self, hydrogen_dir: Path) -> _DevServerCtx:
        return _DevServerCtx(self, hydrogen_dir)


class _DevServerCtx:
    """Context-manager wrapper that increments lifecycle counters."""

    def __init__(self, server: _StubDevServer, hydrogen_dir: Path) -> None:
        self._server = server
        self._hydrogen_dir = hydrogen_dir

    def __enter__(self) -> str:
        self._server.enters += 1
        self._server.last_hydrogen_dir = self._hydrogen_dir
        return self._server.base_url

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._server.exits += 1


@dataclass
class _RecordingRuntime:
    """Stub runtime that records call args and writes a verdict body."""

    verdict_body: str | None
    calls: list[dict[str, object]] = field(default_factory=list)

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        self.calls.append(
            {
                "run_dir": run_dir,
                "iter_dir": iter_dir,
                "prompt": prompt,
                "timeout": timeout,
            },
        )
        if self.verdict_body is not None:
            (run_dir / "verdict.json").write_text(self.verdict_body, encoding="utf-8")
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        return RuntimeIterationResult(
            trajectory=Trajectory(
                iter_id="visual-stub",
                runtime="stub",
                started_at=now,
                ended_at=now,
                exit_code=0,
                prompt_sha256="0" * 64,
            ),
        )


class _RaisingRuntime:
    """Runtime stub that raises before writing a verdict.

    Used to verify the dev-server context manager tears the server
    down even when the nested iteration explodes.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls = 0

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del run_dir, iter_dir, prompt, timeout
        self.calls += 1
        raise self._exc


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #


_MINIMAL_CAPABILITIES: dict[str, object] = {
    "home.hero": {"present": True},
    "navigation.header": {"depth": 1},
    "footer": {"present": True},
    "collection.filters": ["price"],
    "product.variant_selectors": [],
    "search.predictive_types": [],
}


def _seed_capabilities(artifact_dir: Path) -> Path:
    target = artifact_dir / "capabilities.json"
    target.write_text(json.dumps(_MINIMAL_CAPABILITIES), encoding="utf-8")
    return target


def _pass_body(*, score: float = 8.5, issues: list[dict[str, str]] | None = None) -> str:
    return json.dumps(
        {
            "verdict": "pass",
            "score": score,
            "category_scores": {"structure": 8, "components": 7, "visual_tone": 9},
            "feedback": "",
            "pages_judged": 2,
            "issues": issues or [],
        },
    )


def _fail_body(score: float = 4.0) -> str:
    return json.dumps(
        {
            "verdict": "fail",
            "score": score,
            "category_scores": {},
            "feedback": "homepage hero is missing the primary CTA",
            "pages_judged": 2,
            "issues": [],
        },
    )


def _extract_capabilities_block(prompt: str) -> str:
    """Return the JSON body inside the prompt's capabilities-slice fence."""
    marker = "## Capabilities slice (filtered for this task)"
    head, _, tail = prompt.partition(marker)
    assert head, f"capabilities header missing from prompt: {prompt!r}"
    _, _, fenced = tail.partition("```json")
    body, _, _ = fenced.partition("```")
    return body


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Fresh empty data dir; bucket-route resolution falls back gracefully."""
    target = tmp_path / "data"
    target.mkdir()
    return target


@pytest.fixture
def make_visual_ctx(
    make_ctx: Callable[..., VerifierContext],
) -> Callable[..., VerifierContext]:
    """Wrapper that pre-builds the ``iters/<iter_id>/`` directory.

    The verifier writes telemetry under ``run_dir/iters/<iter_id>/checks/...``;
    pre-creating the dir keeps the test setup explicit (the harness owns
    the dir in production).
    """

    def _factory(**kwargs: object) -> VerifierContext:
        ctx = make_ctx(**kwargs)
        (ctx.run_dir / "iters" / ctx.iter_id).mkdir(parents=True, exist_ok=True)
        return ctx

    return _factory


# --------------------------------------------------------------------------- #
# Identity / applicability
# --------------------------------------------------------------------------- #


def test_name_matches_spec(data_dir: Path) -> None:
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    assert verifier.name == "visual_judge"


def test_applies_to_default_set(data_dir: Path) -> None:
    """Default applicability set per spec §5.2."""
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    for task_id in (
        "gen_homepage",
        "gen_navigation",
        "gen_collections",
        "gen_product",
        "gen_cart_search",
        "gen_info_pages",
        "visual_fix",
    ):
        assert verifier.applies_to(task_id) is True, f"missing {task_id}"


def test_visual_fix_included_after_t5_7(data_dir: Path) -> None:
    """T5.7 wires multi-bucket fan-out, so ``visual_fix`` is in the default set."""
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    assert verifier.applies_to("visual_fix") is True


# --------------------------------------------------------------------------- #
# Run lifecycle — PASS path (SC1)
# --------------------------------------------------------------------------- #


def test_run_returns_pass_when_agent_emits_clean_verdict(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    runtime = _RecordingRuntime(verdict_body=_pass_body(score=8.5))
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.PASS
    assert result.details["task_id"] == "gen_homepage"
    assert result.details["buckets_run"] == ["homepage"]
    assert result.details["routes"] == ["/"]
    assert result.details["score"] == 8.5  # noqa: PLR2004 -- mirrors fixture
    assert result.details["category_scores"] == {
        "structure": 8,
        "components": 7,
        "visual_tone": 9,
    }
    assert result.details["pages_judged"] == 2  # noqa: PLR2004 -- mirrors fixture
    assert result.details["retry_budget_exhausted"] is False
    assert result.details["prior_fails"] == 0
    assert server.enters == 1
    assert server.exits == 1
    # The runtime received a single nested call.
    assert len(runtime.calls) == 1
    call = runtime.calls[0]
    # The prompt mentions the dev-server URL + task id + the homepage
    # capability slice. Capabilities that belong to other buckets are
    # filtered out before the prompt is rendered; we inspect the
    # JSON-encoded capabilities-slice block to assert the slice itself.
    prompt_text = call["prompt"]
    assert isinstance(prompt_text, str)
    assert "http://127.0.0.1:8000" in prompt_text
    assert "gen_homepage" in prompt_text
    capabilities_block = _extract_capabilities_block(prompt_text)
    assert "home.hero" in capabilities_block
    assert "product.variant_selectors" not in capabilities_block
    assert "search.predictive_types" not in capabilities_block


# --------------------------------------------------------------------------- #
# Run lifecycle — FAIL path (SC2)
# --------------------------------------------------------------------------- #


def test_run_returns_fail_when_agent_emits_fail(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    runtime = _RecordingRuntime(verdict_body=_fail_body())
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert "homepage hero is missing the primary CTA" in result.feedback
    assert server.exits == 1


# --------------------------------------------------------------------------- #
# Redo prefix-match coverage (SC8)
# --------------------------------------------------------------------------- #


def test_run_resolves_same_scope_for_redo_task(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """`gen_homepage_redo_3` resolves to the same routes + slice as `gen_homepage`.

    Spec §5.3 layer 1 (B1 prefix match): the trailing ``_redo_<n>`` is
    stripped before bucket lookup, so the redo flow inherits its
    parent task's scope automatically.
    """
    base_runtime = _RecordingRuntime(verdict_body=_pass_body())
    base_verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    base_ctx = make_visual_ctx(runtime=base_runtime, selected_task_id="gen_homepage")
    base_result = base_verifier.run(base_ctx)

    redo_runtime = _RecordingRuntime(verdict_body=_pass_body())
    redo_verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
        applicable_tasks={"gen_homepage_redo_3"},  # bypass the applies_to gate
    )
    redo_ctx = make_visual_ctx(
        runtime=redo_runtime,
        selected_task_id="gen_homepage_redo_3",
    )
    redo_result = redo_verifier.run(redo_ctx)

    assert base_result.details["buckets_run"] == redo_result.details["buckets_run"]
    assert base_result.details["routes"] == redo_result.details["routes"]

    base_slice = _extract_capabilities_block(str(base_runtime.calls[0]["prompt"]))
    redo_slice = _extract_capabilities_block(str(redo_runtime.calls[0]["prompt"]))
    assert base_slice == redo_slice


# --------------------------------------------------------------------------- #
# Score / severity coercion (§9.3)
# --------------------------------------------------------------------------- #


def test_run_coerces_pass_to_fail_below_threshold(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    runtime = _RecordingRuntime(verdict_body=_pass_body(score=5.5))
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
        pass_threshold=7.0,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert "5.50" in result.feedback
    assert result.details["coercion_reason"] is not None


def test_run_coerces_pass_to_fail_on_critical_issue(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    body = _pass_body(
        score=9.0,
        issues=[
            {
                "route": "/",
                "viewport": "mobile",
                "screenshot": "screenshots/home__mobile.png",
                "severity": "critical",
                "summary": "hero overflows the viewport",
                "capability": "home.hero",
            },
        ],
    )
    runtime = _RecordingRuntime(verdict_body=body)
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert result.details["coercion_reason"] == "critical-severity issue forces fail"
    assert result.details["issue_count"] == 1


def test_run_threshold_lowered_lets_marginal_pass_through(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """Impl plan T3.6: a lowered threshold survives a `score=6.0` pass.

    Demonstrates the knob is observable end-to-end: with the default
    threshold of 7.0 a `score=6.0` `pass` would coerce to FAIL
    (covered above); with `pass_threshold=5.0` the same body survives
    coercion and the verifier emits PASS.
    """
    runtime = _RecordingRuntime(verdict_body=_pass_body(score=6.0))
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
        pass_threshold=5.0,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.PASS
    assert result.details["coercion_reason"] is None
    assert result.details["score"] == 6.0  # noqa: PLR2004 -- mirrors fixture


def test_init_stores_max_concurrency() -> None:
    """Impl plan T3.6: page-bucket fan-out worker count is stored on the verifier."""
    verifier = VisualJudgeVerifier(
        data_dir=Path("/tmp"),
        dev_server_factory=_StubDevServer(),
        max_concurrency=5,
    )
    assert verifier._max_concurrency == 5  # noqa: PLR2004 -- mirrors fixture


# --------------------------------------------------------------------------- #
# Diagnostic FAIL paths
# --------------------------------------------------------------------------- #


def test_run_fails_when_verdict_json_missing(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """The agent stub never writes a verdict; verifier renders a diagnostic FAIL."""
    runtime = _RecordingRuntime(verdict_body=None)
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert "verdict.json" in result.feedback
    assert result.details["phase"] == "parse"
    assert server.exits == 1


def test_run_fails_when_verdict_json_malformed(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    runtime = _RecordingRuntime(verdict_body="{not even json")
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert result.details["phase"] == "parse"


def test_run_fails_when_capabilities_missing(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """No capabilities file under artifact_dir → diagnostic FAIL, no runtime call."""
    runtime = _RecordingRuntime(verdict_body=_pass_body())
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")
    # Intentionally do not call _seed_capabilities.

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert "capabilities.json" in result.feedback
    assert runtime.calls == []
    assert server.enters == 0  # short-circuited before booting


def test_run_returns_error_for_unknown_task(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    runtime = _RecordingRuntime(verdict_body=_pass_body())
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
        applicable_tasks={"weird_task"},  # bypass the applies_to gate
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="weird_task")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.ERROR
    assert "weird_task" in result.feedback
    assert runtime.calls == []


# --------------------------------------------------------------------------- #
# Lifecycle invariants
# --------------------------------------------------------------------------- #


def test_dev_server_torn_down_on_runtime_exception(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """The dev-server context manager exits even when the runtime raises."""
    runtime = _RaisingRuntime(RuntimeError("agent crashed"))
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    with pytest.raises(RuntimeError, match="agent crashed"):
        verifier.run(ctx)

    assert server.enters == 1
    assert server.exits == 1
    assert runtime.calls == 1



def test_run_returns_fail_on_runtime_timeout_with_partial_verdict(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """`subprocess.TimeoutExpired` after the agent wrote `verdict.json`.

    The verifier should recover the partial verdict body, surface a
    FAIL (the budget overrun is itself the failure signal), keep
    a balanced dev-server lifecycle, and embed the partial score in
    `details` so the next iteration sees actionable signal.
    """

    @dataclass
    class _TimeoutAfterVerdictRuntime:
        body: str
        calls: int = 0

        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del iter_dir, prompt
            self.calls += 1
            (run_dir / "verdict.json").write_text(self.body, encoding="utf-8")
            raise subprocess.TimeoutExpired(
                cmd=["pi", "--print", "--mode", "json"],
                timeout=timeout,
            )

    runtime = _TimeoutAfterVerdictRuntime(body=_fail_body(score=4.0))
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert result.details["phase"] == "timeout"
    assert result.details["partial_verdict"] is True
    assert result.details["score"] == 4.0  # noqa: PLR2004 -- mirrors fixture
    assert "timed out" in result.feedback
    # Dev-server lifecycle is balanced even on timeout.
    assert server.enters == 1
    assert server.exits == 1
    assert runtime.calls == 1


def test_run_returns_fail_on_runtime_timeout_with_partial_screenshots(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """Timeout with no `verdict.json` but partial screenshots on disk.

    The verifier should promote the screenshots into its tree and
    surface a FAIL whose feedback names the screenshot count, so the
    executor can browse the partial captures next iteration.
    """

    @dataclass
    class _TimeoutAfterScreenshotsRuntime:
        calls: int = 0

        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del iter_dir, prompt
            self.calls += 1
            shots = run_dir / "screenshots"
            shots.mkdir()
            (shots / "home__desktop.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (shots / "home__mobile.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            raise subprocess.TimeoutExpired(
                cmd=["pi", "--print", "--mode", "json"],
                timeout=timeout,
            )

    runtime = _TimeoutAfterScreenshotsRuntime()
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert result.details["phase"] == "timeout"
    assert result.details["partial_verdict"] is False
    assert result.details["screenshot_count"] == 2  # noqa: PLR2004 -- mirrors fixture
    assert "screenshot(s) survived" in result.feedback
    # Screenshots were promoted into the verifier tree.
    promoted = (
        ctx.run_dir / "iters" / ctx.iter_id / "checks" / "verifiers" /
        "visual_judge" / "screenshots"
    )
    assert (promoted / "home__desktop.png").is_file()
    assert (promoted / "home__mobile.png").is_file()
    assert server.enters == 1
    assert server.exits == 1


def test_run_returns_fail_on_runtime_timeout_with_no_artifacts(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """Timeout with neither verdict nor screenshots.

    The agent likely never reached a renderable page (e.g. dev server
    returning 5xx). Feedback names this explicitly and points at the
    cheap `routes_200` gate so the executor knows what to fix.
    """
    runtime = _RaisingRuntime(
        subprocess.TimeoutExpired(
            cmd=["pi", "--print", "--mode", "json"],
            timeout=300.0,
        ),
    )
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert result.details["phase"] == "timeout"
    assert result.details["partial_verdict"] is False
    assert result.details["screenshot_count"] == 0
    assert "routes_200" in result.feedback
    assert server.enters == 1
    assert server.exits == 1

def test_screenshots_promoted_into_verifier_tree(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """Agent-written screenshots end up under ``checks/verifiers/visual_judge/screenshots``."""

    @dataclass
    class _ScreenshotRuntime:
        body: str

        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del iter_dir, prompt, timeout
            (run_dir / "verdict.json").write_text(self.body, encoding="utf-8")
            shots = run_dir / "screenshots"
            shots.mkdir()
            (shots / "home__desktop.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
            return RuntimeIterationResult(
                trajectory=Trajectory(
                    iter_id="visual-stub",
                    runtime="stub",
                    started_at=now,
                    ended_at=now,
                    exit_code=0,
                    prompt_sha256="0" * 64,
                ),
            )

    runtime = _ScreenshotRuntime(body=_pass_body())
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.PASS
    promoted = (
        ctx.run_dir
        / "iters"
        / ctx.iter_id
        / "checks"
        / "verifiers"
        / "visual_judge"
        / "screenshots"
        / "home__desktop.png"
    )
    assert promoted.is_file()


# --------------------------------------------------------------------------- #
# Sub-workspace fixture parity
# --------------------------------------------------------------------------- #


def test_seed_capabilities_helper_used_consistently(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
    artifact_dir: Path,
) -> None:
    """Sanity-check the helper layout matches the verifier's expectations."""
    _seed_capabilities(artifact_dir)
    runtime = _RecordingRuntime(verdict_body=_pass_body())
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="gen_homepage")
    result = verifier.run(ctx)
    assert result.verdict is Verdict.PASS


# --------------------------------------------------------------------------- #
# Per-task retry budget (T2.2 — spec §5.4)
# --------------------------------------------------------------------------- #


def _write_visual_judge_record(
    *,
    run_dir: Path,
    iter_id: str,
    task_id: str,
    verdict: str,
) -> Path:
    """Write a dispatch-shaped ``visual_judge.json`` telemetry sibling."""
    record_dir = run_dir / "iters" / iter_id / "checks" / "verifiers"
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / "visual_judge.json"
    record_path.write_text(
        json.dumps(
            {
                "iter_id": iter_id,
                "name": "visual_judge",
                "task_id": task_id,
                "verdict": verdict,
                "started_at": "2024-01-01T00:00:00+00:00",
                "duration_ms": 1,
                "feedback": "",
                "details": {},
            },
        ),
        encoding="utf-8",
    )
    return record_path


def test_run_downgrades_to_advisory_when_retry_budget_met(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """4th call after 3 sibling FAILs returns ADVISORY without invoking the runtime."""
    del caplog  # unused; the test asserts on call counts, not log lines.
    runtime = _RecordingRuntime(verdict_body=_pass_body())
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
        retry_budget=3,
    )
    ctx = make_visual_ctx(
        runtime=runtime,
        selected_task_id="gen_homepage",
        iter_id="exec-0004",
    )
    for i in range(1, 4):
        _write_visual_judge_record(
            run_dir=ctx.run_dir,
            iter_id=f"exec-{i:04d}",
            task_id="gen_homepage",
            verdict="fail",
        )

    result = verifier.run(ctx)

    assert result.verdict is Verdict.ADVISORY
    assert result.details["retry_budget_exhausted"] is True
    assert result.details["prior_fails"] == 3  # noqa: PLR2004 -- mirrors fixture
    assert result.details["retry_budget"] == 3  # noqa: PLR2004 -- mirrors ctor arg
    assert "retry budget" in result.feedback
    assert "gen_homepage" in result.feedback
    # Spec §5.4: dev server is *not* booted and the runtime is *not* called.
    assert server.enters == 0
    assert server.exits == 0
    assert runtime.calls == []


def test_run_does_not_downgrade_below_retry_budget(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """With 2 prior FAILs and budget 3, the verifier still runs the iteration."""
    runtime = _RecordingRuntime(verdict_body=_pass_body())
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
        retry_budget=3,
    )
    ctx = make_visual_ctx(
        runtime=runtime,
        selected_task_id="gen_homepage",
        iter_id="exec-0003",
    )
    for i in range(1, 3):
        _write_visual_judge_record(
            run_dir=ctx.run_dir,
            iter_id=f"exec-{i:04d}",
            task_id="gen_homepage",
            verdict="fail",
        )

    result = verifier.run(ctx)

    assert result.verdict is Verdict.PASS
    assert result.details["retry_budget_exhausted"] is False
    assert result.details["prior_fails"] == 2  # noqa: PLR2004 -- mirrors fixture
    assert len(runtime.calls) == 1
    assert server.enters == 1


def test_run_ignores_retry_budget_when_zero(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """``retry_budget=0`` disables the budget (spec §5.4)."""
    runtime = _RecordingRuntime(verdict_body=_pass_body())
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
        retry_budget=0,
    )
    ctx = make_visual_ctx(
        runtime=runtime,
        selected_task_id="gen_homepage",
        iter_id="exec-0011",
    )
    for i in range(1, 11):
        _write_visual_judge_record(
            run_dir=ctx.run_dir,
            iter_id=f"exec-{i:04d}",
            task_id="gen_homepage",
            verdict="fail",
        )

    result = verifier.run(ctx)

    assert result.verdict is Verdict.PASS
    assert result.details["retry_budget_exhausted"] is False
    assert result.details["prior_fails"] == 10  # noqa: PLR2004 -- mirrors fixture
    assert len(runtime.calls) == 1


# --------------------------------------------------------------------------- #
# SC3 — full-dispatch retry-budget downgrade (T2.5 — spec §5.4)
# --------------------------------------------------------------------------- #


def test_sc3_dispatch_records_advisory_downgrade_after_three_fails(
    artifact_dir: Path,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    """SC3: 4th invocation against ``gen_homepage`` after 3 sibling FAILs
    is recorded as ADVISORY in the dispatch-written ``visual_judge.json``.

    The earlier ``test_run_downgrades_to_advisory_when_retry_budget_met``
    pins the verifier-level return value; this test goes through
    :func:`harness.verifiers.dispatch.dispatch_verifiers` so the
    spec's on-disk contract — ``runs/build/iters/exec-0004/checks/
    verifiers/visual_judge.json`` records the downgrade — is observable.
    """
    run_dir = artifact_dir.parent  # matches make_ctx convention
    iter_id = "exec-0004"
    iter_dir = run_dir / "iters" / iter_id
    iter_dir.mkdir(parents=True)
    # Seed 3 sibling FAIL records against ``gen_homepage``.
    for i in range(1, 4):
        _write_visual_judge_record(
            run_dir=run_dir,
            iter_id=f"exec-{i:04d}",
            task_id="gen_homepage",
            verdict="fail",
        )

    runtime = _RecordingRuntime(verdict_body=_pass_body())
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
        retry_budget=3,
    )

    outcome = dispatch_verifiers(
        verifiers=[verifier],
        iter_dir=iter_dir,
        iter_id=iter_id,
        run_dir=run_dir,
        selected_task_id="gen_homepage",
        plan=TaskList(tasks=()),
        artifact_dir=artifact_dir,
        runtime=runtime,
        feedback_max_chars=4000,
    )

    # The verifier short-circuits before booting the dev server or
    # invoking the runtime.
    assert server.enters == 0
    assert server.exits == 0
    assert runtime.calls == []

    # ADVISORY is non-blocking, so no plan rewrite is triggered.
    assert outcome.blocking is False
    assert len(outcome.runs) == 1
    assert outcome.runs[0].verdict is Verdict.ADVISORY

    # The on-disk record carries the downgrade telemetry.
    record_path = iter_dir / "checks" / "verifiers" / "visual_judge.json"
    assert record_path.is_file()
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "advisory"
    assert payload["task_id"] == "gen_homepage"
    assert payload["iter_id"] == iter_id
    assert payload["details"]["retry_budget_exhausted"] is True
    assert payload["details"]["prior_fails"] == 3  # noqa: PLR2004 -- mirrors fixture
    assert payload["details"]["retry_budget"] == 3  # noqa: PLR2004 -- mirrors ctor arg
    assert "retry budget" in payload["feedback"]
    del tmp_path  # unused; artifact_dir already lives under tmp_path


# --------------------------------------------------------------------------- #
# Default fixture seeding
# --------------------------------------------------------------------------- #
# The PASS / FAIL tests above seed capabilities through the verifier
# fixture path; this autouse fixture seeds the file when the test
# does not explicitly drop it (matching ``test_quality_judge.py``'s
# pattern of seeding helpers per-test).


@pytest.fixture(autouse=True)
def _autoseed_capabilities(
    request: pytest.FixtureRequest,
    artifact_dir: Path,
) -> Iterator[None]:
    if request.node.get_closest_marker("no_capabilities"):
        yield
        return
    skip_seed = request.node.name in {
        "test_run_fails_when_capabilities_missing",
        "test_seed_capabilities_helper_used_consistently",
    }
    if not skip_seed and not (artifact_dir / "capabilities.json").exists():
        _seed_capabilities(artifact_dir)
    yield


# --------------------------------------------------------------------------- #
# SC4 - ``visual_fix`` page-bucket fan-out (T5.7 - spec §5.2.1 step 5-6)
# --------------------------------------------------------------------------- #


@dataclass
class _PerBucketRuntime:
    """Stub runtime that writes per-bucket verdict bodies during a fan-out.

    The verifier stages each bucket under
    ``<parent_dir>/<bucket>/work/``; the runtime infers the bucket name
    from ``run_dir.parent.name`` so the test can drive different per-bucket
    outcomes through a single runtime instance.
    """

    bodies: dict[str, str]
    default_body: str | None = None
    calls: list[Path] = field(default_factory=list)

    def run_iteration(
        self,
        *,
        run_dir: Path,
        iter_dir: Path,
        prompt: str,
        timeout: float,
    ) -> RuntimeIterationResult:
        del iter_dir, timeout
        self.calls.append(run_dir)
        bucket = run_dir.parent.name
        body = self.bodies.get(bucket, self.default_body)
        if body is not None:
            (run_dir / "verdict.json").write_text(body, encoding="utf-8")
        # Sanity: the per-bucket prompt only mentions its own bucket's routes.
        del prompt
        now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
        return RuntimeIterationResult(
            trajectory=Trajectory(
                iter_id="visual-stub",
                runtime="stub",
                started_at=now,
                ended_at=now,
                exit_code=0,
                prompt_sha256="0" * 64,
            ),
        )


_VISUAL_FIX_ACTIVE_BUCKETS: tuple[str, ...] = (
    "cart_search",
    "collections",
    "homepage",
    "info_pages",
    "navigation",
)
"""Buckets that resolve to non-empty routes against an empty ``data_dir``.

The ``product`` bucket is empty without a seeded ``collections.json`` (no
product handles to draw from), so the fan-out drops it from the merge
per spec §9.5 rather than failing the whole verdict.
"""


def test_visual_fix_fanout_walks_every_active_bucket(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
    artifact_dir: Path,
) -> None:
    """SC4: ``visual_fix`` invocation fans out one ``run_iteration`` per bucket."""
    runtime = _PerBucketRuntime(
        bodies={bucket: _pass_body(score=8.0) for bucket in _VISUAL_FIX_ACTIVE_BUCKETS},
    )
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="visual_fix")

    result = verifier.run(ctx)

    # Every active bucket received exactly one runtime call; ``product``
    # was skipped (no routes against an empty data_dir).
    assert len(runtime.calls) == len(_VISUAL_FIX_ACTIVE_BUCKETS)
    called_buckets = sorted(call.parent.name for call in runtime.calls)
    assert called_buckets == sorted(_VISUAL_FIX_ACTIVE_BUCKETS)
    # Dev server boots once across the fan-out (single shared server).
    assert server.enters == 1
    assert server.exits == 1
    # Per-bucket sub-iters exist on disk so reviewers can browse evidence.
    parent_dir = ctx.run_dir / "iters" / ctx.iter_id / "checks" / "verifiers" / verifier.name
    for bucket in _VISUAL_FIX_ACTIVE_BUCKETS:
        assert (parent_dir / bucket / "work" / "verdict.json").is_file(), bucket
    # Merged verdict.json carries the rolled-up numbers (spec §9.5).
    merged_path = parent_dir / "verdict.json"
    assert merged_path.is_file()
    merged_payload = json.loads(merged_path.read_text(encoding="utf-8"))
    assert merged_payload["verdict"] == "pass"
    assert merged_payload["score"] == pytest.approx(8.0)
    # Verifier-level result mirrors the merged payload.
    assert result.verdict is Verdict.PASS
    assert sorted(result.details["buckets_run"]) == sorted(
        {"homepage", "navigation", "collections", "product", "cart_search", "info_pages"},
    )
    assert result.details["score"] == pytest.approx(8.0)
    assert result.details["coercion_reason"] is None
    per_bucket = {entry["bucket"]: entry for entry in result.details["per_bucket"]}
    assert per_bucket["product"]["verdict"] is None
    assert per_bucket["product"]["error"] == "no routes resolved for bucket"
    for bucket in _VISUAL_FIX_ACTIVE_BUCKETS:
        assert per_bucket[bucket]["verdict"] == "pass"
        assert per_bucket[bucket]["score"] == pytest.approx(8.0)
    del artifact_dir  # unused; capabilities.json already seeded by autouse fixture


def test_visual_fix_fanout_weighted_score_uses_page_weights(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """Per-bucket scores are merged by :data:`PAGE_WEIGHTS` (spec §9.5)."""
    # Differentiated scores so the weighted average is observable; every
    # per-bucket score stays at or above the default pass_threshold so
    # individual buckets do not coerce to FAIL (§9.3) before the merge.
    bodies = {
        "homepage": _pass_body(score=10.0),
        "navigation": _pass_body(score=7.0),
        "collections": _pass_body(score=8.0),
        "cart_search": _pass_body(score=9.0),
        "info_pages": _pass_body(score=7.5),
    }
    runtime = _PerBucketRuntime(bodies=bodies)
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="visual_fix")

    result = verifier.run(ctx)

    # Hand-computed weighted average over the active (usable) buckets.
    # PAGE_WEIGHTS: homepage=0.25, navigation=0.20, collections=0.20,
    # cart_search=0.08, info_pages=0.07. ``product`` drops out (no routes).
    expected_num = 0.25 * 10.0 + 0.20 * 7.0 + 0.20 * 8.0 + 0.08 * 9.0 + 0.07 * 7.5
    expected_den = 0.25 + 0.20 + 0.20 + 0.08 + 0.07
    expected_score = round(expected_num / expected_den, 2)
    assert result.details["score"] == pytest.approx(expected_score)
    assert result.verdict is Verdict.PASS


def test_visual_fix_fanout_bucket_fail_propagates_to_merged_verdict(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """SC4: a single bucket FAIL flips the merged verdict to FAIL."""
    bodies = {bucket: _pass_body(score=8.0) for bucket in _VISUAL_FIX_ACTIVE_BUCKETS}
    bodies["navigation"] = _fail_body(score=3.0)
    runtime = _PerBucketRuntime(bodies=bodies)
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="visual_fix")

    result = verifier.run(ctx)

    assert result.verdict is Verdict.FAIL
    assert "navigation" in result.feedback
    per_bucket = {entry["bucket"]: entry for entry in result.details["per_bucket"]}
    assert per_bucket["navigation"]["verdict"] == "fail"
    # Other buckets still emit pass; the per-bucket trace stays intact.
    assert per_bucket["homepage"]["verdict"] == "pass"


def test_visual_fix_fanout_runtime_error_collapses_to_fail(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """A bucket whose runtime crashes is recorded as errored, merged → FAIL."""

    @dataclass
    class _OneBucketRaises:
        bodies: dict[str, str]
        raise_on_bucket: str
        calls: list[Path] = field(default_factory=list)

        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del iter_dir, prompt, timeout
            self.calls.append(run_dir)
            bucket = run_dir.parent.name
            if bucket == self.raise_on_bucket:
                raise RuntimeError(f"bucket {bucket} exploded")
            body = self.bodies.get(bucket)
            if body is not None:
                (run_dir / "verdict.json").write_text(body, encoding="utf-8")
            now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
            return RuntimeIterationResult(
                trajectory=Trajectory(
                    iter_id="visual-stub",
                    runtime="stub",
                    started_at=now,
                    ended_at=now,
                    exit_code=0,
                    prompt_sha256="0" * 64,
                ),
            )

    bodies = {bucket: _pass_body(score=8.0) for bucket in _VISUAL_FIX_ACTIVE_BUCKETS}
    runtime = _OneBucketRaises(bodies=bodies, raise_on_bucket="homepage")
    server = _StubDevServer()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=server,
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="visual_fix")

    result = verifier.run(ctx)

    # The error is recorded; the dev-server context still tears down cleanly.
    assert server.exits == 1
    assert result.verdict is Verdict.FAIL
    per_bucket = {entry["bucket"]: entry for entry in result.details["per_bucket"]}
    assert per_bucket["homepage"]["verdict"] is None
    assert "runtime raised RuntimeError" in (per_bucket["homepage"]["error"] or "")


def test_visual_fix_fanout_per_bucket_capability_slice_isolated(
    make_visual_ctx: Callable[..., VerifierContext],
    data_dir: Path,
) -> None:
    """Each bucket's prompt only carries its own capability slice (spec §5.3.1)."""
    captured: dict[str, str] = {}

    @dataclass
    class _CapturingRuntime:
        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            del iter_dir, timeout
            bucket = run_dir.parent.name
            captured[bucket] = prompt
            (run_dir / "verdict.json").write_text(_pass_body(score=8.0), encoding="utf-8")
            now = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
            return RuntimeIterationResult(
                trajectory=Trajectory(
                    iter_id="visual-stub",
                    runtime="stub",
                    started_at=now,
                    ended_at=now,
                    exit_code=0,
                    prompt_sha256="0" * 64,
                ),
            )

    runtime = _CapturingRuntime()
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    ctx = make_visual_ctx(runtime=runtime, selected_task_id="visual_fix")

    verifier.run(ctx)

    homepage_slice = _extract_capabilities_block(captured["homepage"])
    cart_slice = _extract_capabilities_block(captured["cart_search"])
    # Homepage prompt sees ``home.hero`` but not search keys; cart_search inverse.
    assert "home.hero" in homepage_slice
    assert "search" not in homepage_slice
    assert "home.hero" not in cart_slice
