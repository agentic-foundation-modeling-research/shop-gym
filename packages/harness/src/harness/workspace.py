"""Filesystem workspace helpers for the plan + exec harness (spec §5.3).

The harness owns the `run_dir/` layout. This module is responsible for:

* `Workspace.create(config)` — materialising the §5.3 directory layout from
  a `PlanExecLoopConfig`. Refuses to overwrite an existing non-empty
  workspace.
* `Workspace.open(run_dir, *, config)` — adopt an existing workspace for
  resume after validating the §5.2 identity tuple
  (``docs/specs/harness/resume.md``).
* `Workspace.snapshot_plan(target)` — copy the live `plan.md` byte for
  byte to a per-iteration sidecar (`plan.before.md` / `plan.after.md`).
* `atomic_write_json(path, data)` — write a JSON document via temp file +
  `os.replace`, the durable rewrite primitive used for `run.json`.

No subprocess or runtime concerns live here; the workspace is a passive
filesystem facade. See `docs/specs/harness/plan_exec_loop.md` sections 5.3-5.4.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from harness.config import PlanExecLoopConfig
from harness.plan.parser import parse as parse_plan
from harness.seed import SeedError, SeedManifest, snapshot_seed

_AGENTS_FILENAME = "AGENTS.md"
_PROMPTS_DIRNAME = "prompts"
_PLANNER_PROMPT_FILENAME = "planner.md"
_EXECUTE_PROMPT_FILENAME = "execute.md"
_ARTIFACT_DIRNAME = "artifact"
_PLAN_FILENAME = "plan.md"
_ITERS_DIRNAME = "iters"
_RUN_SUMMARY_FILENAME = "run.json"
_HARNESS_INTERNAL_DIRNAME = ".harness"
_SEED_MANIFEST_FILENAME = "seed_manifest.json"


class WorkspaceError(Exception):
    """Raised when the harness refuses to create or write a workspace."""


class ResumeMismatchError(Exception):
    """Raised when an existing `run_dir` is not continuation-compatible with `config`.

    Carried fields are stable strings so callers and tests can match on
    them without parsing the human-readable message
    (``docs/specs/harness/resume.md`` §5.2).

    Attributes:
        field: One of ``agents_md``, ``prompts.planner``,
            ``prompts.execute``, ``seed_manifest``, ``plan_md``, or
            ``iters_dir`` (for the missing-`iters/` precondition).
        run_dir: The workspace path being adopted.
        prior_repr: Compact representation of the on-disk value.
        current_repr: Compact representation of the value derived from
            `config`.
    """

    def __init__(
        self,
        *,
        field: str,
        run_dir: Path,
        prior_repr: str,
        current_repr: str,
    ) -> None:
        self.field = field
        self.run_dir = run_dir
        self.prior_repr = prior_repr
        self.current_repr = current_repr
        super().__init__(
            f"resume identity mismatch on {field} for run_dir={run_dir}: "
            f"prior={prior_repr!r} current={current_repr!r}"
        )


@dataclass(frozen=True, slots=True)
class Workspace:
    """Filesystem facade for a single harness run rooted at `run_dir`.

    A `Workspace` is a thin, immutable handle to the §5.3 layout. It does
    not cache state; every property resolves a path relative to
    `run_dir` on each access. Construct one via `Workspace.create`; do not
    instantiate this class directly except in tests that intentionally
    target a hand-built layout.

    Attributes:
        run_dir: Absolute or caller-relative path to the run workspace.
        seed_manifest: Fingerprint of files copied from
            ``config.artifact_seed_dir`` at workspace creation time, used
            by the post-iteration seed-immutability check
            (``docs/specs/harness/seed_immutability.md``). ``None`` when
            no seed dir was configured.
    """

    run_dir: Path
    seed_manifest: SeedManifest | None = field(default=None)

    @property
    def agents_md(self) -> Path:
        """Path to `AGENTS.md` (caller's project constitution)."""
        return self.run_dir / _AGENTS_FILENAME

    @property
    def prompts_dir(self) -> Path:
        """Path to the stable `prompts/` directory."""
        return self.run_dir / _PROMPTS_DIRNAME

    @property
    def planner_prompt(self) -> Path:
        """Path to the planner prompt file inside `prompts/`."""
        return self.prompts_dir / _PLANNER_PROMPT_FILENAME

    @property
    def execute_prompt(self) -> Path:
        """Path to the executor prompt file inside `prompts/`."""
        return self.prompts_dir / _EXECUTE_PROMPT_FILENAME

    @property
    def artifact_dir(self) -> Path:
        """Path to the evolving `artifact/` working area."""
        return self.run_dir / _ARTIFACT_DIRNAME

    @property
    def plan_md(self) -> Path:
        """Path to the live `plan.md` task list."""
        return self.run_dir / _PLAN_FILENAME

    @property
    def iters_dir(self) -> Path:
        """Path to the append-only per-iteration telemetry root."""
        return self.run_dir / _ITERS_DIRNAME

    @property
    def run_summary(self) -> Path:
        """Path to the atomically rewritten `run.json` summary."""
        return self.run_dir / _RUN_SUMMARY_FILENAME

    @property
    def harness_internal_dir(self) -> Path:
        """Path to the harness-internal `.harness/` directory.

        Sibling of `artifact/` so internal state (e.g. the persisted
        seed manifest) never lands inside the seeded subtree
        (``docs/specs/harness/resume.md`` §5.1).
        """
        return self.run_dir / _HARNESS_INTERNAL_DIRNAME

    @property
    def seed_manifest_path(self) -> Path:
        """Path to the persisted `.harness/seed_manifest.json`."""
        return self.harness_internal_dir / _SEED_MANIFEST_FILENAME

    @classmethod
    def create(cls, config: PlanExecLoopConfig) -> Workspace:
        """Materialise the §5.3 layout for `config` and return its handle.

        The harness is the sole writer of stable files. After this call the
        workspace contains:

        * `AGENTS.md` with `config.agents_md` verbatim,
        * `prompts/planner.md` and `prompts/execute.md` with the prompt
          bundle verbatim,
        * `artifact/` populated with the contents of
          `config.artifact_seed_dir` (if any),
        * an empty `plan.md` (the planner is the first writer),
        * an empty `iters/` directory.

        Args:
            config: Validated run configuration.

        Returns:
            A `Workspace` rooted at `config.run_dir`.

        Raises:
            WorkspaceError: If `run_dir` exists and is not an empty
                directory.
        """
        run_dir = config.run_dir
        if run_dir.exists():
            if not run_dir.is_dir():
                raise WorkspaceError(f"run_dir is not a directory: {run_dir}")
            if any(run_dir.iterdir()):
                raise WorkspaceError(f"run_dir is not empty: {run_dir}")
        else:
            run_dir.mkdir(parents=True)

        # Materialise stable surfaces first via a temporary handle, then
        # re-construct with the seed manifest so the returned `Workspace`
        # is frozen and self-consistent.
        bare = cls(run_dir=run_dir)
        bare.agents_md.write_text(config.agents_md, encoding="utf-8")
        bare.prompts_dir.mkdir()
        bare.planner_prompt.write_text(config.prompts.planner, encoding="utf-8")
        bare.execute_prompt.write_text(config.prompts.execute, encoding="utf-8")
        bare.artifact_dir.mkdir()
        seed_manifest: SeedManifest | None = None
        if config.artifact_seed_dir is not None:
            seeded_roots = _copy_tree_into(config.artifact_seed_dir, bare.artifact_dir)
            seed_manifest = snapshot_seed(bare.artifact_dir, seeded_roots)
            bare.harness_internal_dir.mkdir()
            atomic_write_json(bare.seed_manifest_path, seed_manifest.to_json())
        bare.plan_md.write_text("", encoding="utf-8")
        bare.iters_dir.mkdir()
        return cls(run_dir=run_dir, seed_manifest=seed_manifest)

    @classmethod
    def open(cls, run_dir: Path, *, config: PlanExecLoopConfig) -> Workspace:
        """Adopt an existing `run_dir` for resume after validating identity (§5.2).

        The caller (loop) selects this entry point when `run_dir` exists
        and is non-empty. Validation is read-only: nothing under
        `run_dir` is created, renamed, or rewritten by `open`. The first
        identity-tuple violation raises `ResumeMismatchError`; structural
        problems with `plan.md` propagate `InvalidPlanError`.

        Validation order (first failure wins):

        1. Required files exist: `AGENTS.md`, `prompts/planner.md`,
           `prompts/execute.md`, `plan.md`, `iters/`.
        2. `AGENTS.md` bytes equal `config.agents_md`.
        3. `prompts/planner.md` bytes equal `config.prompts.planner`.
        4. `prompts/execute.md` bytes equal `config.prompts.execute`.
        5. Seed manifest matches `config.artifact_seed_dir`. If
           `artifact_seed_dir` is set, the persisted
           `.harness/seed_manifest.json` must equal a freshly-computed
           manifest of `artifact_seed_dir`. If `artifact_seed_dir` is
           ``None``, no manifest file may exist.
        6. `plan.md` parses without `InvalidPlanError`.

        Args:
            run_dir: Existing workspace root to adopt.
            config: Caller's run configuration. Provides the prior
                identity tuple to compare on-disk values against.

        Returns:
            A `Workspace` rooted at `run_dir`, with `seed_manifest`
            populated from `.harness/seed_manifest.json` when present.

        Raises:
            ResumeMismatchError: On any missing required file or
                identity-tuple mismatch.
            InvalidPlanError: If `plan.md` fails to parse.
        """
        bare = cls(run_dir=run_dir)

        _require_path(bare.agents_md, "agents_md", run_dir, kind="file")
        _require_path(bare.planner_prompt, "prompts.planner", run_dir, kind="file")
        _require_path(bare.execute_prompt, "prompts.execute", run_dir, kind="file")
        _require_path(bare.plan_md, "plan_md", run_dir, kind="file")
        _require_path(bare.iters_dir, "iters_dir", run_dir, kind="dir")

        _check_text_match(
            bare.agents_md.read_text(encoding="utf-8"),
            config.agents_md,
            field="agents_md",
            run_dir=run_dir,
        )
        _check_text_match(
            bare.planner_prompt.read_text(encoding="utf-8"),
            config.prompts.planner,
            field="prompts.planner",
            run_dir=run_dir,
        )
        _check_text_match(
            bare.execute_prompt.read_text(encoding="utf-8"),
            config.prompts.execute,
            field="prompts.execute",
            run_dir=run_dir,
        )

        seed_manifest = _validate_seed_manifest(bare, config)

        parse_plan(bare.plan_md.read_text(encoding="utf-8"))

        return cls(run_dir=run_dir, seed_manifest=seed_manifest)

    def snapshot_plan(self, target: Path) -> None:
        """Copy the live `plan.md` byte-for-byte to `target`.

        Used for the per-iteration `plan.before.md` / `plan.after.md`
        sidecars. Parent directories are created on demand. The copy
        preserves bytes exactly; no normalization or re-encoding is
        performed.

        Args:
            target: Destination path. Must not already exist.

        Raises:
            WorkspaceError: If `plan.md` does not exist or `target`
                already exists.
        """
        if not self.plan_md.is_file():
            raise WorkspaceError(f"plan.md does not exist: {self.plan_md}")
        if target.exists():
            raise WorkspaceError(f"snapshot target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.plan_md, target)


def atomic_write_json(path: Path, data: Any) -> None:
    """Atomically write a JSON document to `path`.

    Writes to a temp file in the same directory, `fsync`s, then
    `os.replace`s into place so a reader never observes a partial file.
    The destination directory is created if missing. The JSON payload is
    pretty-printed with `indent=2` and terminated by a single newline.

    Args:
        path: Destination file path.
        data: Any JSON-serialisable value.

    Raises:
        TypeError: If `data` contains non-JSON-serialisable values.
        OSError: For underlying filesystem errors.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def _copy_tree_into(src: Path, dst: Path) -> frozenset[PurePosixPath]:
    """Copy every entry under `src` into `dst` and return the seeded roots.

    Rejects symlinks anywhere under `src` before copying anything, so the
    seed manifest never picks up files outside the literal seed tree
    (spec `seed_immutability.md` §5.2, alternative C). The returned set
    contains one POSIX-relative entry per top-level name in `src`.
    """
    _reject_symlinks(src)
    seeded_roots: set[PurePosixPath] = set()
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, symlinks=False)
        else:
            shutil.copy2(entry, target)
        seeded_roots.add(PurePosixPath(entry.name))
    return frozenset(seeded_roots)


def _reject_symlinks(root: Path) -> None:
    """Walk `root` and raise `WorkspaceError` if any entry is a symlink.

    Validation runs before any copy so the destination is never partially
    populated when a symlink is rejected.
    """
    for entry in root.iterdir():
        rel = PurePosixPath(entry.name)
        try:
            _reject_symlinks_at(entry, rel)
        except SeedError as exc:
            raise WorkspaceError(str(exc)) from exc


def _reject_symlinks_at(entry: Path, rel: PurePosixPath) -> None:
    """Recursive worker for `_reject_symlinks`; raises `SeedError` on hit."""
    if entry.is_symlink():
        raise SeedError(f"symlink in seed not supported: {rel.as_posix()}")
    if entry.is_dir():
        for child in entry.iterdir():
            _reject_symlinks_at(child, rel / child.name)


# ---------------------------------------------------------------------------
# Workspace.open helpers (resume.md §5.2)
# ---------------------------------------------------------------------------


_REPR_LIMIT = 80


def _truncate_repr(text: str) -> str:
    """Return a single-line repr-friendly summary of `text`, capped for messages."""
    flat = text.replace("\n", "\\n")
    if len(flat) <= _REPR_LIMIT:
        return flat
    return flat[:_REPR_LIMIT] + "…"


def _require_path(path: Path, field_name: str, run_dir: Path, *, kind: str) -> None:
    """Raise `ResumeMismatchError` if `path` is missing or the wrong kind."""
    if kind == "file":
        if path.is_file():
            return
        current = "<missing>" if not path.exists() else "<not a regular file>"
    elif kind == "dir":
        if path.is_dir():
            return
        current = "<missing>" if not path.exists() else "<not a directory>"
    else:  # pragma: no cover — guarded by the call sites
        raise AssertionError(f"unknown kind: {kind!r}")
    raise ResumeMismatchError(
        field=field_name,
        run_dir=run_dir,
        prior_repr=current,
        current_repr=f"<expected {kind}>",
    )


def _check_text_match(
    actual: str,
    expected: str,
    *,
    field: str,
    run_dir: Path,
) -> None:
    """Raise `ResumeMismatchError(field=...)` if the two strings differ."""
    if actual == expected:
        return
    raise ResumeMismatchError(
        field=field,
        run_dir=run_dir,
        prior_repr=_truncate_repr(actual),
        current_repr=_truncate_repr(expected),
    )


def _validate_seed_manifest(
    bare: Workspace,
    config: PlanExecLoopConfig,
) -> SeedManifest | None:
    """Return the persisted seed manifest after confirming it matches `config`.

    Three valid configurations:

    * `config.artifact_seed_dir is None` and no persisted manifest:
      ``return None`` (unseeded run; resume continues unseeded).
    * `config.artifact_seed_dir` is set and a persisted manifest matches:
      return the persisted manifest.
    * `config.artifact_seed_dir is None` *and* a persisted manifest
      exists, or the seed dir is set but the persisted manifest is
      missing or differs: raise ``ResumeMismatchError(field="seed_manifest")``.
    """
    persisted_path = bare.seed_manifest_path
    persisted_exists = persisted_path.is_file()

    if config.artifact_seed_dir is None:
        if persisted_exists:
            raise ResumeMismatchError(
                field="seed_manifest",
                run_dir=bare.run_dir,
                prior_repr="<seeded run>",
                current_repr="<artifact_seed_dir is None>",
            )
        return None

    if not persisted_exists:
        raise ResumeMismatchError(
            field="seed_manifest",
            run_dir=bare.run_dir,
            prior_repr="<no .harness/seed_manifest.json>",
            current_repr="<artifact_seed_dir is set>",
        )

    try:
        persisted_payload = json.loads(persisted_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResumeMismatchError(
            field="seed_manifest",
            run_dir=bare.run_dir,
            prior_repr=f"<unreadable: {exc.msg}>",
            current_repr="<valid manifest>",
        ) from exc
    persisted_manifest = SeedManifest.from_json(persisted_payload)

    fresh_manifest = _compute_seed_manifest(config.artifact_seed_dir)

    if (
        persisted_manifest.seeded_roots != fresh_manifest.seeded_roots
        or dict(persisted_manifest.files) != dict(fresh_manifest.files)
    ):
        raise ResumeMismatchError(
            field="seed_manifest",
            run_dir=bare.run_dir,
            prior_repr=_summarise_manifest(persisted_manifest),
            current_repr=_summarise_manifest(fresh_manifest),
        )
    return persisted_manifest


def _compute_seed_manifest(seed_dir: Path) -> SeedManifest:
    """Build a `SeedManifest` for `seed_dir` without copying it.

    Mirrors `Workspace.create`'s seeding step: top-level entries become
    `seeded_roots`, sha256 fingerprints are taken in place. Any symlink
    raises a `WorkspaceError` so resume cannot adopt a manifest derived
    from outside the literal seed tree.
    """
    _reject_symlinks(seed_dir)
    seeded_roots = frozenset(PurePosixPath(entry.name) for entry in seed_dir.iterdir())
    return snapshot_seed(seed_dir, seeded_roots)


def _summarise_manifest(manifest: SeedManifest) -> str:
    """Compact string representation of a manifest for error messages."""
    return (
        f"<roots={sorted(p.as_posix() for p in manifest.seeded_roots)} "
        f"files={len(manifest.files)}>"
    )
