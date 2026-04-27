"""``write_merge_manifest`` — Phase 1 manifest writer (spec §5.2).

Final step of the multi-seed manual-merge sub-DAG. Records the seed
list, the per-leaf capability-merge conflict log produced upstream by
:class:`shop_gen.manual_merge.capabilities.MergeCapabilitiesStep`, and
the per-step write history (which step produced which file under
``manual/``, plus that step's fingerprint and timestamp). Pure I/O —
no LLM, no network, no env reads.

The manifest schema is closed (``extra="forbid"``) so a corrupted or
out-of-date manifest fails fast under
``Manifest.model_validate_json``. Tests rely on this for the §T2.4
"schema validation" check.

Inputs read at run time:

* ``ShopGenConfig.seeds`` — exposed via ``ctx.config`` — for the
  ``seeds`` field. Stored as POSIX strings so the manifest is
  cross-platform readable.
* ``.shop_gen/stage_cache/capability_conflicts.json`` — the
  per-leaf :class:`~shop_gen.manual_merge.capabilities.MergeConflict`
  log. The file always exists at this point because
  :class:`MergeCapabilitiesStep` is a declared upstream.
* ``.shop_gen/state.json`` — for the per-upstream-step fingerprint
  and ``ts`` recorded by the runner. Upstream steps are guaranteed
  ``FRESH`` here because the runner runs them first.

Step contract (spec §5.7.1):

* ``id``: ``write_merge_manifest``.
* ``phase``: ``manual_merge``.
* ``inputs``: :class:`~shop_gen.steps.base.StepInput` for each of
  ``merge_capabilities``, ``merge_manual_prose``, ``compute_merge_stats``.
* ``outputs``: ``manual/manifest.json``.
* ``depends_on``:
  ``[merge_capabilities, merge_manual_prose, compute_merge_stats]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, Field

from shop_gen.manual_merge.capabilities import MergeConflict
from shop_gen.steps.base import InputRef, StepContext, StepInput
from shop_gen.steps.state import read_state

_PHASE: Final[str] = "manual_merge"
_STEP_ID: Final[str] = "write_merge_manifest"
_STEP_VERSION: Final[int] = 1

_UPSTREAM_CAPABILITIES: Final[str] = "merge_capabilities"
_UPSTREAM_PROSE: Final[str] = "merge_manual_prose"
_UPSTREAM_STATS: Final[str] = "compute_merge_stats"

_OUT_MANIFEST: Final[Path] = Path("manual") / "manifest.json"
_IN_CONFLICTS: Final[Path] = Path(".shop_gen") / "stage_cache" / "capability_conflicts.json"

_PUBLISHED_PATHS: Final[dict[str, str]] = {
    "manual": "manual/manual.md",
    "capabilities": "manual/capabilities.json",
    "stats": "manual/stats.json",
    "manifest": "manual/manifest.json",
}

# Mapping of upstream step id -> the manual/ artifact it produced. The
# manifest's ``write_history`` enumerates one record per (step, output)
# pair so consumers can answer "which upstream produced this file?".
_WRITE_HISTORY_OUTPUTS: Final[tuple[tuple[str, str], ...]] = (
    (_UPSTREAM_CAPABILITIES, "manual/capabilities.json"),
    (_UPSTREAM_PROSE, "manual/manual.md"),
    (_UPSTREAM_STATS, "manual/stats.json"),
)

_MANIFEST_SCHEMA_VERSION: Final[int] = 1


class WriteHistoryEntry(BaseModel):
    """One artifact-write record in :class:`Manifest.write_history`.

    Attributes:
        path: Run-relative POSIX path of the artifact written
            (e.g. ``manual/manual.md``).
        step_id: ``Step.id`` of the upstream step that produced ``path``.
        fingerprint: Hex sha256 fingerprint recorded for ``step_id`` in
            ``state.json``. ``None`` indicates the runner has no
            successful run on record yet (defensive — should not occur
            because the manifest writer's ``depends_on`` forces upstream
            success first).
        ts: ISO-8601 UTC timestamp from ``state.json`` for the upstream
            step's last transition. ``None`` mirrors ``fingerprint``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    step_id: str
    fingerprint: str | None = None
    ts: str | None = None


