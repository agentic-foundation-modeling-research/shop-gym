"""Tests for `harness.workspace`."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath

import pytest

from harness.config import PlanExecLoopConfig, Prompts
from harness.plan.parser import InvalidPlanError
from harness.seed import SeedManifest
from harness.workspace import (
    ResumeMismatchError,
    Workspace,
    WorkspaceError,
    atomic_write_json,
)

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


# ---------------------------------------------------------------------------
# Workspace.create — persisted seed manifest (resume.md §5.1)
# ---------------------------------------------------------------------------


def test_create_persists_seed_manifest_when_seed_dir_provided(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    (seed / "prefetch" / "robots.txt").write_text("ok", encoding="utf-8")

    ws = Workspace.create(_config(tmp_path, seed=seed))

    assert ws.harness_internal_dir.is_dir()
    assert ws.seed_manifest_path.is_file()
    payload = json.loads(ws.seed_manifest_path.read_text(encoding="utf-8"))
    assert payload["seeded_roots"] == ["prefetch"]
    assert "prefetch/robots.txt" in payload["files"]


def test_create_does_not_persist_seed_manifest_when_no_seed_dir(tmp_path: Path) -> None:
    ws = Workspace.create(_config(tmp_path))

    assert not ws.harness_internal_dir.exists()
    assert not ws.seed_manifest_path.exists()


def test_persisted_seed_manifest_round_trips_to_in_memory(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    (seed / "prefetch" / "robots.txt").write_text("ok", encoding="utf-8")
    (seed / "policy.md").write_text("be nice", encoding="utf-8")

    ws = Workspace.create(_config(tmp_path, seed=seed))

    assert ws.seed_manifest is not None
    payload = json.loads(ws.seed_manifest_path.read_text(encoding="utf-8"))
    restored = SeedManifest.from_json(payload)
    assert restored.files == dict(ws.seed_manifest.files)
    assert restored.seeded_roots == ws.seed_manifest.seeded_roots


def test_harness_internal_dir_is_sibling_of_artifact_not_inside(tmp_path: Path) -> None:
    """`.harness/` lives at run_dir root, never inside `artifact/`."""
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    (seed / "prefetch" / "robots.txt").write_text("ok", encoding="utf-8")

    ws = Workspace.create(_config(tmp_path, seed=seed))

    # `.harness/` is at run_dir root.
    assert (ws.run_dir / ".harness").is_dir()
    # `.harness/` is not under artifact/, so the seeded subtree scan
    # naturally excludes it without any explicit filtering.
    assert not (ws.artifact_dir / ".harness").exists()
    assert ws.seed_manifest is not None
    # No manifest entry references `.harness/`.
    assert all(".harness" not in p.as_posix() for p in ws.seed_manifest.files)
    assert all(".harness" not in p.as_posix() for p in ws.seed_manifest.seeded_roots)


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


# ---------------------------------------------------------------------------
# Workspace.open — happy path
# ---------------------------------------------------------------------------


_PARSEABLE_PLAN = "## Tasks\n- [ ] homepage\n"


def _seed_dir_with_one_file(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    (seed / "prefetch").mkdir(parents=True)
    (seed / "prefetch" / "robots.txt").write_text("ok", encoding="utf-8")
    return seed


def test_open_returns_workspace_when_unseeded_identity_matches(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")

    ws = Workspace.open(cfg.run_dir, config=cfg)

    assert ws.run_dir == cfg.run_dir
    assert ws.seed_manifest is None
    assert ws.agents_md.read_text(encoding="utf-8") == _AGENTS_MD


def test_open_returns_workspace_with_persisted_manifest_when_seeded(tmp_path: Path) -> None:
    seed = _seed_dir_with_one_file(tmp_path)
    cfg = _config(tmp_path, seed=seed)
    created = Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")

    ws = Workspace.open(cfg.run_dir, config=cfg)

    assert ws.seed_manifest is not None
    assert created.seed_manifest is not None
    assert ws.seed_manifest.seeded_roots == created.seed_manifest.seeded_roots
    assert dict(ws.seed_manifest.files) == dict(created.seed_manifest.files)


def test_open_does_not_mutate_the_workspace(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    before = {p.relative_to(cfg.run_dir): p.stat().st_mtime_ns for p in _walk(cfg.run_dir)}

    Workspace.open(cfg.run_dir, config=cfg)

    after = {p.relative_to(cfg.run_dir): p.stat().st_mtime_ns for p in _walk(cfg.run_dir)}
    assert set(before) == set(after)


def _walk(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


# ---------------------------------------------------------------------------
# Workspace.open — missing files
# ---------------------------------------------------------------------------


def test_open_raises_for_missing_agents_md(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    (cfg.run_dir / "AGENTS.md").unlink()

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "agents_md"
    assert exc_info.value.run_dir == cfg.run_dir
    assert "missing" in exc_info.value.prior_repr


def test_open_raises_for_missing_planner_prompt(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    (cfg.run_dir / "prompts" / "planner.md").unlink()

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "prompts.planner"


def test_open_raises_for_missing_execute_prompt(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    (cfg.run_dir / "prompts" / "execute.md").unlink()

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "prompts.execute"


def test_open_raises_for_missing_plan_md(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    # plan.md was created empty by `Workspace.create`; remove it.
    (cfg.run_dir / "plan.md").unlink()

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "plan_md"


def test_open_raises_for_missing_iters_dir(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    iters = cfg.run_dir / "iters"
    iters.rmdir()

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "iters_dir"


# ---------------------------------------------------------------------------
# Workspace.open — content mismatches
# ---------------------------------------------------------------------------


def test_open_raises_on_agents_md_mismatch(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    (cfg.run_dir / "AGENTS.md").write_text("# Different\n", encoding="utf-8")

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "agents_md"


def test_open_raises_on_planner_prompt_mismatch(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    (cfg.run_dir / "prompts" / "planner.md").write_text("changed.\n", encoding="utf-8")

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "prompts.planner"


def test_open_raises_on_execute_prompt_mismatch(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    (cfg.run_dir / "prompts" / "execute.md").write_text("changed.\n", encoding="utf-8")

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "prompts.execute"


def test_open_validates_in_documented_order(tmp_path: Path) -> None:
    """When several fields differ, the first one in §5.2 order wins."""
    seed = _seed_dir_with_one_file(tmp_path)
    cfg = _config(tmp_path, seed=seed)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    # Mutate every identity component except the first; the first one
    # listed in §5.2 (agents_md) is the only one we *also* mutate, and
    # we expect that to be the field reported.
    (cfg.run_dir / "AGENTS.md").write_text("# X\n", encoding="utf-8")
    (cfg.run_dir / "prompts" / "planner.md").write_text("Y\n", encoding="utf-8")
    (cfg.run_dir / "prompts" / "execute.md").write_text("Z\n", encoding="utf-8")

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "agents_md"


# ---------------------------------------------------------------------------
# Workspace.open — seed manifest
# ---------------------------------------------------------------------------


def test_open_raises_when_seeded_run_has_no_persisted_manifest(tmp_path: Path) -> None:
    seed = _seed_dir_with_one_file(tmp_path)
    cfg = _config(tmp_path, seed=seed)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    # Simulate a workspace produced before M1 added persistence.
    (cfg.run_dir / ".harness" / "seed_manifest.json").unlink()

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "seed_manifest"


def test_open_raises_when_unseeded_config_meets_persisted_manifest(tmp_path: Path) -> None:
    seed = _seed_dir_with_one_file(tmp_path)
    seeded_cfg = _config(tmp_path, seed=seed)
    Workspace.create(seeded_cfg)
    seeded_cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    # Caller resumes with no `artifact_seed_dir`.
    unseeded_cfg = _config(tmp_path)

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(seeded_cfg.run_dir, config=unseeded_cfg)
    assert exc_info.value.field == "seed_manifest"


def test_open_raises_when_seed_dir_contents_changed_between_attempts(tmp_path: Path) -> None:
    seed = _seed_dir_with_one_file(tmp_path)
    cfg = _config(tmp_path, seed=seed)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    # Caller modifies the seed dir before resuming.
    (seed / "prefetch" / "robots.txt").write_text("DIFFERENT", encoding="utf-8")

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "seed_manifest"


def test_open_raises_when_seed_dir_grows_extra_top_level(tmp_path: Path) -> None:
    seed = _seed_dir_with_one_file(tmp_path)
    cfg = _config(tmp_path, seed=seed)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    (seed / "policy.md").write_text("be nice", encoding="utf-8")

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "seed_manifest"


def test_open_succeeds_when_seed_dir_is_byte_identical(tmp_path: Path) -> None:
    seed = _seed_dir_with_one_file(tmp_path)
    cfg = _config(tmp_path, seed=seed)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")

    ws = Workspace.open(cfg.run_dir, config=cfg)

    assert ws.seed_manifest is not None


def test_open_succeeds_when_unseeded_and_no_persisted_manifest(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    assert not (cfg.run_dir / ".harness" / "seed_manifest.json").exists()

    ws = Workspace.open(cfg.run_dir, config=cfg)

    assert ws.seed_manifest is None


def test_open_raises_for_corrupt_persisted_manifest(tmp_path: Path) -> None:
    seed = _seed_dir_with_one_file(tmp_path)
    cfg = _config(tmp_path, seed=seed)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(_PARSEABLE_PLAN, encoding="utf-8")
    (cfg.run_dir / ".harness" / "seed_manifest.json").write_text(
        "not json{", encoding="utf-8"
    )

    with pytest.raises(ResumeMismatchError) as exc_info:
        Workspace.open(cfg.run_dir, config=cfg)
    assert exc_info.value.field == "seed_manifest"


# ---------------------------------------------------------------------------
# Workspace.open — plan parsing
# ---------------------------------------------------------------------------


def test_open_propagates_invalid_plan_error(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Workspace.create(cfg)
    cfg.run_dir.joinpath("plan.md").write_text(
        "## Tasks\n- [ ] BADID with spaces\n", encoding="utf-8"
    )

    with pytest.raises(InvalidPlanError):
        Workspace.open(cfg.run_dir, config=cfg)


def test_open_accepts_empty_plan_md_as_invalid_plan(tmp_path: Path) -> None:
    """`Workspace.create` writes an empty plan.md; resuming before the planner
    has run is not a supported state and should surface as `InvalidPlanError`
    (no `## Tasks` section).
    """
    cfg = _config(tmp_path)
    Workspace.create(cfg)

    with pytest.raises(InvalidPlanError):
        Workspace.open(cfg.run_dir, config=cfg)


# ---------------------------------------------------------------------------
# ResumeMismatchError shape
# ---------------------------------------------------------------------------


def test_resume_mismatch_error_carries_typed_fields(tmp_path: Path) -> None:
    err = ResumeMismatchError(
        field="agents_md",
        run_dir=tmp_path / "run",
        prior_repr="A",
        current_repr="B",
    )

    assert err.field == "agents_md"
    assert err.run_dir == tmp_path / "run"
    assert err.prior_repr == "A"
    assert err.current_repr == "B"
    assert "agents_md" in str(err)
