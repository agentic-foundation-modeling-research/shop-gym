"""Tests for `harness.workspace`."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath

import pytest

from harness.config import PlanExecLoopConfig, Prompts
from harness.workspace import Workspace, WorkspaceError, atomic_write_json

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_PLANNER_PROMPT = "plan it.\n"
_EXECUTE_PROMPT = "execute it.\n"
_AGENTS_MD = "# Project Constitution\nbe nice.\n"


def _config(tmp_path: Path, *, seed: Path | None = None) -> PlanExecLoopConfig:
    return PlanExecLoopConfig(
        run_dir=tmp_path / "run",
        prompts=Prompts(planner=_PLANNER_PROMPT, execute=_EXECUTE_PROMPT),
        agents_md=_AGENTS_MD,
        artifact_seed_dir=seed,
        max_iters=3,
        timeout=60.0,
    )


# ---------------------------------------------------------------------------
# Workspace.create — layout
# ---------------------------------------------------------------------------


def test_create_materialises_layout(tmp_path: Path) -> None:
    cfg = _config(tmp_path)

    ws = Workspace.create(cfg)

    assert ws.run_dir == cfg.run_dir
    assert ws.agents_md.is_file()
    assert ws.prompts_dir.is_dir()
    assert ws.planner_prompt.is_file()
    assert ws.execute_prompt.is_file()
    assert ws.artifact_dir.is_dir()
    assert ws.plan_md.is_file()
    assert ws.iters_dir.is_dir()
    # `run.json` is harness-rewritten later; create() must not pre-write it.
    assert not ws.run_summary.exists()


def test_create_writes_caller_inputs_verbatim(tmp_path: Path) -> None:
    cfg = _config(tmp_path)

    ws = Workspace.create(cfg)

    assert ws.agents_md.read_text(encoding="utf-8") == _AGENTS_MD
    assert ws.planner_prompt.read_text(encoding="utf-8") == _PLANNER_PROMPT
    assert ws.execute_prompt.read_text(encoding="utf-8") == _EXECUTE_PROMPT


def test_create_starts_plan_md_empty(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))

    assert ws.plan_md.read_text(encoding="utf-8") == ""


def test_create_artifact_dir_is_empty_without_seed(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))

    assert list(ws.artifact_dir.iterdir()) == []


def test_create_iters_dir_is_empty(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))

    assert list(ws.iters_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Workspace.create — run_dir preconditions
# ---------------------------------------------------------------------------


def test_create_accepts_nonexistent_run_dir(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    assert not cfg.run_dir.exists()

    ws = Workspace.create(cfg)

    assert ws.run_dir.is_dir()


def test_create_accepts_existing_empty_run_dir(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.run_dir.mkdir()

    ws = Workspace.create(cfg)

    assert ws.agents_md.is_file()


def test_create_rejects_non_empty_run_dir(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.run_dir.mkdir()
    (cfg.run_dir / "leftover.txt").write_text("hi")

    with pytest.raises(WorkspaceError, match="not empty"):
        Workspace.create(cfg)


def test_create_rejects_run_dir_that_is_a_file(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.run_dir.write_text("oops")

    with pytest.raises(WorkspaceError, match="not a directory"):
        Workspace.create(cfg)


def test_create_creates_parent_directories(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "run"
    cfg = PlanExecLoopConfig(
        run_dir=deep,
        prompts=Prompts(planner="p", execute="e"),
        agents_md="# x\n",
        max_iters=1,
        timeout=1.0,
    )

    ws = Workspace.create(cfg)

    assert ws.run_dir == deep
    assert deep.is_dir()


# ---------------------------------------------------------------------------
# Workspace.create — artifact seeding
# ---------------------------------------------------------------------------


def test_create_copies_artifact_seed_directory(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    (seed / "nested").mkdir(parents=True)
    (seed / "top.txt").write_text("hello", encoding="utf-8")
    (seed / "nested" / "deep.bin").write_bytes(b"\x00\x01\x02")

    ws = Workspace.create(_config(tmp_path, seed=seed))

    assert (ws.artifact_dir / "top.txt").read_text(encoding="utf-8") == "hello"
    assert (ws.artifact_dir / "nested" / "deep.bin").read_bytes() == b"\x00\x01\x02"


def test_create_artifact_seed_does_not_leak_into_run_root(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "marker").write_text("x")

    ws = Workspace.create(_config(tmp_path, seed=seed))

    # Seed entries land under artifact/, not at run_dir root.
    assert not (ws.run_dir / "marker").exists()
    assert (ws.artifact_dir / "marker").is_file()


# ---------------------------------------------------------------------------
# Workspace.create — seed manifest
# ---------------------------------------------------------------------------


def test_create_records_seed_manifest_for_each_seeded_top_level(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    (seed / "prefetch" / "robots.txt").write_text("ok", encoding="utf-8")
    (seed / "policy.md").write_text("be nice", encoding="utf-8")

    ws = Workspace.create(_config(tmp_path, seed=seed))

    assert ws.seed_manifest is not None
    assert ws.seed_manifest.seeded_roots == frozenset(
        {PurePosixPath("prefetch"), PurePosixPath("policy.md")}
    )
    assert set(ws.seed_manifest.files) == {
        PurePosixPath("prefetch/robots.txt"),
        PurePosixPath("policy.md"),
    }


def test_create_seed_manifest_is_none_when_no_seed_dir(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))

    assert ws.seed_manifest is None


def test_create_rejects_symlink_in_seed_top_level(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    target = tmp_path / "target_dir"
    target.mkdir()
    (target / "data.txt").write_text("data", encoding="utf-8")
    (seed / "shortcut").symlink_to(target)

    cfg = _config(tmp_path, seed=seed)

    with pytest.raises(WorkspaceError, match="symlink in seed not supported"):
        Workspace.create(cfg)


def test_create_rejects_nested_symlink_in_seed(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    target = tmp_path / "leaked.txt"
    target.write_text("nope", encoding="utf-8")
    (seed / "prefetch" / "shortcut").symlink_to(target)

    cfg = _config(tmp_path, seed=seed)

    with pytest.raises(WorkspaceError, match="symlink in seed not supported"):
        Workspace.create(cfg)


def test_create_symlink_rejection_does_not_leave_partial_artifact(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    (seed / "prefetch" / "valid.txt").write_text("ok", encoding="utf-8")
    target = tmp_path / "leaked.txt"
    target.write_text("nope", encoding="utf-8")
    (seed / "prefetch" / "shortcut").symlink_to(target)

    cfg = _config(tmp_path, seed=seed)

    with pytest.raises(WorkspaceError):
        Workspace.create(cfg)

    # Validation runs before any copy, so the artifact dir was never seeded.
    artifact_dir = cfg.run_dir / "artifact"
    assert not artifact_dir.exists() or list(artifact_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Workspace.snapshot_plan
# ---------------------------------------------------------------------------


def test_snapshot_plan_is_byte_identical(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    payload = "# Plan\n\n## Tasks\n- [ ] homepage\n- [~] checkout\n"
    ws.plan_md.write_text(payload, encoding="utf-8")
    target = ws.iters_dir / "exec-0001" / "plan.before.md"

    ws.snapshot_plan(target)

    assert target.read_bytes() == ws.plan_md.read_bytes()


def test_snapshot_plan_creates_parent_dirs(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    target = ws.iters_dir / "exec-0007" / "nested" / "plan.after.md"

    ws.snapshot_plan(target)

    assert target.is_file()


def test_snapshot_plan_rejects_existing_target(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    target = ws.iters_dir / "exec-0001" / "plan.before.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="already exists"):
        ws.snapshot_plan(target)


def test_snapshot_plan_rejects_when_plan_md_missing(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))
    ws.plan_md.unlink()

    with pytest.raises(WorkspaceError, match=r"plan\.md does not exist"):
        ws.snapshot_plan(ws.iters_dir / "exec-0001" / "plan.before.md")


# ---------------------------------------------------------------------------
# atomic_write_json
# ---------------------------------------------------------------------------


def test_atomic_write_json_writes_payload(tmp_path: Path) -> None:
    target = tmp_path / "run.json"

    atomic_write_json(target, {"final_status": "completed", "exec_iter_count": 2})

    payload = target.read_text(encoding="utf-8")
    assert payload.endswith("\n")
    assert json.loads(payload) == {"final_status": "completed", "exec_iter_count": 2}


def test_atomic_write_json_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "run.json"
    target.write_text("stale", encoding="utf-8")

    atomic_write_json(target, {"x": 1})

    assert json.loads(target.read_text(encoding="utf-8")) == {"x": 1}


def test_atomic_write_json_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "deeply" / "nested" / "run.json"

    atomic_write_json(target, [1, 2, 3])

    assert json.loads(target.read_text(encoding="utf-8")) == [1, 2, 3]


def test_atomic_write_json_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "run.json"

    atomic_write_json(target, {"k": "v"})

    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["run.json"]


def test_atomic_write_json_rejects_unserialisable(tmp_path: Path) -> None:
    target = tmp_path / "run.json"

    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": object()})

    # Failed writes must not leak temp files into the target directory.
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_json_replaces_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Destination always reads as previous or new payload, never partial bytes."""
    target = tmp_path / "run.json"
    atomic_write_json(target, {"v": 1})
    snapshots: list[str] = []

    real_replace = os.replace

    def spy_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        # Capture the destination contents immediately before the swap.
        snapshots.append(Path(dst).read_text(encoding="utf-8"))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    atomic_write_json(target, {"v": 2})

    assert json.loads(snapshots[0]) == {"v": 1}
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}
