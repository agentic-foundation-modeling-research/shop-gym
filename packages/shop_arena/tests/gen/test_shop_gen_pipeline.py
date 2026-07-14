"""Unit tests for :mod:`shop_arena.gen.pipeline`.

Covers the T1.6 requirements from
``docs/impl/shop_gen_implementation.md``:

* :func:`shop_arena.gen.pipeline.run` resolves ``out_dir`` defaults, drives
  the runner against the registry built for the config, and writes
  ``state.json`` only when at least one stale step ran (currently
  none — the registry is empty pending M2-M6 step registrations).
* :func:`shop_arena.gen.pipeline.status` returns ``has_run=False`` against a
  fresh workspace and projects every persisted record into a
  :class:`StepStatusEntry` once a run has touched ``state.json``.
* :func:`shop_arena.gen.pipeline.list_steps` returns one entry per declared
  phase (in :data:`PHASES` order), and asserts the DAG-shape
  invariant for both single-seed and multi-seed registrations
  (currently empty for both branches; the assertion will sharpen as
  M2-M6 wire up concrete steps).
* The single-seed-vs-multi-seed branch in registration is exercised
  via patched hooks so the architectural seam is covered before any
  concrete steps exist.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from harness.runtimes import LLMCompleter
from shop_arena.gen import pipeline
from shop_arena.gen.build import loop as build_loop
from shop_arena.gen.build.verifiers._task_routes import BucketCaps
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.pipeline import (
    PHASES,
    StatusReport,
    StepStatusEntry,
    list_steps,
    run,
    status,
)
from shop_arena.gen.steps.base import Step, StepContext, StepStatus
from shop_arena.gen.steps.runner import Registry
from shop_arena.gen.steps.state import (
    StateFile,
    StepStateRecord,
    state_path,
    write_state,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_seeds(tmp_path: Path, count: int) -> list[Path]:
    """Create ``count`` seed directories with the canonical artifact tree.

    Each seed gets an ``artifact/`` directory containing minimal
    ``capabilities.json`` / ``manual.md`` / ``stats.json`` files so the
    Phase 1 ``copy_seed_manual`` step (single-seed) and merge steps
    (multi-seed) have something to read. Tests that exercise the runner
    machinery without caring about Phase 1 contents can still rely on
    these stub artifacts because the copy step only reads bytes.
    """
    seeds: list[Path] = []
    for i in range(count):
        seed = tmp_path / f"seed_{i}"
        artifact = seed / "artifact"
        artifact.mkdir(parents=True)
        (artifact / "capabilities.json").write_text("{}", encoding="utf-8")
        # ``split_manual_parts`` (Phase 1) refuses to run against a manual
        # missing every canonical structural section, so include one.
        (artifact / "manual.md").write_text(
            f"# seed_{i}\n\n## Homepage\n\nStub homepage section.\n",
            encoding="utf-8",
        )
        (artifact / "stats.json").write_text("{}", encoding="utf-8")
        seeds.append(seed)
    return seeds


class _NoOpStep:
    """Concrete :class:`Step` that records calls without writing outputs."""

    def __init__(self, step_id: str, phase: str) -> None:
        self.id = step_id
        self.phase = phase
        self.inputs: list[object] = []
        self.outputs: list[Path] = []
        self.depends_on: list[str] = []
        self.version = 1
        self.calls = 0

    def run(self, ctx: StepContext) -> None:
        del ctx
        self.calls += 1


class _ProbeStep:
    """:class:`Step` that stashes the :class:`StepContext` it sees in a sink dict."""

    def __init__(self, sink: dict[str, object], step_id: str = "probe") -> None:
        self.id = step_id
        self.phase = "data_synth"
        self.inputs: list[object] = []
        self.outputs: list[Path] = []
        self.depends_on: list[str] = []
        self.version = 1
        self._sink = sink

    def run(self, ctx: StepContext) -> None:
        self._sink["runtime"] = ctx.runtime


# --------------------------------------------------------------------------- #
# list_steps
# --------------------------------------------------------------------------- #


def test_list_steps_returns_every_phase_in_order() -> None:
    grouped = list_steps()
    assert tuple(grouped.keys()) == PHASES


def test_list_steps_only_lists_registered_phases() -> None:
    """Every phase lists at least one registered step at v0.1."""
    grouped = list_steps()
    assert grouped["manual_merge"] == (
        "copy_seed_manual",
        "split_manual_parts",
        "merge_capabilities",
        "merge_manual_prose",
        "compute_merge_stats",
        "write_merge_manifest",
    )
    assert grouped["data_synth"] == (
        "synth_identity",
        "synth_store",
        "synth_pages",
        "synth_policies",
        "synth_collections",
        "synth_product_skeletons",
        "synth_product_details",
        "synth_alt_text",
        "gen_images",
        "synth_navigation",
        "assemble_data",
    )
    assert grouped["data_validation"] == ("validate_schema", "validate_hosting")
    assert grouped["build"] == (
        "clone_template",
        "write_env_file",
        "start_sidecar",
        "run_build_harness_loop",
    )
    assert grouped["final_eval"] == ("final_eval",)


def test_list_steps_unions_single_and_multi_seed_branches() -> None:
    """Phase 1 entries from either branch surface in the listing.

    Wired against patched hooks so this test stays sharp once concrete
    steps land in M2 — the public ``--list-steps`` table must show
    every step name a user can target, regardless of seed count.
    """

    def _multi(reg: Registry, *, config: ShopGenConfig | None = None) -> None:
        del config
        reg.register(cast(Step, _NoOpStep("merge_capabilities", "manual_merge")))

    def _single(reg: Registry, *, config: ShopGenConfig | None = None) -> None:
        del config
        reg.register(cast(Step, _NoOpStep("copy_seed_manual", "manual_merge")))

    with (
        patch.object(pipeline, "_register_manual_merge", _multi),
        patch.object(pipeline, "_register_single_seed_manual", _single),
    ):
        grouped = list_steps()

    assert set(grouped["manual_merge"]) == {"merge_capabilities", "copy_seed_manual"}


# --------------------------------------------------------------------------- #
# Registry shape (T1.6 check)
# --------------------------------------------------------------------------- #


def test_build_registry_single_seed_uses_copy_seed_branch(tmp_path: Path) -> None:
    """Single-seed runs invoke the single-seed manual hook, not the merge hook."""
    [seed] = _make_seeds(tmp_path, 1)
    config = ShopGenConfig(seeds=[seed], out_dir=tmp_path / "out")

    with (
        patch.object(pipeline, "_register_manual_merge") as merge_hook,
        patch.object(pipeline, "_register_single_seed_manual") as single_hook,
    ):
        pipeline._build_registry(config)

    merge_hook.assert_not_called()
    single_hook.assert_called_once()


def test_build_registry_multi_seed_uses_merge_branch(tmp_path: Path) -> None:
    """Multi-seed runs invoke the merge hook, not the single-seed hook."""
    seeds = _make_seeds(tmp_path, 2)
    config = ShopGenConfig(seeds=seeds, out_dir=tmp_path / "out")

    with (
        patch.object(pipeline, "_register_manual_merge") as merge_hook,
        patch.object(pipeline, "_register_single_seed_manual") as single_hook,
    ):
        pipeline._build_registry(config)

    merge_hook.assert_called_once()
    single_hook.assert_not_called()


def test_build_registry_single_seed_registers_copy_seed_manual(tmp_path: Path) -> None:
    """Single-seed branch registers ``copy_seed_manual`` (impl plan T2.6)."""
    [seed] = _make_seeds(tmp_path, 1)
    single = pipeline._build_registry(
        ShopGenConfig(seeds=[seed], out_dir=tmp_path / "a"),
    )
    assert single.ids() == [
        "copy_seed_manual",
        "split_manual_parts",
        "synth_identity",
        "synth_store",
        "synth_pages",
        "synth_policies",
        "synth_collections",
        "synth_product_skeletons",
        "synth_product_details",
        "synth_alt_text",
        "gen_images",
        "synth_navigation",
        "assemble_data",
        "validate_schema",
        "validate_hosting",
        "clone_template",
        "write_env_file",
        "start_sidecar",
        "run_build_harness_loop",
        "final_eval",
    ]


def test_build_registry_multi_seed_registers_manual_merge_steps(tmp_path: Path) -> None:
    """Multi-seed branch registers all four Phase 1 manual-merge steps."""
    multi_seeds = _make_seeds(tmp_path, 2)
    multi = pipeline._build_registry(
        ShopGenConfig(seeds=multi_seeds, out_dir=tmp_path / "b"),
    )
    assert multi.ids() == [
        "merge_capabilities",
        "merge_manual_prose",
        "split_manual_parts",
        "compute_merge_stats",
        "write_merge_manifest",
        "synth_identity",
        "synth_store",
        "synth_pages",
        "synth_policies",
        "synth_collections",
        "synth_product_skeletons",
        "synth_product_details",
        "synth_alt_text",
        "gen_images",
        "synth_navigation",
        "assemble_data",
        "validate_schema",
        "validate_hosting",
        "clone_template",
        "write_env_file",
        "start_sidecar",
        "run_build_harness_loop",
        "final_eval",
    ]


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


def test_run_creates_out_dir_and_returns_artifact_paths(tmp_path: Path) -> None:
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)

    # ``synth_identity`` (T3.3) requires an LLM completer; this test
    # asserts only the result-path shape, so patch out Phase 2 here.
    with (
        patch.object(pipeline, "_register_data_synth", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        result = run(config)

    assert out_dir.is_dir()
    assert result.out_dir == out_dir
    assert result.manual_dir == out_dir / "manual"
    assert result.identity_path == out_dir / "identity.json"
    assert result.data_dir == out_dir / "data"
    assert result.hydrogen_dir == out_dir / "hydrogen"
    assert result.data_validation_path == out_dir / "data_validation.json"
    assert result.final_eval_path == out_dir / "final_eval.json"
    assert result.build_run_dir == out_dir / "runs" / "build"


def test_run_with_no_registered_steps_writes_no_state(tmp_path: Path) -> None:
    """An empty registry resolves to zero stale steps; ``state.json`` is untouched."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    # Patch out every registration hook so the registry is genuinely
    # empty (this test asserts runner behaviour, not phase contents).
    with (
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_synth", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(ShopGenConfig(seeds=[seed], out_dir=out_dir))
    assert not state_path(out_dir).exists()


def test_run_drives_registered_step_to_completion(tmp_path: Path) -> None:
    """A patched registry runs through to ``StepStatus.FRESH``."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    step = _NoOpStep("smoke", "data_synth")

    def _register(reg: Registry, **_: object) -> None:
        reg.register(cast(Step, step))

    with (
        patch.object(pipeline, "_register_data_synth", _register),
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(config)

    assert step.calls == 1
    report = status(out_dir)
    assert report.has_run is True
    assert len(report.steps) == 1
    [entry] = report.steps
    assert entry.id == "smoke"
    assert entry.phase == "data_synth"
    assert entry.status is StepStatus.FRESH


def test_run_default_out_dir_for_single_seed(tmp_path: Path) -> None:
    """Single-seed: defaults to ``outputs/shops/<seed-name>/`` under cwd."""
    [seed] = _make_seeds(tmp_path, 1)
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    # ``synth_identity`` (T3.3) requires an LLM completer; this test
    # asserts only the resolved out-dir, so patch out Phase 2 here.
    with (
        _chdir(cwd),
        patch.object(pipeline, "_register_data_synth", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        result = run(ShopGenConfig(seeds=[seed]))

    assert result.out_dir == Path("outputs") / "shops" / seed.name
    assert (cwd / result.out_dir).is_dir()


def test_run_rejects_multi_seed_default_without_name(tmp_path: Path) -> None:
    """Multi-seed: defaulting requires explicit ``name`` (identity is M3)."""
    seeds = _make_seeds(tmp_path, 2)
    with pytest.raises(ValueError, match="multi-seed"):
        run(ShopGenConfig(seeds=seeds))


def test_run_uses_explicit_name_for_default_out_dir(tmp_path: Path) -> None:
    """``name`` overrides the slug derivation when ``out_dir`` is unset."""
    seeds = _make_seeds(tmp_path, 2)
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    # The merge_capabilities step (T2.1) reads each seed's
    # capabilities.json and ``synth_identity`` (T3.3) needs an LLM;
    # this test only exercises out_dir resolution, so patch both
    # registrations to no-ops.
    with (
        _chdir(cwd),
        patch.object(pipeline, "_register_manual_merge", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_synth", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        result = run(ShopGenConfig(seeds=seeds, name="acme"))

    assert result.out_dir == Path("outputs") / "shops" / "acme"
    assert (cwd / result.out_dir).is_dir()


def test_run_is_idempotent_on_second_invocation(tmp_path: Path) -> None:
    """SC7 (modulo registered steps): a fresh re-run is a no-op."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)

    step = _NoOpStep("smoke", "data_synth")
    step.outputs = [Path("data/smoke.json")]

    def _register(reg: Registry, **_: object) -> None:
        reg.register(cast(Step, step))

    def _do_run() -> None:
        # Write the declared output so the runner sees it as FRESH on re-run.
        (out_dir / "data").mkdir(parents=True, exist_ok=True)
        (out_dir / "data" / "smoke.json").write_bytes(b"ok")

    with (
        patch.object(pipeline, "_register_data_synth", _register),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(config)
        _do_run()
        # State file now records FRESH; second invocation must skip the step.
        run(config)

    assert step.calls == 1


# --------------------------------------------------------------------------- #
# stop_at (--to STEP)
# --------------------------------------------------------------------------- #


def _register_chain(reg: Registry, steps: list[_NoOpStep]) -> None:
    for step in steps:
        reg.register(cast(Step, step))


def _make_chain(*ids: str) -> list[_NoOpStep]:
    """Build a linear chain ``id[0] <- id[1] <- ... <- id[-1]`` of no-op steps."""
    chain: list[_NoOpStep] = []
    for idx, sid in enumerate(ids):
        step = _NoOpStep(sid, "data_synth")
        if idx > 0:
            step.depends_on = [ids[idx - 1]]
        chain.append(step)
    return chain


def test_run_stop_at_only_executes_target_and_ancestors(tmp_path: Path) -> None:
    """``stop_at`` slices the registry to the upstream cone of the target."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    chain = _make_chain("alpha", "beta", "gamma", "delta")

    with (
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(
            pipeline,
            "_register_data_synth",
            lambda reg, **_: _register_chain(reg, chain),
        ),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(config, stop_at="beta")

    calls = {step.id: step.calls for step in chain}
    assert calls == {"alpha": 1, "beta": 1, "gamma": 0, "delta": 0}


def test_run_stop_at_unknown_step_raises_value_error(tmp_path: Path) -> None:
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    chain = _make_chain("alpha", "beta")

    with (
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(
            pipeline,
            "_register_data_synth",
            lambda reg, **_: _register_chain(reg, chain),
        ),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
        pytest.raises(ValueError, match="ghost"),
    ):
        run(config, stop_at="ghost")


def test_run_stop_at_rejects_force_id_outside_cone(tmp_path: Path) -> None:
    """``--from STEP`` outside the slice surfaces a clear config error."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    chain = _make_chain("alpha", "beta", "gamma")

    with (
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(
            pipeline,
            "_register_data_synth",
            lambda reg, **_: _register_chain(reg, chain),
        ),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
        pytest.raises(ValueError, match="upstream cone"),
    ):
        run(config, force_ids=frozenset({"gamma"}), stop_at="alpha")


# --------------------------------------------------------------------------- #
# runtime wiring
# --------------------------------------------------------------------------- #


class _StubCompleter:
    """Minimal :class:`LLMCompleter` stub recording the contexts it lands in."""

    def __init__(self, label: str) -> None:
        self.label = label

    def complete(self, prompt: str, *, timeout: float) -> str:
        del prompt, timeout
        return self.label


def test_run_resolves_runtime_from_config_when_omitted(tmp_path: Path) -> None:
    """Default invocation builds a runtime from ``config.runtime`` + ``config.model``."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    skill_dir = tmp_path / "node_modules" / "pi-playwright" / "skills" / "playwright-browser"
    skill_dir.mkdir(parents=True)
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=out_dir,
        runtime="pi",
        model="anthropic/claude-opus-4-7",
    )
    captured: dict[str, object] = {}

    def fake_get_runtime(name: str, **kwargs: object) -> _StubCompleter:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return _StubCompleter("resolved")

    sink: dict[str, object] = {}

    def _register(reg: Registry, **_: object) -> None:
        reg.register(cast(Step, _ProbeStep(sink)))

    with (
        patch.object(pipeline, "get_runtime", fake_get_runtime),
        patch.object(pipeline, "resolve_playwright_skill_dir", lambda: skill_dir),
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_synth", _register),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(config)

    assert captured == {
        "name": "pi",
        "kwargs": {
            "model": "anthropic/claude-opus-4-7",
            "skill_paths": [skill_dir],
        },
    }
    assert isinstance(sink["runtime"], _StubCompleter)
    assert sink["runtime"].label == "resolved"


def test_run_drops_model_kwarg_when_config_model_is_none(tmp_path: Path) -> None:
    """``--model \"\"`` (config.model = None) opts out of pinning a model."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir, model=None)
    captured_kwargs: dict[str, object] = {}

    def fake_get_runtime(name: str, **kwargs: object) -> _StubCompleter:
        del name
        captured_kwargs.update(kwargs)
        return _StubCompleter("no-model")

    with (
        patch.object(pipeline, "get_runtime", fake_get_runtime),
        patch.object(pipeline, "resolve_playwright_skill_dir", lambda: None),
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_synth", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(config)

    assert captured_kwargs == {}


def test_run_drops_skill_paths_for_non_pi_runtime(tmp_path: Path) -> None:
    """Only Pi receives explicit playwright skill paths from the pipeline runtime."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=out_dir,
        runtime="claude_code",
        model="opus",
    )
    captured: dict[str, object] = {}

    def fake_get_runtime(name: str, **kwargs: object) -> _StubCompleter:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return _StubCompleter("resolved")

    with (
        patch.object(pipeline, "get_runtime", fake_get_runtime),
        patch.object(pipeline, "resolve_playwright_skill_dir", lambda: tmp_path),
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_synth", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(config)

    assert captured == {"name": "claude_code", "kwargs": {"model": "opus"}}


def test_build_loop_runtime_factory_wires_pi_playwright_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``shop-gen`` build-loop pi runtime gets the workspace playwright skill explicitly."""
    [seed] = _make_seeds(tmp_path, 1)
    skill_dir = tmp_path / "node_modules" / "pi-playwright" / "skills" / "playwright-browser"
    skill_dir.mkdir(parents=True)
    config = ShopGenConfig(
        seeds=[seed],
        runtime="pi",
        model="anthropic/claude-opus-4-7",
    )
    captured: dict[str, object] = {}

    def fake_get_runtime(name: str, **kwargs: object) -> _StubCompleter:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return _StubCompleter("build-loop")

    monkeypatch.setattr(build_loop, "resolve_playwright_skill_dir", lambda: skill_dir)
    monkeypatch.setattr(build_loop, "get_runtime", fake_get_runtime)

    runtime = build_loop._default_runtime_factory(config)  # pyright: ignore[reportPrivateUsage]

    assert isinstance(runtime, _StubCompleter)
    assert captured == {
        "name": "pi",
        "kwargs": {
            "model": "anthropic/claude-opus-4-7",
            "skill_paths": [skill_dir],
        },
    }


def test_build_loop_runtime_factory_drops_skill_paths_for_non_pi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only pi accepts explicit skill paths; claude_code runtime stays unchanged."""
    [seed] = _make_seeds(tmp_path, 1)
    config = ShopGenConfig(seeds=[seed], runtime="claude_code", model="opus")
    captured: dict[str, object] = {}

    def fake_get_runtime(name: str, **kwargs: object) -> _StubCompleter:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return _StubCompleter("build-loop")

    monkeypatch.setattr(build_loop, "resolve_playwright_skill_dir", lambda: tmp_path)
    monkeypatch.setattr(build_loop, "get_runtime", fake_get_runtime)

    build_loop._default_runtime_factory(config)  # pyright: ignore[reportPrivateUsage]

    assert captured == {"name": "claude_code", "kwargs": {"model": "opus"}}


def test_run_accepts_explicit_runtime_override(tmp_path: Path) -> None:
    """Library callers can inject a completer instead of resolving via ``get_runtime``."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    explicit = _StubCompleter("explicit")

    def boom_get_runtime(*_a: object, **_kw: object) -> object:
        raise AssertionError("get_runtime must not be called when override supplied")

    sink: dict[str, object] = {}

    def _register(reg: Registry, **_: object) -> None:
        reg.register(cast(Step, _ProbeStep(sink)))

    with (
        patch.object(pipeline, "get_runtime", boom_get_runtime),
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_synth", _register),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(config, runtime=cast("LLMCompleter", explicit))

    assert sink["runtime"] is explicit


# --------------------------------------------------------------------------- #
# progress logging
# --------------------------------------------------------------------------- #


def test_run_logs_start_and_end_summary(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """:func:`pipeline.run` brackets the runner with INFO ``start``/``end`` lines."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir, runtime="pi", model="opus")

    sink: dict[str, object] = {}

    def _register(reg: Registry, **_: object) -> None:
        reg.register(cast(Step, _ProbeStep(sink)))

    with (
        caplog.at_level(logging.INFO, logger="shop_arena.gen.pipeline"),
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_synth", _register),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(config, runtime=cast("LLMCompleter", _StubCompleter("x")))

    messages = [r.message for r in caplog.records if r.name == "shop_arena.gen.pipeline"]
    assert any(m.startswith("start run \u2014 out_dir=") for m in messages)
    assert any("runtime=pi" in m and "model=opus" in m for m in messages)
    end_lines = [m for m in messages if m.startswith("end run")]
    assert end_lines and "ran=1" in end_lines[0] and "skipped=0" in end_lines[0]


def test_run_includes_stop_at_in_start_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``--to STEP`` surfaces in the start log so users see the slice in effect."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    sink: dict[str, object] = {}

    def _register(reg: Registry, **_: object) -> None:
        reg.register(cast(Step, _ProbeStep(sink, step_id="probe")))

    with (
        caplog.at_level(logging.INFO, logger="shop_arena.gen.pipeline"),
        patch.object(pipeline, "_register_single_seed_manual", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_synth", _register),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg, **_: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        run(
            config,
            stop_at="probe",
            runtime=cast("LLMCompleter", _StubCompleter("x")),
        )

    start_lines = [r.message for r in caplog.records if r.message.startswith("start run")]
    assert start_lines and "stop_at=probe" in start_lines[0]


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


def test_status_reports_no_run_for_fresh_workspace(tmp_path: Path) -> None:
    out_dir = tmp_path / "shop"
    out_dir.mkdir()
    report = status(out_dir)
    assert report == StatusReport(out_dir=out_dir, has_run=False, steps=())


def test_status_reports_no_run_for_missing_workspace(tmp_path: Path) -> None:
    """``status`` is read-only and tolerates a missing workspace."""
    report = status(tmp_path / "missing")
    assert report.has_run is False
    assert report.steps == ()


def test_status_projects_every_persisted_record(tmp_path: Path) -> None:
    out_dir = tmp_path / "shop"
    out_dir.mkdir()
    state = StateFile(
        steps={
            "a": StepStateRecord(
                id="a",
                phase="data_synth",
                status=StepStatus.FRESH,
                fingerprint="abc",
                ts="2025-01-01T00:00:00Z",
            ),
            "b": StepStateRecord(
                id="b",
                phase="build",
                status=StepStatus.FAILED,
                fingerprint=None,
                ts="2025-01-02T00:00:00Z",
            ),
        },
    )
    write_state(out_dir, state)

    report = status(out_dir)

    assert report.has_run is True
    assert report.steps == (
        StepStatusEntry(
            id="a",
            phase="data_synth",
            status=StepStatus.FRESH,
            fingerprint="abc",
            ts="2025-01-01T00:00:00Z",
        ),
        StepStatusEntry(
            id="b",
            phase="build",
            status=StepStatus.FAILED,
            fingerprint=None,
            ts="2025-01-02T00:00:00Z",
        ),
    )


# --------------------------------------------------------------------------- #
# _register_final_eval — config threading (impl plan T5.4)
# --------------------------------------------------------------------------- #


_T54_MAX_COLLECTIONS = 2
_T54_PRODUCTS_PER_COLLECTION = 3
_T54_MAX_PAGES = 4
_T54_VISUAL_TIMEOUT_S = 42.0
_T54_MAX_CONCURRENCY = 5
_T54_PASS_THRESHOLD = 6.5


def test_register_final_eval_threads_config_caps_into_step(tmp_path: Path) -> None:
    """Impl plan T5.4: ``ShopGenConfig.final_eval_*`` flow into ``FinalEvalStep``."""
    [seed] = _make_seeds(tmp_path, 1)
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=tmp_path / "shop",
        final_eval_max_collections=_T54_MAX_COLLECTIONS,
        final_eval_products_per_collection=_T54_PRODUCTS_PER_COLLECTION,
        final_eval_max_pages=_T54_MAX_PAGES,
        final_eval_visual_timeout_s=_T54_VISUAL_TIMEOUT_S,
        # The sweep reads ``final_eval_visual_max_concurrency``, not the
        # in-loop ``visual_judge_max_concurrency``; set them apart so the
        # assertion below proves the step picked up the decoupled knob.
        visual_judge_max_concurrency=_T54_MAX_CONCURRENCY + 1,
        final_eval_visual_max_concurrency=_T54_MAX_CONCURRENCY,
        visual_judge_pass_threshold=_T54_PASS_THRESHOLD,
    )
    registry = Registry()

    pipeline._register_final_eval(registry, config=config)

    step = registry.get("final_eval")
    assert step is not None
    expected_caps = BucketCaps(
        max_collections=_T54_MAX_COLLECTIONS,
        products_per_collection=_T54_PRODUCTS_PER_COLLECTION,
        max_pages=_T54_MAX_PAGES,
    )
    assert step._visual_caps == expected_caps  # type: ignore[attr-defined]
    assert step._visual_timeout_s == _T54_VISUAL_TIMEOUT_S  # type: ignore[attr-defined]
    assert step._visual_max_concurrency == _T54_MAX_CONCURRENCY  # type: ignore[attr-defined]
    assert step._visual_pass_threshold == _T54_PASS_THRESHOLD  # type: ignore[attr-defined]

# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


@contextmanager
def _chdir(target: Path) -> Iterator[None]:
    """Tiny ``os.chdir`` context manager local to this test module."""

    prev = Path.cwd()
    os.chdir(target)
    try:
        yield
    finally:
        os.chdir(prev)
