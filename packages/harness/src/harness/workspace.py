"""Filesystem workspace helpers for the plan + exec harness (spec §5.3).

The harness owns the `run_dir/` layout. This module is responsible for:

* `Workspace.create(config)` — materialising the §5.3 directory layout from
  a `PlanExecLoopConfig`. Refuses to overwrite an existing non-empty
  workspace.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.config import PlanExecLoopConfig

_AGENTS_FILENAME = "AGENTS.md"
_PROMPTS_DIRNAME = "prompts"
_PLANNER_PROMPT_FILENAME = "planner.md"
_EXECUTE_PROMPT_FILENAME = "execute.md"
_ARTIFACT_DIRNAME = "artifact"
_PLAN_FILENAME = "plan.md"
_ITERS_DIRNAME = "iters"
_RUN_SUMMARY_FILENAME = "run.json"


class WorkspaceError(Exception):
    """Raised when the harness refuses to create or write a workspace."""


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
    """

    run_dir: Path

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

        ws = cls(run_dir=run_dir)
        ws.agents_md.write_text(config.agents_md, encoding="utf-8")
        ws.prompts_dir.mkdir()
        ws.planner_prompt.write_text(config.prompts.planner, encoding="utf-8")
        ws.execute_prompt.write_text(config.prompts.execute, encoding="utf-8")
        ws.artifact_dir.mkdir()
        if config.artifact_seed_dir is not None:
            _copy_tree_into(config.artifact_seed_dir, ws.artifact_dir)
        ws.plan_md.write_text("", encoding="utf-8")
        ws.iters_dir.mkdir()
        return ws

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


def _copy_tree_into(src: Path, dst: Path) -> None:
    """Copy every entry under `src` into the existing directory `dst`."""
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)
