"""``state.json`` persistence + per-step fingerprint hashing.

Implements the resume-model storage layer documented in
``docs/specs/shop_arena/shop_arena.gen.md`` §5.7. The companion runner (T1.4)
consumes these primitives to drive staleness detection and topological
execution; this module owns only:

* the on-disk layout ``<out_dir>/.shop_gen/state.json``;
* a closed pydantic schema for the persisted records;
* an atomic writer (tmp + ``os.replace``) so a crash mid-write cannot
  corrupt the prior state;
* the deterministic per-step fingerprint:
  ``sha256(input file hashes ⊕ upstream fingerprints ⊕ step version)``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from shop_arena.gen.steps.base import FileInput, Step, StepStatus

STATE_DIR_NAME: Final[str] = ".shop_gen"
"""Hidden subdirectory under ``out_dir`` that owns runner bookkeeping."""

STATE_FILE_NAME: Final[str] = "state.json"
"""File name of the persisted state document inside :data:`STATE_DIR_NAME`."""

SCHEMA_VERSION: Final[int] = 1
"""Bumped when the on-disk schema changes incompatibly."""

_HASH_CHUNK: Final[int] = 64 * 1024
"""Read size used by :func:`hash_file` to stream large inputs."""


def state_path(out_dir: Path) -> Path:
    """Return the canonical ``state.json`` path for a run workspace.

    Args:
        out_dir: Resolved run workspace (``ShopGenConfig.out_dir`` after
            defaults are applied).

    Returns:
        ``<out_dir>/.shop_gen/state.json`` — never created by this call.
    """
    return out_dir / STATE_DIR_NAME / STATE_FILE_NAME


class StepStateRecord(BaseModel):
    """Persisted lifecycle record for a single step.

    The runner writes one record per step after every transition. The
    schema is closed (``extra="forbid"``) so an unexpected field on disk
    surfaces as a validation error rather than silent data loss.

    Attributes:
        id: Globally unique step id (matches ``Step.id``).
        phase: Phase the step belongs to (matches ``Step.phase``).
        status: Most recently observed lifecycle state.
        fingerprint: Hex sha256 from :func:`compute_fingerprint`. ``None``
            when the step has never produced outputs (``PENDING`` /
            ``FAILED`` before any successful run).
        ts: ISO-8601 UTC timestamp of the last transition. ``None`` for
            never-run steps.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    phase: str
    status: StepStatus
    fingerprint: str | None = None
    ts: str | None = None


