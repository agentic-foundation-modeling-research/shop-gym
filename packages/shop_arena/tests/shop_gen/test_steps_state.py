"""Unit tests for :mod:`shop_gen.steps.state`.

Covers the persistence + fingerprint requirements from
``docs/impl/shop_gen_implementation.md`` T1.3:

* ``state.json`` reader / writer round-trips through the closed schema.
* Atomic writer leaves the prior file intact when an injected crash
  fires after the temp file is on disk but before ``os.replace``.
* Per-step fingerprint is stable across reorderings of ``inputs``,
  changes when *any* of file content / upstream fingerprint / step
  ``version`` changes, and refuses to silently invent a digest for
  missing files or never-run upstream steps.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

import shop_gen.steps.state as state_mod
from shop_gen.steps.base import FileInput, InputRef, Step, StepInput, StepStatus
from shop_gen.steps.state import (
    STATE_DIR_NAME,
    STATE_FILE_NAME,
    StateFile,
    StepStateRecord,
    compute_fingerprint,
    hash_file,
    read_state,
    state_path,
    upsert_step_state,
    write_state,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_SHA256_HEX_LEN = 64


class _StubStep:
    """Minimal concrete step used to drive ``compute_fingerprint``."""

    def __init__(
        self,
        *,
        step_id: str = "stub",
        inputs: list[InputRef] | None = None,
        version: int = 1,
    ) -> None:
        self.id: str = step_id
        self.phase: str = "data_synth"
        self.inputs: list[InputRef] = inputs if inputs is not None else []
        self.outputs: list[Path] = []
        self.depends_on: list[str] = []
        self.version: int = version

    def run(self, ctx: object) -> None:
        del ctx


def _as_step(stub: _StubStep) -> Step:
    """Narrow a ``_StubStep`` to ``Step`` (Protocol satisfied at runtime)."""
    return cast(Step, stub)


# --------------------------------------------------------------------------- #
# state_path
# --------------------------------------------------------------------------- #


def test_state_path_lives_under_dot_shop_gen(tmp_path: Path) -> None:
    """The state document sits at ``<out_dir>/.shop_gen/state.json``."""
    assert state_path(tmp_path) == tmp_path / STATE_DIR_NAME / STATE_FILE_NAME


# --------------------------------------------------------------------------- #
# read / write round-trip
# --------------------------------------------------------------------------- #


def test_read_state_returns_empty_when_missing(tmp_path: Path) -> None:
    """First-run workspaces have no state.json; the reader yields an empty doc."""
    result = read_state(tmp_path)
    assert result.steps == {}


def test_write_state_creates_parent_dir(tmp_path: Path) -> None:
    """The atomic writer materialises ``.shop_gen/`` on first write."""
    write_state(tmp_path, StateFile())
    assert (tmp_path / STATE_DIR_NAME).is_dir()
    assert state_path(tmp_path).is_file()


def test_state_round_trips_through_disk(tmp_path: Path) -> None:
    record = StepStateRecord(
        id="synth_identity",
        phase="data_synth",
        status=StepStatus.FRESH,
        fingerprint="deadbeef",
        ts="2026-04-27T00:00:00Z",
    )
    write_state(tmp_path, StateFile(steps={"synth_identity": record}))
    loaded = read_state(tmp_path)
    assert loaded.steps == {"synth_identity": record}


def test_read_state_rejects_unknown_fields(tmp_path: Path) -> None:
    """Closed schema: an unexpected key surfaces as ValidationError."""
    path = state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 1, "steps": {}, "rogue": 1}\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        read_state(tmp_path)


def test_upsert_step_state_replaces_existing() -> None:
    state = StateFile(
        steps={
            "a": StepStateRecord(id="a", phase="p", status=StepStatus.FRESH, fingerprint="x"),
        },
    )
    updated = upsert_step_state(
        state,
        StepStateRecord(id="a", phase="p", status=StepStatus.STALE, fingerprint="y"),
    )
    assert updated.steps["a"].status is StepStatus.STALE
    assert updated.steps["a"].fingerprint == "y"
    # original is untouched (StateFile is frozen)
    assert state.steps["a"].fingerprint == "x"


def test_upsert_step_state_adds_new_record() -> None:
    state = StateFile()
    updated = upsert_step_state(
        state,
        StepStateRecord(id="b", phase="p", status=StepStatus.PENDING),
    )
    assert set(updated.steps) == {"b"}


# --------------------------------------------------------------------------- #
# Atomic writes — simulated crash
# --------------------------------------------------------------------------- #


def test_write_state_is_atomic_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``os.replace`` raises, the prior state.json must remain intact and no tmp file lingers."""
    # First, lay down a known-good state.
    good = StateFile(
        steps={"a": StepStateRecord(id="a", phase="p", status=StepStatus.FRESH, fingerprint="g")},
    )
    write_state(tmp_path, good)
    expected_bytes = state_path(tmp_path).read_bytes()

    # Simulate a crash inside ``os.replace`` (the rename step is the
    # documented atomicity boundary; failure before it must not leak).

    def _boom(_src: object, _dst: object) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(state_mod.os, "replace", _boom)

    bad = StateFile(
        steps={"a": StepStateRecord(id="a", phase="p", status=StepStatus.STALE, fingerprint="b")},
    )
    with pytest.raises(OSError, match="simulated crash"):
        write_state(tmp_path, bad)

    # Original file is unchanged.
    assert state_path(tmp_path).read_bytes() == expected_bytes
    # No tmp leftovers.
    tmp_prefix = STATE_FILE_NAME + ".tmp"
    leftovers = [p for p in (tmp_path / STATE_DIR_NAME).iterdir() if p.name.startswith(tmp_prefix)]
    assert leftovers == []


