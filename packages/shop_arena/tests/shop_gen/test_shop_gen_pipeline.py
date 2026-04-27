"""Unit tests for :mod:`shop_gen.pipeline`.

Covers the T1.6 requirements from
``docs/impl/shop_gen_implementation.md``:

* :func:`shop_gen.pipeline.run` resolves ``out_dir`` defaults, drives
  the runner against the registry built for the config, and writes
  ``state.json`` only when at least one stale step ran (currently
  none — the registry is empty pending M2-M6 step registrations).
* :func:`shop_gen.pipeline.status` returns ``has_run=False`` against a
  fresh workspace and projects every persisted record into a
  :class:`StepStatusEntry` once a run has touched ``state.json``.
* :func:`shop_gen.pipeline.list_steps` returns one entry per declared
  phase (in :data:`PHASES` order), and asserts the DAG-shape
  invariant for both single-seed and multi-seed registrations
  (currently empty for both branches; the assertion will sharpen as
  M2-M6 wire up concrete steps).
* The single-seed-vs-multi-seed branch in registration is exercised
  via patched hooks so the architectural seam is covered before any
  concrete steps exist.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from shop_gen import pipeline
from shop_gen.config import ShopGenConfig
from shop_gen.pipeline import (
    PHASES,
    StatusReport,
    StepStatusEntry,
    list_steps,
    run,
    status,
)
from shop_gen.steps.base import Step, StepContext, StepStatus
from shop_gen.steps.runner import Registry
from shop_gen.steps.state import (
    StateFile,
    StepStateRecord,
    state_path,
    write_state,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_seeds(tmp_path: Path, count: int) -> list[Path]:
    seeds: list[Path] = []
    for i in range(count):
        seed = tmp_path / f"seed_{i}"
        seed.mkdir()
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


# --------------------------------------------------------------------------- #
# list_steps
# --------------------------------------------------------------------------- #


def test_list_steps_returns_every_phase_in_order() -> None:
    grouped = list_steps()
    assert tuple(grouped.keys()) == PHASES


def test_list_steps_only_lists_registered_phases() -> None:
    """Phase 1 lists landed M2 steps; later phases stay empty until M3-M6."""
    grouped = list_steps()
    assert grouped["manual_merge"] == ("merge_capabilities",)
    for phase in ("data_synth", "data_validation", "build", "final_eval"):
        assert grouped[phase] == ()


def test_list_steps_unions_single_and_multi_seed_branches() -> None:
    """Phase 1 entries from either branch surface in the listing.

    Wired against patched hooks so this test stays sharp once concrete
    steps land in M2 — the public ``--list-steps`` table must show
    every step name a user can target, regardless of seed count.
    """

    def _multi(reg: Registry, *, config: ShopGenConfig | None = None) -> None:
        del config
        reg.register(cast(Step, _NoOpStep("merge_capabilities", "manual_merge")))

    def _single(reg: Registry) -> None:
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


def test_build_registry_single_seed_branch_remains_empty(tmp_path: Path) -> None:
    """Single-seed manual hook is still a no-op (T2.6 lands later in M2)."""
    [seed] = _make_seeds(tmp_path, 1)
    single = pipeline._build_registry(
        ShopGenConfig(seeds=[seed], out_dir=tmp_path / "a"),
    )
    assert single.ids() == []


def test_build_registry_multi_seed_registers_merge_capabilities(tmp_path: Path) -> None:
    """Multi-seed branch registers ``merge_capabilities`` (T2.1 landed)."""
    multi_seeds = _make_seeds(tmp_path, 2)
    multi = pipeline._build_registry(
        ShopGenConfig(seeds=multi_seeds, out_dir=tmp_path / "b"),
    )
    assert multi.ids() == ["merge_capabilities"]


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


def test_run_creates_out_dir_and_returns_artifact_paths(tmp_path: Path) -> None:
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)

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
    run(ShopGenConfig(seeds=[seed], out_dir=out_dir))
    assert not state_path(out_dir).exists()


def test_run_drives_registered_step_to_completion(tmp_path: Path) -> None:
    """A patched registry runs through to ``StepStatus.FRESH``."""
    [seed] = _make_seeds(tmp_path, 1)
    out_dir = tmp_path / "shop"
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    step = _NoOpStep("smoke", "data_synth")

    def _register(reg: Registry) -> None:
        reg.register(cast(Step, step))

    with patch.object(pipeline, "_register_data_synth", _register):
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

    with _chdir(cwd):
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
    # capabilities.json; this test only exercises out_dir resolution,
    # so patch the manual-merge registration to a no-op.
    with _chdir(cwd), patch.object(pipeline, "_register_manual_merge", lambda reg, **_: None):
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

    def _register(reg: Registry) -> None:
        reg.register(cast(Step, step))

    def _do_run() -> None:
        # Write the declared output so the runner sees it as FRESH on re-run.
        (out_dir / "data").mkdir(parents=True, exist_ok=True)
        (out_dir / "data" / "smoke.json").write_bytes(b"ok")

    with patch.object(pipeline, "_register_data_synth", _register):
        run(config)
        _do_run()
        # State file now records FRESH; second invocation must skip the step.
        run(config)

    assert step.calls == 1


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