class StateFile(BaseModel):
    """Top-level wrapper persisted as ``state.json``.

    Attributes:
        schema_version: On-disk schema version. Mismatches are rejected
            by pydantic on read.
        steps: Step id → :class:`StepStateRecord` for every step the
            runner has touched in this workspace.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=SCHEMA_VERSION)
    steps: dict[str, StepStateRecord] = Field(default_factory=dict)


def read_state(out_dir: Path) -> StateFile:
    """Load ``state.json`` from ``out_dir``.

    Args:
        out_dir: Run workspace directory.

    Returns:
        The parsed :class:`StateFile`. An empty :class:`StateFile` is
        returned when the file does not yet exist (first run).

    Raises:
        pydantic.ValidationError: The on-disk document does not satisfy
            the closed schema.
    """
    path = state_path(out_dir)
    if not path.exists():
        return StateFile()
    raw = path.read_text(encoding="utf-8")
    return StateFile.model_validate_json(raw)


def write_state(out_dir: Path, state: StateFile) -> None:
    """Atomically persist ``state`` to ``<out_dir>/.shop_gen/state.json``.

    The payload is written to a sibling ``*.tmp.<rand>`` file in the
    same directory and then ``os.replace``-d into place, so a crash
    mid-write leaves the prior ``state.json`` intact (POSIX + Windows
    both guarantee atomic same-filesystem rename).

    Args:
        out_dir: Run workspace directory.
        state: State document to persist.

    Raises:
        OSError: The filesystem rejects the temp write or the rename.
    """
    path = state_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump_json(indent=2) + "\n"
    tmp = path.with_name(f"{path.name}.tmp.{secrets.token_hex(8)}")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        # Best-effort cleanup; never mask the original exception.
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def upsert_step_state(state: StateFile, record: StepStateRecord) -> StateFile:
    """Return a new :class:`StateFile` with ``record`` merged in by id.

    Args:
        state: Prior state document (left untouched — :class:`StateFile`
            is frozen).
        record: New record for ``record.id``.

    Returns:
        A fresh :class:`StateFile` with ``record`` replacing any prior
        record for the same id.
    """
    new_steps = dict(state.steps)
    new_steps[record.id] = record
    return StateFile(schema_version=state.schema_version, steps=new_steps)


def hash_file(path: Path) -> str:
    """Return the lowercase hex sha256 of a file's bytes.

    Streamed in :data:`_HASH_CHUNK`-sized chunks so multi-megabyte
    inputs do not balloon memory.

    Args:
        path: File to hash.

    Returns:
        64-char lowercase hex digest.

    Raises:
        FileNotFoundError: ``path`` does not exist.
    """
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_input_path(path: Path, run_root: Path) -> Path:
    """Resolve a ``FileInput`` path against the run workspace.

    Absolute paths are returned unchanged; relative paths are joined to
    ``run_root`` so a step's declared inputs travel with the workspace.
    """
    return path if path.is_absolute() else run_root / path


def compute_fingerprint(
    step: Step,
    state: StateFile,
    *,
    run_root: Path,
) -> str:
    """Compute the deterministic fingerprint for ``step``.

    The fingerprint is a sha256 over a canonical, lexicographically
    sorted serialisation of:

    * each :class:`~shop_arena.gen.steps.base.FileInput`'s declared path plus
      sha256 of its bytes on disk;
    * each :class:`~shop_arena.gen.steps.base.StepInput`'s upstream id plus
      that upstream's recorded fingerprint;
    * the step's :attr:`~shop_arena.gen.steps.base.Step.version`.

    Sorting makes the digest invariant under input-list reordering, so
    a step author may shuffle ``inputs`` without invalidating cached
    outputs (spec §5.7).

    Args:
        step: Step whose fingerprint to compute.
        state: Current in-memory state file. Looked up only for
            upstream ``StepInput`` references.
        run_root: Workspace root used to resolve relative
            ``FileInput.path`` values.

    Returns:
        Lowercase hex sha256 digest.

    Raises:
        FileNotFoundError: A declared ``FileInput`` does not exist.
        KeyError: A declared ``StepInput`` references a step id that is
            absent from ``state`` or has no recorded fingerprint yet
            (the runner enforces topological order to avoid this).
    """
    parts: list[tuple[str, str, str]] = []
    for ref in step.inputs:
        if isinstance(ref, FileInput):
            resolved = _resolve_input_path(ref.path, run_root)
            parts.append(("file", str(ref.path), hash_file(resolved)))
        else:
            # Pyright narrows the union: ``ref`` is ``StepInput`` here.
            upstream = state.steps.get(ref.step_id)
            if upstream is None or upstream.fingerprint is None:
                raise KeyError(
                    f"step {step.id!r} depends on upstream {ref.step_id!r} "
                    "which has no recorded fingerprint",
                )
            parts.append(("step", ref.step_id, upstream.fingerprint))

    parts.sort()
    digest = hashlib.sha256()
    for kind, key, value in parts:
        digest.update(kind.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(key.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    digest.update(b"version\x00")
    digest.update(str(step.version).encode("utf-8"))
    digest.update(b"\n")
    return digest.hexdigest()


__all__ = [
    "SCHEMA_VERSION",
    "STATE_DIR_NAME",
    "STATE_FILE_NAME",
    "StateFile",
    "StepStateRecord",
    "compute_fingerprint",
    "hash_file",
    "read_state",
    "state_path",
    "upsert_step_state",
    "write_state",
]
