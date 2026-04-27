"""Unit tests for :mod:`shop_explore.pipeline`.

Covers T2.4 of ``docs/impl/shop_explore_implementation.md``: the
:func:`shop_explore.pipeline.explore` orchestrator runs prefetch into a
seed dir and hands a fully populated :class:`harness.PlanExecLoopConfig`
to ``run_plan_exec_loop``. The harness call is monkey-patched with a
stub so the test exercises only the wiring contract — not real LLM or
runtime behavior.

Also covers T6.2: when the configured runtime satisfies
:class:`harness.LLMCompleter`, the pipeline routes the §5.10 manual-merge
LLM call through ``runtime.complete``. Tests that drive non-completer
stub runtimes inject an explicit ``llm=`` argument to :func:`explore`
because :func:`shop_explore.pipeline.build_runtime_llm` now raises
:class:`SynthesisError` rather than falling back silently to a no-op
client (M3 — the silent fallback masked LLM-client misconfiguration).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from harness.config import FinalStatus, PlanExecLoopConfig, PlanExecLoopResult
from harness.runtimes import RuntimeIterationResult
from shop_explore import pipeline as pipeline_mod
from shop_explore.config import ExploreConfig
from shop_explore.pipeline import (
    RUN_ID_HASH_LEN,
    _derive_playwright_session,
    _render_agents_md,
    _resolve_playwright_skill_dir,
    build_runtime_llm,
)
from shop_explore.prefetch import PrefetchResult
from shop_explore.synthesize import SynthesisError


@pytest.fixture(autouse=True)
def _stub_playwright_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real ``pw.js open / close`` for every test in this module.

    The pipeline pre-opens a browser session before invoking the harness
    loop (cuts cold-start for executor iterations); these unit tests only
    exercise wiring shape and don't need a live browser. Replacing the
    helpers with no-ops keeps the test hermetic and ~7x faster locally.
    """

    def _noop(skill_dir: Path | None, *, session: str) -> None:
        return None

    monkeypatch.setattr(pipeline_mod, "_preopen_browser", _noop)
    monkeypatch.setattr(pipeline_mod, "_close_browser", _noop)


BASE_URL = "https://example-shop.com"
MAX_ITERS = 4
TIMEOUT_SECONDS = 12.0
RUN_ID_TIMESTAMP_LEN = 16  # len("YYYYMMDDTHHMMSSZ")