def test_write_state_overwrites_existing_atomically(tmp_path: Path) -> None:
    """A successful second write replaces the first byte-for-byte."""
    write_state(tmp_path, StateFile())
    record = StepStateRecord(id="x", phase="p", status=StepStatus.FRESH, fingerprint="f")
    write_state(tmp_path, StateFile(steps={"x": record}))
    assert read_state(tmp_path).steps == {"x": record}


# --------------------------------------------------------------------------- #
# hash_file
# --------------------------------------------------------------------------- #


def test_hash_file_sha256_of_known_content(tmp_path: Path) -> None:
    """Empty file → sha256 of empty string."""
    target = tmp_path / "empty.bin"
    target.write_bytes(b"")
    # sha256("")
    assert hash_file(target) == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


def test_hash_file_streams_content_larger_than_chunk(tmp_path: Path) -> None:
    target = tmp_path / "big.bin"
    payload = b"a" * (200 * 1024)  # > 64 KiB chunk size
    target.write_bytes(payload)
    assert hash_file(target) == hashlib.sha256(payload).hexdigest()


def test_hash_file_raises_on_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        hash_file(tmp_path / "ghost.json")


# --------------------------------------------------------------------------- #
# compute_fingerprint
# --------------------------------------------------------------------------- #


def test_fingerprint_stable_for_same_inputs(tmp_path: Path) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text("hello", encoding="utf-8")
    step = _StubStep(inputs=[FileInput(path=seed)])
    state = StateFile()
    fp1 = compute_fingerprint(_as_step(step), state, run_root=tmp_path)
    fp2 = compute_fingerprint(_as_step(step), state, run_root=tmp_path)
    assert fp1 == fp2
    # 64-char lowercase hex sha256 digest.
    assert len(fp1) == _SHA256_HEX_LEN
    assert all(ch in "0123456789abcdef" for ch in fp1)


def test_fingerprint_changes_on_file_content_change(tmp_path: Path) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text("v1", encoding="utf-8")
    step = _StubStep(inputs=[FileInput(path=seed)])
    state = StateFile()
    before = compute_fingerprint(_as_step(step), state, run_root=tmp_path)
    seed.write_text("v2", encoding="utf-8")
    after = compute_fingerprint(_as_step(step), state, run_root=tmp_path)
    assert before != after


def test_fingerprint_changes_on_version_bump(tmp_path: Path) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text("hello", encoding="utf-8")
    step_v1 = _StubStep(inputs=[FileInput(path=seed)], version=1)
    step_v2 = _StubStep(inputs=[FileInput(path=seed)], version=2)
    state = StateFile()
    fp_v1 = compute_fingerprint(_as_step(step_v1), state, run_root=tmp_path)
    fp_v2 = compute_fingerprint(_as_step(step_v2), state, run_root=tmp_path)
    assert fp_v1 != fp_v2


