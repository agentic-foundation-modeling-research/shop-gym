"""Unit tests for :mod:`shop_gen.steps.runner`.

Covers the runner requirements from
``docs/impl/shop_gen_implementation.md`` T1.4:

* DAG resolution rejects cycles and missing dependencies; topological
  order is deterministic across registration orderings.
* Staleness detection cascades: changing an upstream input forces every
  downstream step stale.
* Output staleness: deleting a declared output marks the step stale.
* Idempotent re-run: a clean workspace skips every step on the second
  invocation.
* ``--from`` / ``--only`` plumbing: ``force_ids`` re-runs the targeted
  step and cascades downstream descendants.
* Failure path: a step exception persists ``StepStatus.FAILED`` in
  ``state.json`` and re-raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from shop_gen.config import ShopGenConfig
from shop_gen.steps.base import FileInput, InputRef, Step, StepContext, StepInput, StepStatus
from shop_gen.steps.runner import (
    CycleError,
    DuplicateStepError,
    MissingDependencyError,
    Registry,
    RunResult,
    compute_staleness,
    resolve_dag,
    run_pipeline,
)
from shop_gen.steps.state import (
    StateFile,
    StepStateRecord,
    compute_fingerprint,
    read_state,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@dataclass
class _RecordingStep:
    """Concrete step that writes its declared outputs and records calls.

    The ``payload`` is written verbatim to every output path; this makes
    fingerprint changes easy to drive in tests.
    """

    id: str
    phase: str = "data_synth"
    inputs: list[InputRef] = field(default_factory=list)
    outputs: list[Path] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    version: int = 1
    payload: bytes = b"ok"
    calls: list[str] = field(default_factory=list)
    raises: BaseException | None = None

    def run(self, ctx: StepContext) -> None:
        self.calls.append(self.id)
        if self.raises is not None:
            raise self.raises
        for out in self.outputs:
            target = out if out.is_absolute() else ctx.out_dir / out
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.payload)


def _as_step(stub: _RecordingStep) -> Step:
    return cast(Step, stub)


def _ctx(out_dir: Path, seed: Path) -> StepContext:
    out_dir.mkdir(parents=True, exist_ok=True)
    return StepContext(config=ShopGenConfig(seeds=[seed]), out_dir=out_dir)


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def test_registry_register_and_lookup() -> None:
    reg = Registry()
    a = _RecordingStep(id="a")
    reg.register(_as_step(a))
    assert "a" in reg
    assert reg.get("a") is _as_step(a)
    assert reg.ids() == ["a"]
    assert len(reg) == 1


def test_registry_rejects_duplicate_ids() -> None:
    reg = Registry()
    reg.register(_as_step(_RecordingStep(id="a")))
    with pytest.raises(DuplicateStepError):
        reg.register(_as_step(_RecordingStep(id="a")))


# --------------------------------------------------------------------------- #
# resolve_dag
# --------------------------------------------------------------------------- #


def test_resolve_dag_returns_topological_order() -> None:
    a = _RecordingStep(id="a")
    b = _RecordingStep(id="b", depends_on=["a"])
    c = _RecordingStep(id="c", depends_on=["b"])
    order = [step.id for step in resolve_dag([_as_step(c), _as_step(b), _as_step(a)])]
    assert order == ["a", "b", "c"]


def test_resolve_dag_is_deterministic_under_id_tie_break() -> None:
    """Independent leaves run in id-sorted order regardless of registration."""
    a = _RecordingStep(id="a")
    b = _RecordingStep(id="b")
    c = _RecordingStep(id="c")
    order_first = [step.id for step in resolve_dag([_as_step(c), _as_step(a), _as_step(b)])]
    order_second = [step.id for step in resolve_dag([_as_step(b), _as_step(a), _as_step(c)])]
    assert order_first == order_second == ["a", "b", "c"]


def test_resolve_dag_rejects_cycle() -> None:
    a = _RecordingStep(id="a", depends_on=["b"])
    b = _RecordingStep(id="b", depends_on=["a"])
    with pytest.raises(CycleError, match="cycle"):
        resolve_dag([_as_step(a), _as_step(b)])


def test_resolve_dag_rejects_missing_dependency() -> None:
    a = _RecordingStep(id="a", depends_on=["ghost"])
    with pytest.raises(MissingDependencyError, match="ghost"):
        resolve_dag([_as_step(a)])


def test_resolve_dag_rejects_step_input_missing_from_depends_on() -> None:
    """``StepInput`` must be declared in ``depends_on`` (spec §5.7.1)."""
    a = _RecordingStep(id="a")
    b = _RecordingStep(id="b", inputs=[StepInput(step_id="a")], depends_on=[])
    with pytest.raises(MissingDependencyError, match="depends_on"):
        resolve_dag([_as_step(a), _as_step(b)])


def test_resolve_dag_accepts_diamond() -> None:
    a = _RecordingStep(id="a")
    b = _RecordingStep(id="b", depends_on=["a"])
    c = _RecordingStep(id="c", depends_on=["a"])
    d = _RecordingStep(id="d", depends_on=["b", "c"])
    order = [step.id for step in resolve_dag([_as_step(d), _as_step(c), _as_step(b), _as_step(a)])]
    assert order[0] == "a"
    assert order[-1] == "d"
    assert set(order[1:3]) == {"b", "c"}


# --------------------------------------------------------------------------- #
# compute_staleness
# --------------------------------------------------------------------------- #


def test_compute_staleness_marks_unrecorded_steps_stale(tmp_path: Path) -> None:
    a = _RecordingStep(id="a")
    stale = compute_staleness([_as_step(a)], StateFile(), run_root=tmp_path)
    assert stale == {"a": True}


def test_compute_staleness_skips_clean_step(tmp_path: Path) -> None:
    """A step whose outputs exist and whose fingerprint matches is FRESH."""
    seed = tmp_path / "seed.json"
    seed.write_text("hello", encoding="utf-8")
    out = tmp_path / "data" / "x.json"
    out.parent.mkdir()
    out.write_bytes(b"ok")
    step = _RecordingStep(id="a", inputs=[FileInput(path=seed)], outputs=[Path("data/x.json")])

    # Pre-compute the fingerprint and persist it.
    fp = compute_fingerprint(_as_step(step), StateFile(), run_root=tmp_path)
    state = StateFile(
        steps={
            "a": StepStateRecord(
                id="a",
                phase="data_synth",
                status=StepStatus.FRESH,
                fingerprint=fp,
            ),
        },
    )
    assert compute_staleness([_as_step(step)], state, run_root=tmp_path) == {"a": False}


def test_compute_staleness_detects_missing_output(tmp_path: Path) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text("hello", encoding="utf-8")
    step = _RecordingStep(
        id="a",
        inputs=[FileInput(path=seed)],
        outputs=[Path("data/missing.json")],
    )
    state = StateFile(
        steps={
            "a": StepStateRecord(
                id="a",
                phase="data_synth",
                status=StepStatus.FRESH,
                fingerprint="deadbeef",
            ),
        },
    )
    assert compute_staleness([_as_step(step)], state, run_root=tmp_path) == {"a": True}


def test_compute_staleness_cascades_through_chain(tmp_path: Path) -> None:
    """Stale upstream → stale downstream, even if downstream's record is clean."""
    a = _RecordingStep(id="a")  # never recorded → stale
    b = _RecordingStep(id="b", depends_on=["a"])
    c = _RecordingStep(id="c", depends_on=["b"])
    state = StateFile(
        steps={
            # b and c look clean in isolation, but cascade marks them stale.
            "b": StepStateRecord(
                id="b", phase="data_synth", status=StepStatus.FRESH, fingerprint="x"
            ),
            "c": StepStateRecord(
                id="c", phase="data_synth", status=StepStatus.FRESH, fingerprint="y"
            ),
        },
    )
    ordered = resolve_dag([_as_step(a), _as_step(b), _as_step(c)])
    stale = compute_staleness(ordered, state, run_root=tmp_path)
    assert stale == {"a": True, "b": True, "c": True}


