"""Unit tests for :mod:`shop_explore.pipeline`.

Covers T2.4 of ``docs/impl/shop_explore_implementation.md``: the
:func:`shop_explore.pipeline.explore` orchestrator runs prefetch into a
seed dir and hands a fully populated :class:`harness.PlanExecLoopConfig`
to ``run_plan_exec_loop``. The harness call is monkey-patched with a
stub so the test exercises only the wiring contract — not real LLM or
runtime behavior.

Also covers T6.2: when the configured runtime satisfies
:class:`harness.LLMCompleter`, the pipeline routes the §5.10 manual-merge
LLM call through ``runtime.complete``. Stub runtimes that omit
``complete`` keep the deterministic-concatenation fallback (the existing
v0.1 behaviour).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from harness.config import FinalStatus, PlanExecLoopConfig, PlanExecLoopResult
from harness.runtimes import RuntimeIterationResult
from shop_explore import pipeline as pipeline_mod
from shop_explore.config import ExploreConfig
from shop_explore.pipeline import RUN_ID_HASH_LEN, build_runtime_llm
from shop_explore.prefetch import PrefetchResult

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
    result = pipeline_mod.explore(config)

    # Runtime selection passed the configured name through to the registry.
    assert captured["runtime_name"] == "pi"
    assert captured["runtime"] is stub_runtime

    loop_config = captured["config"]
    assert isinstance(loop_config, PlanExecLoopConfig)
    assert loop_config.run_dir == out_dir
    assert loop_config.max_iters == MAX_ITERS
    assert loop_config.timeout == TIMEOUT_SECONDS
    assert loop_config.agents_md.startswith("# AGENTS.md")
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
    pipeline_mod.explore(config)

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
    ``complete``. The stub returns a long-enough response so
    ``manual_fallback`` flips to ``False`` (a real-LLM run with the
    M2 cassette would observe the same).
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
    assert '"manual_fallback": false' in manifest_text
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


def test_build_runtime_llm_falls_back_to_noop_for_non_completer() -> None:
    """Runtimes without ``complete`` get a no-op client (forces fallback path)."""

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

    client = build_runtime_llm(_BareRuntime(), timeout=1.0)

    assert client.complete("anything") == ""


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
