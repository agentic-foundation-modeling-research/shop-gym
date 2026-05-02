"""Unit tests for :mod:`shop_arena.gen.manual_merge.copy_seed`.

Covers the T2.6 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``copy_seed_manual`` copies the seed's ``capabilities.json``,
  ``manual.md``, and ``stats.json`` verbatim into ``manual/`` (identical
  bytes — spec §5.2 "manual files are copied verbatim").
* The step never invokes the LLM (``ctx.runtime`` is left untouched).
* The step contract surfaces the canonical id / phase / inputs /
  outputs / version so the runner can DAG-resolve and fingerprint it.
* The listing-branch placeholder (``seed_dir=None``) advertises its id
  but raises if the runner ever tries to execute it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.manual_merge.copy_seed import CopySeedManualStep
from shop_arena.gen.steps.base import FileInput, Step, StepContext

_ARTIFACT_FILES = ("capabilities.json", "manual.md", "stats.json")


@dataclass
class _RecordingCompleter:
    """Stub :class:`LLMCompleter` that fails the test if called."""

    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        raise AssertionError("copy_seed_manual must not invoke the LLM")


def _write_seed(seed_dir: Path, *, payloads: dict[str, bytes] | None = None) -> Path:
    """Write a seed ``artifact/`` directory and return the seed root."""
    artifact = seed_dir / "artifact"
    artifact.mkdir(parents=True, exist_ok=True)
    defaults: dict[str, bytes] = {
        "capabilities.json": b'{"version": "0.1"}\n',
        "manual.md": b"# Seed Manual\n\n## Overview\n\nseed content\n",
        "stats.json": b'{"products_total": 12}\n',
    }
    files = payloads if payloads is not None else defaults
    for name, content in files.items():
        (artifact / name).write_bytes(content)
    return seed_dir


# --------------------------------------------------------------------------- #
# Step contract
# --------------------------------------------------------------------------- #


def test_copy_seed_manual_step_satisfies_step_protocol(tmp_path: Path) -> None:
    seed = _write_seed(tmp_path / "seed")
    step = CopySeedManualStep(seed_dir=seed)

    assert isinstance(step, Step)
    assert step.id == "copy_seed_manual"
    assert step.phase == "manual_merge"
    assert step.depends_on == []
    assert step.version == 1
    assert step.outputs == [Path("manual") / name for name in _ARTIFACT_FILES]
    expected_inputs = [FileInput(path=seed / "artifact" / name) for name in _ARTIFACT_FILES]
    assert step.inputs == expected_inputs


def test_copy_seed_manual_step_listing_placeholder_has_no_inputs() -> None:
    """``seed_dir=None`` registers a listing-branch placeholder (config-free)."""
    step = CopySeedManualStep(seed_dir=None)

    assert step.id == "copy_seed_manual"
    assert step.phase == "manual_merge"
    assert step.inputs == []
    assert step.outputs == [Path("manual") / name for name in _ARTIFACT_FILES]


# --------------------------------------------------------------------------- #
# run — happy path
# --------------------------------------------------------------------------- #


def test_copy_seed_manual_writes_identical_bytes(tmp_path: Path) -> None:
    """Spec §5.2 check: the published files match seed bytes exactly."""
    seed = _write_seed(tmp_path / "seed")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    CopySeedManualStep(seed_dir=seed).run(ctx)

    for name in _ARTIFACT_FILES:
        source = (seed / "artifact" / name).read_bytes()
        copied = (out_dir / "manual" / name).read_bytes()
        assert source == copied, f"{name}: bytes diverged"


def test_copy_seed_manual_preserves_arbitrary_byte_payloads(tmp_path: Path) -> None:
    """Verbatim copy must work for any byte payload, not just well-formed JSON."""
    payloads = {
        "capabilities.json": b"\x00binary-not-actually-json\x01",
        "manual.md": "# unicode — \u2603\n".encode(),
        "stats.json": b"",
    }
    seed = _write_seed(tmp_path / "seed", payloads=payloads)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    CopySeedManualStep(seed_dir=seed).run(ctx)

    for name, expected in payloads.items():
        assert (out_dir / "manual" / name).read_bytes() == expected


def test_copy_seed_manual_does_not_invoke_llm(tmp_path: Path) -> None:
    """T2.6 check: zero LLM calls for the single-seed shortcut."""
    seed = _write_seed(tmp_path / "seed")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    completer = _RecordingCompleter()
    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir, runtime=completer)

    CopySeedManualStep(seed_dir=seed).run(ctx)

    assert completer.prompts == []


def test_copy_seed_manual_creates_manual_dir(tmp_path: Path) -> None:
    """The step must create ``manual/`` if the run workspace is empty."""
    seed = _write_seed(tmp_path / "seed")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    assert not (out_dir / "manual").exists()
    CopySeedManualStep(seed_dir=seed).run(ctx)
    assert (out_dir / "manual").is_dir()


def test_copy_seed_manual_is_idempotent(tmp_path: Path) -> None:
    """Re-running the step against the same seed produces the same bytes."""
    seed = _write_seed(tmp_path / "seed")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    step = CopySeedManualStep(seed_dir=seed)
    step.run(ctx)
    first = {name: (out_dir / "manual" / name).read_bytes() for name in _ARTIFACT_FILES}
    step.run(ctx)
    second = {name: (out_dir / "manual" / name).read_bytes() for name in _ARTIFACT_FILES}
    assert first == second


# --------------------------------------------------------------------------- #
# run — error paths
# --------------------------------------------------------------------------- #


def test_copy_seed_manual_raises_when_artifact_file_missing(tmp_path: Path) -> None:
    """Missing artifact file surfaces as :class:`FileNotFoundError`."""
    seed = _write_seed(tmp_path / "seed")
    (seed / "artifact" / "manual.md").unlink()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    with pytest.raises(FileNotFoundError, match=r"manual\.md"):
        CopySeedManualStep(seed_dir=seed).run(ctx)


def test_copy_seed_manual_listing_placeholder_refuses_to_run(tmp_path: Path) -> None:
    """The listing-branch placeholder cannot execute (config-free instance)."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    seed = _write_seed(tmp_path / "seed")
    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    with pytest.raises(ValueError, match="placeholder"):
        CopySeedManualStep(seed_dir=None).run(ctx)