def test_compute_staleness_failed_status_is_stale(tmp_path: Path) -> None:
    a = _RecordingStep(id="a")
    state = StateFile(
        steps={
            "a": StepStateRecord(
                id="a", phase="data_synth", status=StepStatus.FAILED, fingerprint=None
            ),
        },
    )
    assert compute_staleness([_as_step(a)], state, run_root=tmp_path) == {"a": True}


def test_compute_staleness_running_status_is_stale(tmp_path: Path) -> None:
    """RUNNING on disk means the prior run crashed; treat as stale."""
    a = _RecordingStep(id="a")
    state = StateFile(
        steps={
            "a": StepStateRecord(
                id="a",
                phase="data_synth",
                status=StepStatus.RUNNING,
                fingerprint="x",
            ),
        },
    )
    assert compute_staleness([_as_step(a)], state, run_root=tmp_path) == {"a": True}


def test_compute_staleness_force_ids_propagates_downstream(tmp_path: Path) -> None:
    a = _RecordingStep(id="a")
    b = _RecordingStep(id="b", depends_on=["a"])
    # Pretend both are FRESH on disk.
    state = StateFile(
        steps={
            "a": StepStateRecord(
                id="a", phase="data_synth", status=StepStatus.FRESH, fingerprint="x"
            ),
            "b": StepStateRecord(
                id="b", phase="data_synth", status=StepStatus.FRESH, fingerprint="y"
            ),
        },
    )
    ordered = resolve_dag([_as_step(a), _as_step(b)])
    stale = compute_staleness(ordered, state, run_root=tmp_path, force_ids=frozenset({"a"}))
    assert stale == {"a": True, "b": True}