def _ok(content: str | bytes, *, content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    body = content.encode("utf-8") if isinstance(content, str) else content
    return httpx.Response(200, content=body, headers={"content-type": content_type})


def _stub_storefront(mock: respx.MockRouter) -> None:
    """Stub every URL the prefetch plan hits with a 200 response."""
    mock.get(f"{BASE_URL}/robots.txt").mock(
        return_value=_ok("User-agent: *\nAllow: /\n", content_type="text/plain")
    )
    mock.get(f"{BASE_URL}/").mock(return_value=_ok("<!doctype html><html></html>"))
    mock.get(f"{BASE_URL}/sitemap.xml").mock(
        return_value=_ok("<?xml version='1.0'?><urlset></urlset>", content_type="application/xml")
    )
    mock.get(f"{BASE_URL}/products.json", params={"page": "1", "limit": "250"}).mock(
        return_value=_ok('{"products": []}', content_type="application/json")
    )
    mock.get(f"{BASE_URL}/collections.json", params={"limit": "50"}).mock(
        return_value=_ok('{"collections": []}', content_type="application/json")
    )
    mock.get(
        f"{BASE_URL}/search/suggest.json",
        params={"q": "a", "resources[type]": "product"},
    ).mock(return_value=_ok('{"resources": {}}', content_type="application/json"))
    mock.get(f"{BASE_URL}/cart.js").mock(
        return_value=_ok('{"items": []}', content_type="application/json")
    )
    mock.get(f"{BASE_URL}/cart").mock(return_value=_ok("<html>cart</html>"))
    mock.get(f"{BASE_URL}/search").mock(return_value=_ok("<html>search</html>"))
    for slug in ("refund-policy", "privacy-policy", "terms-of-service", "shipping-policy"):
        mock.get(f"{BASE_URL}/policies/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))
    for slug in ("about", "contact", "faq"):
        mock.get(f"{BASE_URL}/pages/{slug}").mock(return_value=_ok(f"<html>{slug}</html>"))


class _StubRuntime:
    """Sentinel runtime instance; never invoked by the test."""


_STUB_MANUAL_BODY = (
    "# Shop Manual\n\n## Overview\n\n"
    + ("Stub manual body produced by the pipeline test. " * 8)
    + "\n"
)


class _StubLLM:
    """Synthesis ``LLMClient`` stub for tests that drive non-completer runtimes.

    Injected via :func:`shop_explore.pipeline.explore`'s ``llm=`` keyword
    so the §5.10 manual-merge call doesn't trip the
    :class:`harness.runtimes.LLMCompleter` guard in
    :func:`shop_explore.pipeline.build_runtime_llm`.
    """

    def __init__(self, response: str = _STUB_MANUAL_BODY) -> None:
        self._response = response
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


@respx.mock
def test_explore_passes_seeded_config_to_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_storefront(respx.mock)

    captured: dict[str, Any] = {}
    stub_runtime = _StubRuntime()

    def fake_get_runtime(name: str) -> Any:
        captured["runtime_name"] = name
        return stub_runtime

    def fake_run_plan_exec_loop(
        loop_config: PlanExecLoopConfig, runtime: Any, **_kwargs: Any
    ) -> PlanExecLoopResult:
        captured["config"] = loop_config
        captured["runtime"] = runtime
        # Snapshot the seed contents *before* the pipeline cleans up the temp dir.
        seed = loop_config.artifact_seed_dir
        assert seed is not None
        captured["seed_files"] = sorted(
            p.relative_to(seed).as_posix() for p in seed.rglob("*") if p.is_file()
        )
        # Materialise run_dir + the artifact tree the synthesis pass expects.
        loop_config.run_dir.mkdir(parents=True, exist_ok=True)
        _seed_artifact_for_synthesis(loop_config.run_dir)
        return PlanExecLoopResult(
            run_dir=loop_config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
            trajectory_paths=(),
            tasks_final=(),
        )

    monkeypatch.setattr(pipeline_mod, "get_runtime", fake_get_runtime)
    monkeypatch.setattr(pipeline_mod, "run_plan_exec_loop", fake_run_plan_exec_loop)

    out_dir = tmp_path / "run"
    config = ExploreConfig(
        url=BASE_URL,
        out_dir=out_dir,
        runtime="pi",
        max_iters=MAX_ITERS,
        timeout=TIMEOUT_SECONDS,
    )
    result = pipeline_mod.explore(config, llm=_StubLLM())

    # Runtime selection passed the configured name through to the registry.
    assert captured["runtime_name"] == "pi"
    assert captured["runtime"] is stub_runtime

    loop_config = captured["config"]
    assert isinstance(loop_config, PlanExecLoopConfig)
    assert loop_config.run_dir == out_dir
    assert loop_config.max_iters == MAX_ITERS
    assert loop_config.timeout == TIMEOUT_SECONDS
    assert loop_config.agents_md.startswith("# AGENTS.md")
    # Both agents.md placeholders must be substituted before the harness sees it —
    # otherwise executors waste 4-5 bash calls per iter on environment discovery.
    assert "{{PLAYWRIGHT_SKILL_DIR}}" not in loop_config.agents_md
    assert "{{CAPABILITIES_SCHEMA}}" not in loop_config.agents_md
    assert "class Capabilities(BaseModel):" in loop_config.agents_md
    assert loop_config.prompts.planner.startswith("# planner.md")
    assert loop_config.prompts.execute.startswith("# execute.md")

    # Seed dir was populated with the §5.9 prefetch layout before the harness was called.
    seed_files = captured["seed_files"]
    assert "prefetch/index.html" in seed_files
    assert "prefetch/products.json" in seed_files
    assert "prefetch/cart.js" in seed_files
    assert "prefetch/prefetch.json" in seed_files

    # Returned ExploreResult points at the §5.4 artifact contract.
    artifact = out_dir / "artifact"
    assert result.run_dir == out_dir
    assert result.manual_path == artifact / "manual.md"
    assert result.capabilities_path == artifact / "capabilities.json"
    assert result.stats_path == artifact / "stats.json"
    assert result.manifest_path == artifact / "manifest.json"
    assert result.prefetch_dir == artifact / "prefetch"
    assert result.final_status == FinalStatus.COMPLETED

    # Pipeline cleaned the temporary seed root after the harness call.
    assert loop_config.artifact_seed_dir is not None
    assert not loop_config.artifact_seed_dir.exists()


def test_explore_uses_default_run_dir_when_out_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    captured: dict[str, Any] = {}

    def fake_get_runtime(name: str) -> Any:
        return object()

    def fake_run_plan_exec_loop(
        loop_config: PlanExecLoopConfig, runtime: Any, **_kwargs: Any
    ) -> PlanExecLoopResult:
        captured["run_dir"] = loop_config.run_dir
        loop_config.run_dir.mkdir(parents=True, exist_ok=True)
        _seed_artifact_for_synthesis(loop_config.run_dir)
        return PlanExecLoopResult(
            run_dir=loop_config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    def fake_prefetch(url: str, *, dest_dir: Path, **_: Any) -> PrefetchResult:
        # Stand-in for prefetch.run: just create a non-empty dest dir.
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "prefetch.json").write_text("{}", encoding="utf-8")
        return PrefetchResult(
            base_url=url,
            user_agent="test",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:00Z",
            entries=(),
        )

    monkeypatch.setattr(pipeline_mod, "get_runtime", fake_get_runtime)
    monkeypatch.setattr(pipeline_mod, "run_plan_exec_loop", fake_run_plan_exec_loop)
    monkeypatch.setattr(pipeline_mod, "run_prefetch", fake_prefetch)

    config = ExploreConfig(url=BASE_URL, runtime="pi")
    pipeline_mod.explore(config, llm=_StubLLM())

    run_dir: Path = captured["run_dir"]
    # outputs/shop_manuals/<domain>/<run_id>
    assert run_dir.parent.parent.parent.name == "outputs"
    assert run_dir.parent.parent.name == "shop_manuals"
    assert run_dir.parent.name == "example-shop.com"

    timestamp, sep, short_hash = run_dir.name.partition("-")
    assert sep == "-"
    # YYYYMMDDTHHMMSSZ
    assert len(timestamp) == RUN_ID_TIMESTAMP_LEN and timestamp.endswith("Z")
    assert len(short_hash) == RUN_ID_HASH_LEN
    int(short_hash, 16)  # short_hash must be valid hex; raises otherwise.


@respx.mock
def test_explore_routes_synthesis_call_through_completer_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runtimes satisfying ``LLMCompleter`` receive the manual-merge prompt.

    Asserts impl plan T6.2 acceptance: the pipeline delegates the
    single §5.10 LLM call to the harness runtime when it exposes
    ``complete``. The stub returns a long-enough response so synthesis
    completes successfully; if the response were under
    :data:`shop_explore.synthesize.MANUAL_MIN_CHARS` the pipeline would
    raise :class:`SynthesisError` rather than fall back silently (M3
    behaviour).
    """
    _stub_storefront(respx.mock)

    captured: dict[str, Any] = {}
    sentinel_body = (
        "Real model output for the merged manual. " * 8
    )  # > 200 chars; clears spec §5.10 minimum length

    class _CompleterRuntime:
        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            raise AssertionError("run_iteration should not be called; harness is stubbed")

        def complete(self, prompt: str, *, timeout: float) -> str:
            captured.setdefault("calls", []).append((prompt, timeout))
            return f"# Shop Manual\n\n{sentinel_body}\n"

    runtime = _CompleterRuntime()

    def fake_get_runtime(name: str) -> Any:
        captured["runtime_name"] = name
        return runtime

    def fake_run_plan_exec_loop(
        loop_config: PlanExecLoopConfig, runtime_arg: Any, **_kwargs: Any
    ) -> PlanExecLoopResult:
        captured["runtime_passed"] = runtime_arg
        loop_config.run_dir.mkdir(parents=True, exist_ok=True)
        _seed_artifact_for_synthesis(loop_config.run_dir)
        return PlanExecLoopResult(
            run_dir=loop_config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    monkeypatch.setattr(pipeline_mod, "get_runtime", fake_get_runtime)
    monkeypatch.setattr(pipeline_mod, "run_plan_exec_loop", fake_run_plan_exec_loop)

    out_dir = tmp_path / "run"
    config = ExploreConfig(
        url=BASE_URL,
        out_dir=out_dir,
        runtime="pi",
        max_iters=MAX_ITERS,
        timeout=TIMEOUT_SECONDS,
    )
    result = pipeline_mod.explore(config)

    # The completer was the same runtime instance handed to the loop.
    assert captured["runtime_passed"] is runtime
    # Synthesis invoked it exactly once with the configured timeout.
    calls = captured["calls"]
    assert len(calls) == 1
    prompt, timeout = calls[0]
    assert "placeholder" in prompt
    assert timeout == TIMEOUT_SECONDS

    manifest_text = (out_dir / "artifact" / "manifest.json").read_text(encoding="utf-8")
    assert "manual_fallback" not in manifest_text
    manual_text = result.manual_path.read_text(encoding="utf-8")
    assert "Real model output for the merged manual." in manual_text


def test_build_runtime_llm_returns_runtime_adapter_for_completer() -> None:
    """`build_runtime_llm` wraps a completer runtime and forwards the timeout.

    The returned client must satisfy the synthesis ``LLMClient``
    Protocol (a single ``complete(prompt) -> str``), and the underlying
    runtime call must receive the captured timeout.
    """

    class _CompleterRuntime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, float]] = []

        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            raise AssertionError("run_iteration should not be called in this test")

        def complete(self, prompt: str, *, timeout: float) -> str:
            self.calls.append((prompt, timeout))
            return "ok"

    runtime = _CompleterRuntime()
    client = build_runtime_llm(runtime, timeout=7.5)

    assert client.complete("hello") == "ok"
    assert runtime.calls == [("hello", 7.5)]


def test_build_runtime_llm_raises_for_non_completer_runtime() -> None:
    """Runtimes without ``complete`` make ``build_runtime_llm`` raise ``SynthesisError``.

    Earlier revisions returned a no-op client whose ``complete`` returned
    ``""``; that path masked LLM-client misconfiguration and triggered a
    silent deterministic-concatenation fallback in synthesis. M3 dropped
    the fallback — non-completer runtimes now have to be paired with an
    explicit ``llm=`` argument to :func:`shop_explore.pipeline.explore`.
    """

    class _BareRuntime:
        def run_iteration(
            self,
            *,
            run_dir: Path,
            iter_dir: Path,
            prompt: str,
            timeout: float,
        ) -> RuntimeIterationResult:
            raise AssertionError("run_iteration should not be called in this test")

    with pytest.raises(SynthesisError, match="does not implement LLMCompleter"):
        build_runtime_llm(_BareRuntime(), timeout=1.0)


def test_render_agents_md_substitutes_both_placeholders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`_render_agents_md` swaps both placeholders for concrete values.

    Pins the skill resolver to a known path so the test is hermetic;
    the schema source is read from the actual ``capabilities/schema.py``
    module so the test fails loudly if the placeholder name drifts.
    """
    fake_skill = tmp_path / "skill"
    fake_skill.mkdir()
    monkeypatch.setattr(
        pipeline_mod,
        "_resolve_playwright_skill_dir",
        lambda: fake_skill,
    )

    template = (
        "# AGENTS.md\n\n"
        'SKILL_DIR="{{PLAYWRIGHT_SKILL_DIR}}"\n\n'
        "```python\n{{CAPABILITIES_SCHEMA}}\n```\n"
    )
    rendered = _render_agents_md(template)

    assert "{{PLAYWRIGHT_SKILL_DIR}}" not in rendered
    assert "{{CAPABILITIES_SCHEMA}}" not in rendered
    assert f'SKILL_DIR="{fake_skill}"' in rendered
    # Schema is inlined verbatim from the live source so it cannot drift.
    assert "class Capabilities(BaseModel):" in rendered
    assert 'model_config = ConfigDict(extra="forbid")' in rendered


def test_render_agents_md_falls_back_when_skill_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the skill cannot be located, the placeholder gets ``<unresolved>``.

    The renderer must not raise — environments without ``pi-playwright``
    installed (e.g. replay-only CI) still need a renderable AGENTS.md.
    The literal placeholder makes the failure obvious if the agent
    actually tries to use ``$SKILL_DIR``.
    """
    monkeypatch.setattr(pipeline_mod, "_resolve_playwright_skill_dir", lambda: None)

    template = 'SKILL_DIR="{{PLAYWRIGHT_SKILL_DIR}}"\n'
    rendered = _render_agents_md(template)

    assert rendered.startswith('SKILL_DIR="<unresolved>"')


def test_resolve_playwright_skill_dir_uses_pnpm_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The resolver shells out to ``pnpm root -g`` first and validates SKILL.md.

    Stubs :func:`subprocess.run` so the test is hermetic — no global
    package manager invocations. Builds a fake global root with a
    ``pi-playwright`` skill tree to confirm the helper joins the
    relative skill path correctly.
    """
    skill_root = tmp_path / "global"
    skill_dir = skill_root / "pi-playwright" / "skills" / "playwright-browser"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# stub", encoding="utf-8")

    calls: list[tuple[str, ...]] = []

    def fake_run(argv: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(argv))
        if argv[0] == "pnpm":
            return subprocess.CompletedProcess(argv, 0, stdout=f"{skill_root}\n", stderr="")
        raise AssertionError("npm fallback should not be reached when pnpm succeeds")

    monkeypatch.setattr(pipeline_mod.subprocess, "run", fake_run)

    resolved = _resolve_playwright_skill_dir()

    assert resolved == skill_dir
    assert calls == [("pnpm", "root", "-g")]


def test_resolve_playwright_skill_dir_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns ``None`` when both pnpm and npm are unavailable or skill is missing."""

    def fake_run(argv: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        # Both managers exit non-zero — equivalent to "skill not installed".
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="not found")

    monkeypatch.setattr(pipeline_mod.subprocess, "run", fake_run)

    assert _resolve_playwright_skill_dir() is None


def test_derive_playwright_session_is_stable_and_safe() -> None:
    """Session id is deterministic and matches `runtime.js` ``sanitizeSessionName``.

    The id is derived from ``run_dir.name`` so resume runs reattach to
    the same browser daemon. Sanitization keeps it within the
    ``[a-z0-9._-]`` charset accepted by `pi-playwright`.
    """
    run_dir = Path("/tmp/runs/example-shop.com/20260427T041144Z-f0d30a86")

    first = _derive_playwright_session(run_dir)
    second = _derive_playwright_session(run_dir)

    assert first == second
    assert first == "shop-explore-20260427t041144z-f0d30a86"
    # Mirrors the JS regex /[^a-z0-9._-]+/.
    assert all(ch.islower() or ch.isdigit() or ch in "._-" for ch in first)


def test_derive_playwright_session_falls_back_when_run_dir_unsafe() -> None:
    """Pathological run-dir names still produce a non-empty sanitized id."""
    run_dir = Path("/tmp/!!!")

    session = _derive_playwright_session(run_dir)

    # Sanitization can collapse the entire suffix; the helper falls back
    # to ``shop-explore`` so the env var is never empty.
    assert session
    assert session == "shop-explore" or session.startswith("shop-explore-")


@respx.mock
def test_explore_pins_playwright_session_env_during_harness_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`PLAYWRIGHT_CLI_SESSION` is set for harness invocations and restored after."""
    _stub_storefront(respx.mock)

    captured: dict[str, Any] = {}
    sentinel_prev = "prior-session-value"
    monkeypatch.setenv("PLAYWRIGHT_CLI_SESSION", sentinel_prev)

    def fake_get_runtime(name: str) -> Any:
        return _StubRuntime()

    def fake_run_plan_exec_loop(
        loop_config: PlanExecLoopConfig, runtime: Any, **_kwargs: Any
    ) -> PlanExecLoopResult:
        captured["session_during_loop"] = os.environ.get("PLAYWRIGHT_CLI_SESSION")
        loop_config.run_dir.mkdir(parents=True, exist_ok=True)
        _seed_artifact_for_synthesis(loop_config.run_dir)
        return PlanExecLoopResult(
            run_dir=loop_config.run_dir,
            final_status=FinalStatus.COMPLETED,
            plan_iter_count=0,
            exec_iter_count=0,
        )

    preopen_calls: list[str] = []
    close_calls: list[str] = []

    def fake_preopen(skill_dir: Path | None, *, session: str) -> None:
        preopen_calls.append(session)

    def fake_close(skill_dir: Path | None, *, session: str) -> None:
        close_calls.append(session)

    monkeypatch.setattr(pipeline_mod, "_preopen_browser", fake_preopen)
    monkeypatch.setattr(pipeline_mod, "_close_browser", fake_close)
    monkeypatch.setattr(pipeline_mod, "get_runtime", fake_get_runtime)
    monkeypatch.setattr(pipeline_mod, "run_plan_exec_loop", fake_run_plan_exec_loop)

    out_dir = tmp_path / "run"
    config = ExploreConfig(
        url=BASE_URL,
        out_dir=out_dir,
        runtime="pi",
        max_iters=MAX_ITERS,
        timeout=TIMEOUT_SECONDS,
    )
    pipeline_mod.explore(config, llm=_StubLLM())

    expected_session = _derive_playwright_session(out_dir)
    # Pre-open + close were both invoked exactly once with the run-keyed session.
    assert preopen_calls == [expected_session]
    assert close_calls == [expected_session]
    # During the harness loop, `PLAYWRIGHT_CLI_SESSION` was the run-keyed id
    # (so every `pw.js` subprocess attaches to the pre-opened daemon).
    assert captured["session_during_loop"] == expected_session
    # After explore returns, the prior env var value is restored intact.
    assert os.environ.get("PLAYWRIGHT_CLI_SESSION") == sentinel_prev


def _seed_artifact_for_synthesis(run_dir: Path) -> None:
    """Seed a minimal ``artifact/`` tree so post-loop synthesis succeeds.

    The real harness populates ``artifact/parts/`` from executor
    iterations and ``artifact/prefetch/`` from the seed dir; the stubs
    in this file short-circuit the loop, so we mirror just enough of
    that layout for :func:`shop_explore.synthesize.synthesize` to run
    without raising ``SynthesisError``. The body of the seeded part is
    intentionally trivial — these tests assert wiring shape, not
    synthesis fidelity (covered by ``test_synthesize.py``).
    """
    artifact_dir = run_dir / "artifact"
    parts_dir = artifact_dir / "parts"
    prefetch_dir = artifact_dir / "prefetch"
    parts_dir.mkdir(parents=True, exist_ok=True)
    prefetch_dir.mkdir(parents=True, exist_ok=True)
    (parts_dir / "placeholder.md").write_text("# placeholder\n\nstub.\n", encoding="utf-8")
    (parts_dir / "placeholder.caps.json").write_text("{}", encoding="utf-8")
    (prefetch_dir / "products.json").write_text('{"products": []}', encoding="utf-8")
    (prefetch_dir / "collections.json").write_text('{"collections": []}', encoding="utf-8")
    (prefetch_dir / "cart.js").write_text('{"items": []}', encoding="utf-8")
