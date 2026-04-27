"""Unit tests for :mod:`shop_gen.manual_merge.manifest`.

Covers the T2.4 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``WriteMergeManifestStep`` honours the step protocol — declared id,
  phase, ``StepInput`` upstreams, and output path match the spec.
* ``manual/manifest.json`` is a valid :class:`Manifest` document with
  the expected seed list, capability conflicts, write history, and
  pointer paths.
* Schema validation rejects malformed conflict sidecars and missing
  upstream artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shop_gen.config import ShopGenConfig
from shop_gen.manual_merge.capabilities import MergeConflict
from shop_gen.manual_merge.manifest import (
    Manifest,
    WriteHistoryEntry,
    WriteMergeManifestStep,
)
from shop_gen.steps.base import Step, StepContext, StepInput
from shop_gen.steps.state import StateFile, StepStateRecord, StepStatus, write_state

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _seed_dir(tmp_path: Path, name: str) -> Path:
    """Create a minimal seed directory tree (the manifest only stores the path)."""
    seed = tmp_path / name
    seed.mkdir()
    return seed


def _write_conflicts(out_dir: Path, conflicts: list[dict[str, object]]) -> Path:
    """Pre-populate the upstream capability-conflict sidecar."""
    path = out_dir / ".shop_gen" / "stage_cache" / "capability_conflicts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(conflicts), encoding="utf-8")
    return path


def _seed_state(out_dir: Path) -> StateFile:
    """Pre-populate ``state.json`` with FRESH records for the upstream Phase 1 steps."""
    state = StateFile(
        steps={
            "merge_capabilities": StepStateRecord(
                id="merge_capabilities",
                phase="manual_merge",
                status=StepStatus.FRESH,
                fingerprint="cap-fp",
                ts="2024-01-01T00:00:00Z",
            ),
            "merge_manual_prose": StepStateRecord(
                id="merge_manual_prose",
                phase="manual_merge",
                status=StepStatus.FRESH,
                fingerprint="prose-fp",
                ts="2024-01-01T00:01:00Z",
            ),
            "compute_merge_stats": StepStateRecord(
                id="compute_merge_stats",
                phase="manual_merge",
                status=StepStatus.FRESH,
                fingerprint="stats-fp",
                ts="2024-01-01T00:02:00Z",
            ),
        },
    )
    write_state(out_dir, state)
    return state


# --------------------------------------------------------------------------- #
# Step contract
# --------------------------------------------------------------------------- #


def test_step_satisfies_step_protocol() -> None:
    step = WriteMergeManifestStep()
    assert isinstance(step, Step)
    assert step.id == "write_merge_manifest"
    assert step.phase == "manual_merge"
    assert step.depends_on == [
        "merge_capabilities",
        "merge_manual_prose",
        "compute_merge_stats",
    ]
    assert step.outputs == [Path("manual") / "manifest.json"]
    upstream_ids = [ref.step_id for ref in step.inputs if isinstance(ref, StepInput)]
    assert upstream_ids == [
        "merge_capabilities",
        "merge_manual_prose",
        "compute_merge_stats",
    ]


# --------------------------------------------------------------------------- #
# End-to-end run
# --------------------------------------------------------------------------- #


def test_step_run_writes_manifest_with_expected_fields(tmp_path: Path) -> None:
    """End-to-end: step assembles a closed-schema manifest from upstream artifacts."""
    seed_a = _seed_dir(tmp_path, "seed_a")
    seed_b = _seed_dir(tmp_path, "seed_b")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    conflict_payload = [
        {
            "path": "cart.has_promo_input",
            "rule": "bool_union",
            "seed_values": {"seed_0": True, "seed_1": False},
            "chosen_value": True,
            "tiebreak": None,
        },
    ]
    _write_conflicts(out_dir, conflict_payload)
    _seed_state(out_dir)

    cfg = ShopGenConfig(seeds=[seed_a, seed_b], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    WriteMergeManifestStep().run(ctx)

    manifest_path = out_dir / "manual" / "manifest.json"
    assert manifest_path.is_file()

    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    assert manifest.schema_version == 1
    assert manifest.seeds == [seed_a.as_posix(), seed_b.as_posix()]
    assert len(manifest.capability_conflicts) == 1
    assert manifest.capability_conflicts[0].path == "cart.has_promo_input"
    assert manifest.capability_conflicts[0].chosen_value is True
    assert manifest.paths == {
        "manual": "manual/manual.md",
        "capabilities": "manual/capabilities.json",
        "stats": "manual/stats.json",
        "manifest": "manual/manifest.json",
    }
    # Synthesized timestamp is RFC 3339 UTC with Z suffix.
    assert manifest.synthesized_at.endswith("Z")


def test_write_history_pairs_each_artifact_with_its_upstream(tmp_path: Path) -> None:
    """Write history records one entry per Phase 1 artifact, sorted by path."""
    seed = _seed_dir(tmp_path, "seed_a")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _write_conflicts(out_dir, [])
    _seed_state(out_dir)

    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)
    WriteMergeManifestStep().run(ctx)

    manifest = Manifest.model_validate_json(
        (out_dir / "manual" / "manifest.json").read_text(encoding="utf-8"),
    )

    # Sorted by path, so capabilities.json comes first, then manual.md, then stats.json.
    history = manifest.write_history
    assert [entry.path for entry in history] == [
        "manual/capabilities.json",
        "manual/manual.md",
        "manual/stats.json",
    ]
    by_path = {entry.path: entry for entry in history}
    assert by_path["manual/capabilities.json"].step_id == "merge_capabilities"
    assert by_path["manual/capabilities.json"].fingerprint == "cap-fp"
    assert by_path["manual/capabilities.json"].ts == "2024-01-01T00:00:00Z"
    assert by_path["manual/manual.md"].step_id == "merge_manual_prose"
    assert by_path["manual/manual.md"].fingerprint == "prose-fp"
    assert by_path["manual/stats.json"].step_id == "compute_merge_stats"
    assert by_path["manual/stats.json"].fingerprint == "stats-fp"


def test_write_history_handles_missing_state_records(tmp_path: Path) -> None:
    """When state.json has no record for an upstream, fingerprint/ts collapse to None."""
    seed = _seed_dir(tmp_path, "seed_a")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _write_conflicts(out_dir, [])
    # Deliberately do not seed state.json — defensive path.

    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)
    WriteMergeManifestStep().run(ctx)

    manifest = Manifest.model_validate_json(
        (out_dir / "manual" / "manifest.json").read_text(encoding="utf-8"),
    )
    for entry in manifest.write_history:
        assert entry.fingerprint is None
        assert entry.ts is None


def test_step_run_requires_capability_conflict_sidecar(tmp_path: Path) -> None:
    """Step refuses to run when ``merge_capabilities`` hasn't written its sidecar."""
    seed = _seed_dir(tmp_path, "seed_a")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)
    with pytest.raises(FileNotFoundError, match="merge_capabilities first"):
        WriteMergeManifestStep().run(ctx)