class Manifest(BaseModel):
    """Closed schema for ``manual/manifest.json``.

    Attributes:
        schema_version: Bumped when the on-disk schema changes
            incompatibly. v0.1 ships ``1``.
        seeds: Per-seed directory paths from
            :class:`~shop_gen.config.ShopGenConfig` rendered as POSIX
            strings. Order mirrors the user's seed order so reruns
            against the same config produce a stable list.
        capability_conflicts: Per-leaf :class:`MergeConflict` log
            forwarded verbatim from
            ``.shop_gen/stage_cache/capability_conflicts.json``.
        write_history: One :class:`WriteHistoryEntry` per Phase 1
            artifact under ``manual/``, sorted by ``path`` for
            deterministic ordering.
        paths: Pointers to the published artifacts the manifest sits
            alongside. Mirrors the layout in spec §4.1.
        synthesized_at: RFC 3339 UTC timestamp (``Z`` suffix) at which
            the manifest was written.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=_MANIFEST_SCHEMA_VERSION)
    seeds: list[str]
    capability_conflicts: list[MergeConflict]
    write_history: list[WriteHistoryEntry]
    paths: dict[str, str]
    synthesized_at: str


class WriteMergeManifestStep:
    """Phase 1 ``write_merge_manifest`` step (spec §5.2).

    Reads the upstream capability-conflict log and the runner's
    ``state.json``, then writes a closed-schema ``manual/manifest.json``
    summarising the multi-seed merge.

    Attributes:
        id: Step id (``write_merge_manifest``).
        phase: ``manual_merge``.
        inputs: One :class:`StepInput` for each Phase 1 upstream step.
        outputs: ``manual/manifest.json``.
        depends_on: ``[merge_capabilities, merge_manual_prose,
            compute_merge_stats]``.
        version: Bumped when the manifest schema or assembly logic
            changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step.

        The step reads the seed list from ``ctx.config`` at run time, so
        no per-seed paths need to be plumbed through the constructor.
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [
            StepInput(step_id=_UPSTREAM_CAPABILITIES),
            StepInput(step_id=_UPSTREAM_PROSE),
            StepInput(step_id=_UPSTREAM_STATS),
        ]
        self.outputs: list[Path] = [_OUT_MANIFEST]
        self.depends_on: list[str] = [
            _UPSTREAM_CAPABILITIES,
            _UPSTREAM_PROSE,
            _UPSTREAM_STATS,
        ]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Assemble and write ``manual/manifest.json``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is ignored — the
                step is fully deterministic.

        Raises:
            FileNotFoundError: The upstream capability-conflict sidecar
                is missing (``merge_capabilities`` did not run, or the
                run workspace was tampered with).
            ValidationError: The conflict sidecar or assembled manifest
                fails closed-schema validation.
        """
        manifest = _build_manifest(ctx)
        out_path = ctx.out_dir / _OUT_MANIFEST
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _build_manifest(ctx: StepContext) -> Manifest:
    """Assemble the :class:`Manifest` payload for ``ctx``.

    Pulled out of :meth:`WriteMergeManifestStep.run` so unit tests can
    exercise the assembly without re-running the writer.
    """
    conflicts = _load_conflicts(ctx.out_dir / _IN_CONFLICTS)
    write_history = _build_write_history(ctx.out_dir)
    seeds = [seed.as_posix() for seed in ctx.config.seeds]
    return Manifest(
        seeds=seeds,
        capability_conflicts=conflicts,
        write_history=write_history,
        paths=dict(_PUBLISHED_PATHS),
        synthesized_at=_utc_now_iso(),
    )


def _load_conflicts(path: Path) -> list[MergeConflict]:
    """Read the upstream capability-conflict sidecar.

    Args:
        path: Absolute path to
            ``.shop_gen/stage_cache/capability_conflicts.json``.

    Returns:
        List of :class:`MergeConflict` records (possibly empty).

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ValueError: The file is not valid JSON or is not a JSON array.
        pydantic.ValidationError: A record fails closed-schema validation.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"capability-conflict sidecar not found at {path}; run merge_capabilities first",
        )
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"capability-conflict sidecar at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, list):
        raise ValueError(
            f"capability-conflict sidecar at {path} must be a JSON array, got {type(raw).__name__}",
        )
    items = cast("list[Any]", raw)
    return [MergeConflict.model_validate(item) for item in items]


def _build_write_history(out_dir: Path) -> list[WriteHistoryEntry]:
    """Build the ``write_history`` list from the runner's ``state.json``.

    Each record pairs a known Phase 1 artifact (``manual/manual.md`` /
    ``manual/capabilities.json`` / ``manual/stats.json``) with the
    upstream step that produced it, plus the fingerprint and timestamp
    the runner stamped after that step finished. Sorted by ``path`` so
    the on-disk manifest is stable across reruns when the upstream
    state has not changed.
    """
    state = read_state(out_dir)
    entries = [
        WriteHistoryEntry(
            path=path,
            step_id=step_id,
            fingerprint=record.fingerprint if (record := state.steps.get(step_id)) else None,
            ts=record.ts if (record := state.steps.get(step_id)) else None,
        )
        for step_id, path in _WRITE_HISTORY_OUTPUTS
    ]
    return sorted(entries, key=lambda e: e.path)


def _utc_now_iso() -> str:
    """Return ``datetime.now(UTC)`` as an RFC 3339 ``Z`` timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "Manifest",
    "WriteHistoryEntry",
    "WriteMergeManifestStep",
]
