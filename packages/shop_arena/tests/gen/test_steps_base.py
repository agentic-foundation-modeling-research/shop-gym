"""Unit tests for :mod:`shop_arena.gen.steps.base`.

Covers the Step contract requirements from
``docs/impl/shop_gen_implementation.md`` T1.2:

* :class:`StepStatus` exposes the documented lifecycle values.
* :class:`FileInput` / :class:`StepInput` are frozen, hashable, and
  flow through the :data:`InputRef` union.
* A concrete example step satisfies the :class:`Step` Protocol at
  runtime via :func:`isinstance` (the Protocol is
  ``@runtime_checkable``).
* :class:`StepContext` carries ``config``, ``out_dir``, and an optional
  one-shot LLM completer.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.steps.base import (
    FileInput,
    InputRef,
    Step,
    StepContext,
    StepInput,
    StepStatus,
)

# --------------------------------------------------------------------------- #
# StepStatus
# --------------------------------------------------------------------------- #


def test_step_status_exposes_lifecycle_values() -> None:
    """All five documented states are present and stringly addressable."""
    assert {member.value for member in StepStatus} == {
        "pending",
        "stale",
        "running",
        "fresh",
        "failed",
    }


def test_step_status_round_trips_via_value() -> None:
    """Values persisted to ``state.json`` deserialise back to the same enum member."""
    for member in StepStatus:
        assert StepStatus(member.value) is member


# --------------------------------------------------------------------------- #
# InputRef arms
# --------------------------------------------------------------------------- #


def test_file_input_carries_path() -> None:
    ref = FileInput(path=Path("/tmp/x.json"))
    assert ref.path == Path("/tmp/x.json")


def test_step_input_carries_step_id() -> None:
    ref = StepInput(step_id="synth_identity")
    assert ref.step_id == "synth_identity"


def test_file_input_is_frozen() -> None:
    ref = FileInput(path=Path("/x"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.path = Path("/y")  # type: ignore[misc]


def test_step_input_is_frozen() -> None:
    ref = StepInput(step_id="upstream")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.step_id = "other"  # type: ignore[misc]


def test_input_refs_are_hashable_for_dedup() -> None:
    """Frozen dataclasses are hashable; the runner relies on this for dedup."""
    refs: set[InputRef] = {
        FileInput(path=Path("/a")),
        FileInput(path=Path("/a")),
        StepInput(step_id="up"),
    }
    assert len(refs) == 2  # noqa: PLR2004


def test_input_ref_union_accepts_both_arms() -> None:
    refs: list[InputRef] = [
        FileInput(path=Path("/tmp/x")),
        StepInput(step_id="upstream"),
    ]
    assert isinstance(refs[0], FileInput)
    assert isinstance(refs[1], StepInput)


# --------------------------------------------------------------------------- #
# Step Protocol (T1.2 "example concrete step compiles")
# --------------------------------------------------------------------------- #


class _ExampleStep:
    """Minimal concrete step used to verify the Protocol is satisfiable.

    Mirrors the shape every real step in :mod:`shop_arena.gen.manual_merge`,
    :mod:`shop_arena.gen.data_synth`, etc. will adopt.
    """

    def __init__(self) -> None:
        self.id: str = "example"
        self.phase: str = "data_synth"
        self.inputs: list[InputRef] = []
        self.outputs: list[Path] = []
        self.depends_on: list[str] = []
        self.version: int = 1

    def run(self, ctx: StepContext) -> None:
        del ctx


def test_example_step_satisfies_protocol_at_runtime() -> None:
    """``Step`` is ``@runtime_checkable`` — ``isinstance`` is the contract test."""
    step = _ExampleStep()
    assert isinstance(step, Step)


def test_example_step_typechecks_as_step_attribute() -> None:
    """Type-narrowing path that pyright/mypy follow at strict mode."""
    step: Step = _ExampleStep()
    assert step.id == "example"
    assert step.phase == "data_synth"
    assert step.version == 1
    assert step.inputs == []
    assert step.outputs == []
    assert step.depends_on == []


def test_step_with_inputs_and_outputs_satisfies_protocol() -> None:
    """A step that declares real inputs / outputs / deps still satisfies the Protocol."""

    class _Wired:
        def __init__(self) -> None:
            self.id: str = "synth_collections"
            self.phase: str = "data_synth"
            self.inputs: list[InputRef] = [
                StepInput(step_id="synth_identity"),
                FileInput(path=Path("manual/manual.md")),
            ]
            self.outputs: list[Path] = [Path(".shop_gen/stage_cache/collections.json")]
            self.depends_on: list[str] = ["synth_identity"]
            self.version: int = 1

        def run(self, ctx: StepContext) -> None:
            del ctx

    step: Step = _Wired()
    assert isinstance(step, Step)
    assert isinstance(step.inputs[0], StepInput)
    assert isinstance(step.inputs[1], FileInput)


def test_object_missing_run_method_fails_isinstance() -> None:
    """Runtime-checkable Protocol detects shape mismatches."""

    class _NotAStep:
        def __init__(self) -> None:
            self.id: str = "x"
            self.phase: str = "y"
            self.inputs: list[InputRef] = []
            self.outputs: list[Path] = []
            self.depends_on: list[str] = []
            self.version: int = 1

    assert not isinstance(_NotAStep(), Step)


# --------------------------------------------------------------------------- #
# StepContext
# --------------------------------------------------------------------------- #


def test_step_context_holds_config_and_out_dir(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[seed])
    ctx = StepContext(config=cfg, out_dir=out_dir)
    assert ctx.config == cfg
    assert ctx.out_dir == out_dir
    assert ctx.runtime is None


def test_step_context_is_frozen(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    cfg = ShopGenConfig(seeds=[seed])
    ctx = StepContext(config=cfg, out_dir=tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.out_dir = tmp_path / "other"  # type: ignore[misc]


def test_step_context_accepts_llm_completer(tmp_path: Path) -> None:
    """StepContext.runtime accepts any object satisfying ``LLMCompleter``."""

    class _StubCompleter:
        def complete(self, prompt: str, *, timeout: float) -> str:
            return ""

    seed = tmp_path / "seed"
    seed.mkdir()
    cfg = ShopGenConfig(seeds=[seed])
    ctx = StepContext(config=cfg, out_dir=tmp_path, runtime=_StubCompleter())
    assert ctx.runtime is not None
    assert ctx.runtime.complete("hi", timeout=1.0) == ""