def test_step_run_rejects_malformed_conflicts_json(tmp_path: Path) -> None:
    """Malformed JSON in the conflict sidecar surfaces as a ValueError."""
    seed = _seed_dir(tmp_path, "seed_a")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    conflicts_path = out_dir / ".shop_gen" / "stage_cache" / "capability_conflicts.json"
    conflicts_path.parent.mkdir(parents=True, exist_ok=True)
    conflicts_path.write_text("{not valid json", encoding="utf-8")

    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)
    with pytest.raises(ValueError, match="not valid JSON"):
        WriteMergeManifestStep().run(ctx)


def test_step_run_rejects_non_array_conflicts_payload(tmp_path: Path) -> None:
    """Conflict sidecar must be a JSON array (matches MergeCapabilitiesStep output)."""
    seed = _seed_dir(tmp_path, "seed_a")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _write_conflicts(out_dir, [])  # ensures the dir exists.
    (out_dir / ".shop_gen" / "stage_cache" / "capability_conflicts.json").write_text(
        json.dumps({"not": "an array"}),
        encoding="utf-8",
    )

    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)
    with pytest.raises(ValueError, match="JSON array"):
        WriteMergeManifestStep().run(ctx)


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #


def test_manifest_schema_rejects_unknown_top_level_field() -> None:
    """The closed schema rejects extra top-level fields on read."""
    payload = {
        "schema_version": 1,
        "seeds": [],
        "capability_conflicts": [],
        "write_history": [],
        "paths": {},
        "synthesized_at": "2024-01-01T00:00:00Z",
        "unknown": "boom",
    }
    with pytest.raises(ValueError, match="extra"):
        Manifest.model_validate(payload)


def test_write_history_entry_schema_is_closed() -> None:
    """``WriteHistoryEntry`` rejects unexpected fields."""
    payload = {
        "path": "manual/manual.md",
        "step_id": "merge_manual_prose",
        "fingerprint": "fp",
        "ts": "2024-01-01T00:00:00Z",
        "extra": "boom",
    }
    with pytest.raises(ValueError, match="extra"):
        WriteHistoryEntry.model_validate(payload)


def test_manifest_round_trip_preserves_conflicts(tmp_path: Path) -> None:
    """Conflict objects survive JSON round-trip via the closed schema."""
    seed = _seed_dir(tmp_path, "seed_a")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    conflict = MergeConflict(
        path="shop.descriptor",
        rule="llm_descriptor",
        seed_values={"seed_0": "casual storefront", "seed_1": "premium storefront"},
        chosen_value="casual premium storefront",
        tiebreak="llm",
    )
    _write_conflicts(out_dir, [conflict.model_dump(mode="json")])
    _seed_state(out_dir)

    cfg = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)
    WriteMergeManifestStep().run(ctx)

    manifest = Manifest.model_validate_json(
        (out_dir / "manual" / "manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest.capability_conflicts == [conflict]
