"""Tests for `harness.seed` (spec `seed_immutability.md` §M1)."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

import pytest

from harness.seed import SeedError, SeedManifest, check_seed, snapshot_seed

_ITER_ID = "exec-0001"


# ---------------------------------------------------------------------------
# snapshot_seed
# ---------------------------------------------------------------------------


def test_snapshot_seed_hashes_every_regular_file(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    (artifact / "prefetch" / "nested").mkdir(parents=True)
    (artifact / "prefetch" / "top.txt").write_text("hello", encoding="utf-8")
    (artifact / "prefetch" / "nested" / "deep.bin").write_bytes(b"\x00\x01")
    (artifact / "outside.md").write_text("not seeded", encoding="utf-8")

    manifest = snapshot_seed(artifact, frozenset({PurePosixPath("prefetch")}))

    rel_top = PurePosixPath("prefetch/top.txt")
    rel_deep = PurePosixPath("prefetch/nested/deep.bin")
    assert set(manifest.files) == {rel_top, rel_deep}
    # Hashes are non-empty 64-char hex strings; spot-check by comparison.
    assert manifest.files[rel_top] == _sha256(b"hello")
    assert manifest.files[rel_deep] == _sha256(b"\x00\x01")
    assert manifest.seeded_roots == frozenset({PurePosixPath("prefetch")})


def test_snapshot_seed_top_level_file_is_recorded_directly(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "policy.md").write_text("be nice", encoding="utf-8")

    manifest = snapshot_seed(artifact, frozenset({PurePosixPath("policy.md")}))

    assert set(manifest.files) == {PurePosixPath("policy.md")}


def test_snapshot_seed_with_empty_roots_yields_empty_manifest(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "drop.txt").write_text("x", encoding="utf-8")

    manifest = snapshot_seed(artifact, frozenset())

    assert manifest.files == {}
    assert manifest.seeded_roots == frozenset()


def test_snapshot_seed_rejects_symlink_at_top_level(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    target = tmp_path / "real"
    target.mkdir()
    (target / "data.bin").write_bytes(b"data")
    (artifact / "prefetch").symlink_to(target)

    with pytest.raises(SeedError, match="symlink in seed not supported"):
        snapshot_seed(artifact, frozenset({PurePosixPath("prefetch")}))


def test_snapshot_seed_rejects_nested_symlink(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    seeded = artifact / "prefetch"
    seeded.mkdir(parents=True)
    target = tmp_path / "leak.txt"
    target.write_text("secret", encoding="utf-8")
    (seeded / "shortcut").symlink_to(target)

    with pytest.raises(SeedError, match="symlink in seed not supported"):
        snapshot_seed(artifact, frozenset({PurePosixPath("prefetch")}))


def test_snapshot_seed_raises_when_seeded_root_missing(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()

    with pytest.raises(SeedError, match="seeded root missing"):
        snapshot_seed(artifact, frozenset({PurePosixPath("prefetch")}))


# ---------------------------------------------------------------------------
# check_seed — clean pass cases
# ---------------------------------------------------------------------------


def test_check_seed_passes_when_subtree_unchanged(tmp_path: Path) -> None:
    artifact, manifest = _seed_with_two_files(tmp_path)

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    assert result.passed is True
    assert result.violations == ()
    assert result.iter_id == _ITER_ID


def test_check_seed_ignores_writes_outside_seeded_subtree(tmp_path: Path) -> None:
    artifact, manifest = _seed_with_two_files(tmp_path)
    # Write under a non-seeded path under artifact/.
    (artifact / "evidence").mkdir()
    (artifact / "evidence" / "screenshot.png").write_bytes(b"\x89PNG")

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    assert result.passed is True


def test_check_seed_with_no_seeded_roots_is_a_noop(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    manifest = SeedManifest(files={}, seeded_roots=frozenset())
    (artifact / "anything").write_text("free reign", encoding="utf-8")

    result = check_seed(manifest, artifact, iter_id="plan")

    assert result.passed is True


# ---------------------------------------------------------------------------
# check_seed — violation categories
# ---------------------------------------------------------------------------


def test_check_seed_reports_mutated_file(tmp_path: Path) -> None:
    artifact, manifest = _seed_with_two_files(tmp_path)
    (artifact / "prefetch" / "top.txt").write_text("MUTATED", encoding="utf-8")

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    assert result.passed is False
    assert "seed_mutated: prefetch/top.txt" in result.violations


def test_check_seed_reports_deleted_file(tmp_path: Path) -> None:
    artifact, manifest = _seed_with_two_files(tmp_path)
    (artifact / "prefetch" / "top.txt").unlink()

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    assert result.passed is False
    assert "seed_deleted: prefetch/top.txt" in result.violations


def test_check_seed_reports_extended_path(tmp_path: Path) -> None:
    artifact, manifest = _seed_with_two_files(tmp_path)
    (artifact / "prefetch" / "_planner").mkdir()
    (artifact / "prefetch" / "_planner" / "snapshot.md").write_text("intruder", encoding="utf-8")

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    assert result.passed is False
    assert "seed_extended: prefetch/_planner/snapshot.md" in result.violations


def test_check_seed_aggregates_all_three_categories(tmp_path: Path) -> None:
    artifact, manifest = _seed_with_two_files(tmp_path)
    (artifact / "prefetch" / "top.txt").write_text("mutated", encoding="utf-8")
    (artifact / "prefetch" / "nested" / "deep.bin").unlink()
    (artifact / "prefetch" / "extra.md").write_text("new", encoding="utf-8")

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    assert result.passed is False
    assert any(v.startswith("seed_mutated: ") for v in result.violations)
    assert any(v.startswith("seed_deleted: ") for v in result.violations)
    assert any(v.startswith("seed_extended: ") for v in result.violations)


def test_check_seed_violations_sorted_within_category(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    seeded = artifact / "prefetch"
    seeded.mkdir(parents=True)
    (seeded / "a.txt").write_text("a", encoding="utf-8")
    (seeded / "b.txt").write_text("b", encoding="utf-8")
    (seeded / "c.txt").write_text("c", encoding="utf-8")
    manifest = snapshot_seed(artifact, frozenset({PurePosixPath("prefetch")}))
    # Mutate in a non-alphabetic order to verify sorted output.
    (seeded / "c.txt").write_text("CHANGED", encoding="utf-8")
    (seeded / "a.txt").write_text("CHANGED", encoding="utf-8")
    (seeded / "b.txt").write_text("CHANGED", encoding="utf-8")

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    mutated = [v for v in result.violations if v.startswith("seed_mutated: ")]
    assert mutated == [
        "seed_mutated: prefetch/a.txt",
        "seed_mutated: prefetch/b.txt",
        "seed_mutated: prefetch/c.txt",
    ]


def test_check_seed_does_not_descend_into_non_seeded_top_levels(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    seeded = artifact / "prefetch"
    seeded.mkdir(parents=True)
    (seeded / "top.txt").write_text("hello", encoding="utf-8")
    manifest = snapshot_seed(artifact, frozenset({PurePosixPath("prefetch")}))
    # Another directory with the same nested layout but different content
    # under a non-seeded root must be invisible to the check.
    other = artifact / "evidence"
    other.mkdir()
    (other / "top.txt").write_text("does not matter", encoding="utf-8")

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    assert result.passed is True


def test_check_seed_flags_symlink_introduced_post_seed(tmp_path: Path) -> None:
    artifact, manifest = _seed_with_two_files(tmp_path)
    target = tmp_path / "external.txt"
    target.write_text("oops", encoding="utf-8")
    # Symlink that did not exist at seed time -> extension.
    (artifact / "prefetch" / "shortcut").symlink_to(target)

    result = check_seed(manifest, artifact, iter_id=_ITER_ID)

    assert result.passed is False
    assert "seed_extended: prefetch/shortcut" in result.violations


# ---------------------------------------------------------------------------
# SeedManifest.to_json / from_json (resume.md §5.1 round-trip)
# ---------------------------------------------------------------------------


def test_seed_manifest_round_trips_through_json(tmp_path: Path) -> None:
    _, manifest = _seed_with_two_files(tmp_path)

    payload = manifest.to_json()
    restored = SeedManifest.from_json(payload)

    assert restored.files == dict(manifest.files)
    assert restored.seeded_roots == manifest.seeded_roots


def test_seed_manifest_to_json_is_sorted_for_determinism(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    (artifact / "b").mkdir(parents=True)
    (artifact / "a").mkdir(parents=True)
    (artifact / "b" / "second.txt").write_text("2", encoding="utf-8")
    (artifact / "a" / "first.txt").write_text("1", encoding="utf-8")
    manifest = snapshot_seed(
        artifact,
        frozenset({PurePosixPath("a"), PurePosixPath("b")}),
    )

    payload = manifest.to_json()

    assert payload["seeded_roots"] == ["a", "b"]
    assert list(payload["files"].keys()) == ["a/first.txt", "b/second.txt"]


def test_seed_manifest_from_json_rejects_missing_keys() -> None:
    with pytest.raises(SeedError, match="missing key"):
        SeedManifest.from_json({"seeded_roots": []})


def test_seed_manifest_from_json_rejects_wrong_value_types() -> None:
    with pytest.raises(SeedError):
        SeedManifest.from_json({"seeded_roots": "not-a-list", "files": {}})

    with pytest.raises(SeedError, match="string"):
        SeedManifest.from_json({"seeded_roots": [], "files": {"a.txt": 123}})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_with_two_files(tmp_path: Path) -> tuple[Path, SeedManifest]:
    """Build an `artifact_dir` with two files inside one seeded root."""
    artifact = tmp_path / "artifact"
    seeded = artifact / "prefetch"
    (seeded / "nested").mkdir(parents=True)
    (seeded / "top.txt").write_text("hello", encoding="utf-8")
    (seeded / "nested" / "deep.bin").write_bytes(b"\x00\x01")
    manifest = snapshot_seed(artifact, frozenset({PurePosixPath("prefetch")}))
    return artifact, manifest


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
