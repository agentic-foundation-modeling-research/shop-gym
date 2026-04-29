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
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from harness.runtimes.base import RuntimeIterationResult
from harness.trajectory import Trajectory
from harness.verifiers import Verdict, VerifierContext
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
    """Default applicability set per spec §5.2 (consolidate excluded in M1)."""
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
        "visual_polish",
    ):
        assert verifier.applies_to(task_id) is True, f"missing {task_id}"


def test_consolidate_excluded_in_m1(data_dir: Path) -> None:
    """``consolidate`` is added back in T5.7 alongside the fan-out."""
    verifier = VisualJudgeVerifier(
        data_dir=data_dir,
        dev_server_factory=_StubDevServer(),
    )
    assert verifier.applies_to("consolidate") is False


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