# --------------------------------------------------------------------------- #
# run_pipeline — happy paths
# --------------------------------------------------------------------------- #


def test_run_pipeline_runs_all_stale_steps_in_topo_order(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    a = _RecordingStep(id="a", outputs=[Path("data/a.json")])
    b = _RecordingStep(
        id="b",
        inputs=[StepInput(step_id="a")],
        depends_on=["a"],
        outputs=[Path("data/b.json")],
    )
    result = run_pipeline([_as_step(b), _as_step(a)], _ctx(out_dir, seed))
    assert result == RunResult(ran=("a", "b"), skipped=())
    assert a.calls == ["a"]
    assert b.calls == ["b"]
    state = read_state(out_dir)
    assert state.steps["a"].status is StepStatus.FRESH
    assert state.steps["b"].status is StepStatus.FRESH
    assert state.steps["a"].fingerprint is not None
    assert state.steps["b"].fingerprint is not None


def test_run_pipeline_is_idempotent_when_clean(tmp_path: Path) -> None:
    """Re-running with no changes must not invoke any ``Step.run``."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    a = _RecordingStep(id="a", outputs=[Path("data/a.json")])
    run_pipeline([_as_step(a)], _ctx(out_dir, seed))
    assert a.calls == ["a"]

    second = run_pipeline([_as_step(a)], _ctx(out_dir, seed))
    assert second == RunResult(ran=(), skipped=("a",))
    # No additional run.
    assert a.calls == ["a"]


def test_run_pipeline_no_steps_is_no_op(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    result = run_pipeline([], _ctx(out_dir, seed))
    assert result == RunResult(ran=(), skipped=())


def test_run_pipeline_re_runs_when_input_file_changes(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    input_file = tmp_path / "input.txt"
    input_file.write_text("v1", encoding="utf-8")

    a = _RecordingStep(
        id="a",
        inputs=[FileInput(path=input_file)],
        outputs=[Path("data/a.json")],
    )
    run_pipeline([_as_step(a)], _ctx(out_dir, seed))
    assert a.calls == ["a"]

    # Mutate the input → step is stale on next run.
    input_file.write_text("v2", encoding="utf-8")
    second = run_pipeline([_as_step(a)], _ctx(out_dir, seed))
    assert second.ran == ("a",)
    assert a.calls == ["a", "a"]


def test_run_pipeline_re_runs_when_output_deleted(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    a = _RecordingStep(id="a", outputs=[Path("data/a.json")])
    run_pipeline([_as_step(a)], _ctx(out_dir, seed))

    (out_dir / "data" / "a.json").unlink()
    second = run_pipeline([_as_step(a)], _ctx(out_dir, seed))
    assert second.ran == ("a",)


def test_run_pipeline_force_ids_re_runs_targeted_and_cascades(tmp_path: Path) -> None:
    """``--from a`` semantics: re-run ``a`` and every descendant."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    a = _RecordingStep(id="a", outputs=[Path("data/a.json")])
    b = _RecordingStep(
        id="b",
        inputs=[StepInput(step_id="a")],
        depends_on=["a"],
        outputs=[Path("data/b.json")],
    )
    c = _RecordingStep(
        id="c",
        inputs=[StepInput(step_id="b")],
        depends_on=["b"],
        outputs=[Path("data/c.json")],
    )
    run_pipeline([_as_step(a), _as_step(b), _as_step(c)], _ctx(out_dir, seed))
    assert [s.calls for s in (a, b, c)] == [["a"], ["b"], ["c"]]

    second = run_pipeline(
        [_as_step(a), _as_step(b), _as_step(c)],
        _ctx(out_dir, seed),
        force_ids=frozenset({"a"}),
    )
    assert second.ran == ("a", "b", "c")
    assert second.skipped == ()


# --------------------------------------------------------------------------- #
# run_pipeline — failure path
# --------------------------------------------------------------------------- #


def test_run_pipeline_marks_step_failed_and_reraises(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    boom = _RecordingStep(id="boom", raises=RuntimeError("nope"))
    with pytest.raises(RuntimeError, match="nope"):
        run_pipeline([_as_step(boom)], _ctx(out_dir, seed))
    state = read_state(out_dir)
    assert state.steps["boom"].status is StepStatus.FAILED
    assert state.steps["boom"].fingerprint is None


def test_run_pipeline_failed_step_is_stale_on_next_run(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    boom = _RecordingStep(id="boom", raises=RuntimeError("nope"))
    with pytest.raises(RuntimeError):
        run_pipeline([_as_step(boom)], _ctx(out_dir, seed))

    # Heal: drop the exception and add an output so the step succeeds.
    healed = _RecordingStep(id="boom", outputs=[Path("data/boom.json")])
    second = run_pipeline([_as_step(healed)], _ctx(out_dir, seed))
    assert second.ran == ("boom",)
    assert read_state(out_dir).steps["boom"].status is StepStatus.FRESH


def test_run_pipeline_does_not_run_downstream_after_upstream_fails(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    a = _RecordingStep(id="a", raises=RuntimeError("a-fail"))
    b = _RecordingStep(id="b", depends_on=["a"], outputs=[Path("data/b.json")])
    with pytest.raises(RuntimeError, match="a-fail"):
        run_pipeline([_as_step(a), _as_step(b)], _ctx(out_dir, seed))
    assert b.calls == []
    state = read_state(out_dir)
    assert state.steps["a"].status is StepStatus.FAILED
    # b never recorded — it never started.
    assert "b" not in state.steps


# --------------------------------------------------------------------------- #
# DAG errors propagate from run_pipeline
# --------------------------------------------------------------------------- #


def test_run_pipeline_rejects_cycle(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    a = _RecordingStep(id="a", depends_on=["b"])
    b = _RecordingStep(id="b", depends_on=["a"])
    with pytest.raises(CycleError):
        run_pipeline([_as_step(a), _as_step(b)], _ctx(out_dir, seed))


def test_run_pipeline_rejects_missing_dependency(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    a = _RecordingStep(id="a", depends_on=["ghost"])
    with pytest.raises(MissingDependencyError):
        run_pipeline([_as_step(a)], _ctx(out_dir, seed))
