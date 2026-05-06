"""Seed immutability protocol check (spec `seed_immutability.md`).

The plan-exec harness copies a caller-supplied `artifact_seed_dir` into
`run_dir/artifact/` at workspace creation time and treats those files as
"stable" (immutable during a run; spec
`docs/specs/harness/plan_exec_loop.md` §5.4). This module owns the
deterministic post-iteration check that catches any mutation, deletion,
or extension of files inside the seeded subtree.

* `SeedManifest` — frozen `{relpath: sha256}` fingerprint plus the set
  of top-level seeded entries.
* `snapshot_seed(artifact_dir, seeded_roots)` — build a manifest by
  walking the seeded subtree under `artifact_dir`. Rejects symlinks.
* `check_seed(manifest, artifact_dir, *, iter_id)` — diff the manifest
  against the current state of the seeded subtree and return a
  `ProtocolCheckResult` whose violations encode `seed_mutated:`,
  `seed_deleted:`, and `seed_extended:` deviations.

`SeedManifest.to_json` / `SeedManifest.from_json` round-trip the
fingerprint to a plain JSON-friendly dict so the manifest can be
persisted to `<run_dir>/.harness/seed_manifest.json` and loaded back on
resume (`docs/specs/harness/resume.md` §5.1).

Plan-domain concerns (`plan.md` invariants) live in `harness.plan.protocol`
and are kept independent of seed checks.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from harness.trajectory import ProtocolCheckResult


class SeedError(Exception):
    """Raised when the seed manifest cannot be built (e.g. symlink in seed)."""


@dataclass(frozen=True, slots=True)
class SeedManifest:
    """Frozen fingerprint of files copied from `artifact_seed_dir`.

    Attributes:
        files: Mapping of POSIX relpaths under `run_dir/artifact/` to
            their sha256 hex digests, captured at workspace creation
            time. Keys cover only files inside the seeded subtree.
        seeded_roots: Top-level entry names copied from
            `artifact_seed_dir`. Bounds the post-iteration scan: only
            paths whose first segment is in this set are inspected.
    """

    files: Mapping[PurePosixPath, str]
    seeded_roots: frozenset[PurePosixPath]

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict representation of this manifest.

        The serialised form is stable across runs: `seeded_roots` and
        `files` keys are sorted by POSIX relpath so the on-disk bytes
        for a given seed are deterministic.
        """
        return {
            "seeded_roots": sorted(p.as_posix() for p in self.seeded_roots),
            "files": {p.as_posix(): self.files[p] for p in sorted(self.files)},
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> SeedManifest:
        """Rebuild a `SeedManifest` from its `to_json` representation.

        Args:
            payload: Mapping with ``seeded_roots`` (list of POSIX
                relpaths) and ``files`` (mapping of POSIX relpath to
                sha256 hex digest).

        Returns:
            A `SeedManifest` equivalent to the one originally serialised.

        Raises:
            SeedError: If required keys are missing or values have the
                wrong shape.
        """
        try:
            roots_raw = payload["seeded_roots"]
            files_raw = payload["files"]
        except KeyError as exc:
            raise SeedError(f"seed manifest missing key: {exc.args[0]!r}") from exc
        if not isinstance(roots_raw, list) or not isinstance(files_raw, dict):
            raise SeedError("seed manifest has wrong shape (expected list + dict)")
        seeded_roots = frozenset(PurePosixPath(r) for r in roots_raw)
        files: dict[PurePosixPath, str] = {}
        for rel, digest in files_raw.items():
            if not isinstance(rel, str) or not isinstance(digest, str):
                raise SeedError("seed manifest entries must be string→string")
            files[PurePosixPath(rel)] = digest
        return cls(files=files, seeded_roots=seeded_roots)


def snapshot_seed(
    artifact_dir: Path,
    seeded_roots: frozenset[PurePosixPath],
) -> SeedManifest:
    """Build a `SeedManifest` by hashing every regular file under the seeded subtree.

    Walks `artifact_dir` restricted to the top-level entries named in
    `seeded_roots`. Each top-level entry is descended recursively; every
    regular file's sha256 is captured under its POSIX relpath. Symlinks
    encountered anywhere in the seeded subtree (including the top-level
    entries themselves) cause this function to raise — symlink expansion
    is incompatible with stable fingerprinting (spec §5.2, alternative C).

    Args:
        artifact_dir: Path to `run_dir/artifact/`.
        seeded_roots: Top-level entry names that came from
            `artifact_seed_dir`. Must reference real entries inside
            `artifact_dir`; missing entries cause this function to raise.

    Returns:
        A `SeedManifest` ready to feed `check_seed`.

    Raises:
        SeedError: If a symlink is encountered, or a `seeded_roots` entry
            is missing from `artifact_dir`.
    """
    files: dict[PurePosixPath, str] = {}
    for root in sorted(seeded_roots):
        root_path = artifact_dir / root.as_posix()
        if not root_path.exists():
            raise SeedError(f"seeded root missing from artifact_dir: {root.as_posix()}")
        if root_path.is_symlink():
            raise SeedError(f"symlink in seed not supported: {root.as_posix()}")
        if root_path.is_dir():
            _hash_dir(root_path, root, files)
        else:
            files[root] = _hash_file(root_path)
    return SeedManifest(files=files, seeded_roots=seeded_roots)


def check_seed(
    manifest: SeedManifest,
    artifact_dir: Path,
    *,
    iter_id: str,
) -> ProtocolCheckResult:
    """Diff the seeded subtree under `artifact_dir` against `manifest`.

    Returns a `ProtocolCheckResult` whose `violations` is one entry per
    deviation, using the stable, grep-friendly prefixes:

    * ``seed_mutated: <relpath>`` — relpath in both, sha256 differs.
    * ``seed_deleted: <relpath>`` — relpath in manifest, missing now.
    * ``seed_extended: <relpath>`` — relpath present now but absent from
      the manifest, with first segment in `manifest.seeded_roots`.

    Symlinks newly introduced inside the seeded subtree are reported as
    ``seed_extended:`` violations (a symlink is an extension of state
    that was not in the manifest). Violation strings are sorted by
    relpath within each category for stable output.

    Args:
        manifest: Manifest captured at workspace creation time.
        artifact_dir: Path to `run_dir/artifact/`.
        iter_id: Iteration id this result is attributed to (e.g.
            ``plan`` or ``exec-0001``).

    Returns:
        A `ProtocolCheckResult`. `passed` is true iff no violations were
        detected.
    """
    current = _walk_seeded_subtree(artifact_dir, manifest.seeded_roots)
    manifest_files = manifest.files

    mutated: list[str] = []
    deleted: list[str] = []
    extended: list[str] = []

    for relpath, expected in manifest_files.items():
        actual = current.get(relpath)
        if actual is None:
            deleted.append(relpath.as_posix())
        elif actual != expected:
            mutated.append(relpath.as_posix())

    for relpath in current:
        if relpath not in manifest_files:
            extended.append(relpath.as_posix())

    violations: list[str] = []
    violations.extend(f"seed_mutated: {p}" for p in sorted(mutated))
    violations.extend(f"seed_deleted: {p}" for p in sorted(deleted))
    violations.extend(f"seed_extended: {p}" for p in sorted(extended))
    return ProtocolCheckResult(
        iter_id=iter_id,
        passed=not violations,
        violations=tuple(violations),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_READ_CHUNK = 1 << 20  # 1 MiB


def _hash_file(path: Path) -> str:
    """Return the sha256 hex digest of `path`, streaming in 1 MiB chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_READ_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _hash_dir(
    dir_path: Path,
    rel_root: PurePosixPath,
    files: dict[PurePosixPath, str],
) -> None:
    """Recursively hash every regular file under `dir_path` into `files`.

    Raises `SeedError` on any symlink encountered. Sorted iteration keeps
    error messages deterministic.
    """
    for entry in sorted(dir_path.iterdir(), key=lambda p: p.name):
        rel = rel_root / entry.name
        if entry.is_symlink():
            raise SeedError(f"symlink in seed not supported: {rel.as_posix()}")
        if entry.is_dir():
            _hash_dir(entry, rel, files)
        elif entry.is_file():
            files[rel] = _hash_file(entry)
        else:
            raise SeedError(f"unsupported seed entry kind: {rel.as_posix()}")


def _walk_seeded_subtree(
    artifact_dir: Path,
    seeded_roots: frozenset[PurePosixPath],
) -> dict[PurePosixPath, str]:
    """Walk the seeded subtree under `artifact_dir`, hashing every regular file.

    Unlike `_hash_dir`, this helper tolerates roots that have been
    deleted (those simply contribute nothing) and reports newly-appeared
    symlinks as plain entries in the output — `check_seed` translates
    them into `seed_extended:` violations rather than raising. Files
    that fail to read (e.g. permission errors) are skipped; the absence
    is reflected as `seed_deleted:` in the diff.
    """
    found: dict[PurePosixPath, str] = {}
    for root in seeded_roots:
        root_path = artifact_dir / root.as_posix()
        if root_path.is_symlink() or not root_path.exists():
            # Symlink at root: treat the link itself as an extended entry
            # so the caller sees the deviation. Missing root: nothing to
            # record (the manifest entries become `seed_deleted:`).
            if root_path.is_symlink():
                found[root] = ""  # value unused; presence triggers `seed_extended:`
            continue
        if root_path.is_dir():
            _walk_dir(root_path, root, found)
        elif root_path.is_file():
            found[root] = _hash_file(root_path)
    return found


def _walk_dir(
    dir_path: Path,
    rel_root: PurePosixPath,
    found: dict[PurePosixPath, str],
) -> None:
    """Walk a single seeded-root directory, populating `found` with file hashes."""
    for entry in dir_path.iterdir():
        rel = rel_root / entry.name
        if entry.is_symlink():
            # Record presence so `check_seed` can flag it as `seed_extended:`.
            found[rel] = ""
            continue
        if entry.is_dir():
            _walk_dir(entry, rel, found)
        elif entry.is_file():
            found[rel] = _hash_file(entry)