def test_fingerprint_changes_on_upstream_fingerprint_change(tmp_path: Path) -> None:
    """A different upstream fingerprint propagates into the downstream digest."""
    step = _StubStep(inputs=[StepInput(step_id="up")])
    state_a = StateFile(
        steps={"up": StepStateRecord(id="up", phase="p", status=StepStatus.FRESH, fingerprint="a")},
    )
    state_b = StateFile(
        steps={"up": StepStateRecord(id="up", phase="p", status=StepStatus.FRESH, fingerprint="b")},
    )
    fp_a = compute_fingerprint(_as_step(step), state_a, run_root=tmp_path)
    fp_b = compute_fingerprint(_as_step(step), state_b, run_root=tmp_path)
    assert fp_a != fp_b


def test_fingerprint_invariant_under_input_reorder(tmp_path: Path) -> None:
    """Sorting before hashing → input order does not affect the digest."""
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text("alpha", encoding="utf-8")
    b.write_text("beta", encoding="utf-8")
    state = StateFile(
        steps={"up": StepStateRecord(id="up", phase="p", status=StepStatus.FRESH, fingerprint="z")},
    )
    forward = _StubStep(
        inputs=[FileInput(path=a), FileInput(path=b), StepInput(step_id="up")],
    )
    reversed_ = _StubStep(
        inputs=[StepInput(step_id="up"), FileInput(path=b), FileInput(path=a)],
    )
    assert compute_fingerprint(_as_step(forward), state, run_root=tmp_path) == compute_fingerprint(
        _as_step(reversed_), state, run_root=tmp_path
    )


def test_fingerprint_combines_files_steps_and_version(tmp_path: Path) -> None:
    """Adding any of the three input kinds flips the digest."""
    seed = tmp_path / "seed.json"
    seed.write_text("hello", encoding="utf-8")
    state = StateFile(
        steps={"up": StepStateRecord(id="up", phase="p", status=StepStatus.FRESH, fingerprint="z")},
    )
    base = _StubStep(inputs=[])
    plus_file = _StubStep(inputs=[FileInput(path=seed)])
    plus_step = _StubStep(inputs=[StepInput(step_id="up")])
    fps = {
        compute_fingerprint(_as_step(base), state, run_root=tmp_path),
        compute_fingerprint(_as_step(plus_file), state, run_root=tmp_path),
        compute_fingerprint(_as_step(plus_step), state, run_root=tmp_path),
    }
    # All three differ.
    assert len(fps) == 3  # noqa: PLR2004


def test_fingerprint_resolves_relative_paths_against_run_root(tmp_path: Path) -> None:
    """A relative ``FileInput.path`` resolves against ``run_root``."""
    sub = tmp_path / "manual"
    sub.mkdir()
    (sub / "manual.md").write_text("hello", encoding="utf-8")
    step = _StubStep(inputs=[FileInput(path=Path("manual/manual.md"))])
    fp = compute_fingerprint(_as_step(step), StateFile(), run_root=tmp_path)
    assert len(fp) == _SHA256_HEX_LEN


def test_fingerprint_raises_on_missing_file_input(tmp_path: Path) -> None:
    step = _StubStep(inputs=[FileInput(path=tmp_path / "nope.json")])
    with pytest.raises(FileNotFoundError):
        compute_fingerprint(_as_step(step), StateFile(), run_root=tmp_path)


def test_fingerprint_raises_on_unknown_upstream(tmp_path: Path) -> None:
    step = _StubStep(inputs=[StepInput(step_id="never_ran")])
    with pytest.raises(KeyError, match="never_ran"):
        compute_fingerprint(_as_step(step), StateFile(), run_root=tmp_path)


def test_fingerprint_raises_on_upstream_without_fingerprint(tmp_path: Path) -> None:
    """An upstream that ran but never recorded a fingerprint (e.g. PENDING) is not usable."""
    state = StateFile(
        steps={"up": StepStateRecord(id="up", phase="p", status=StepStatus.PENDING)},
    )
    step = _StubStep(inputs=[StepInput(step_id="up")])
    with pytest.raises(KeyError, match="up"):
        compute_fingerprint(_as_step(step), state, run_root=tmp_path)
