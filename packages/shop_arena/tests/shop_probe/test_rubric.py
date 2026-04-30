"""Tests for `shop_probe.rubric` (T1.3 acceptance — spec §5.3, §5.8).

Covers:

* :class:`RubricEntry` round-trip and unknown-field rejection.
* Out-of-range ``weight`` rejection.
* :func:`load_rubric` deterministic content hash over a fixture YAML.
* Loader-level error handling for malformed YAML and bad shapes.
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from shop_probe.rubric import (
    Rubric,
    RubricEntry,
    RubricLoadError,
    compute_content_hash,
    load_rubric,
    load_rubric_bytes,
)

# --------------------------------------------------------------------------- #
# Fixture YAML — frozen here so the hash assertion is deterministic.
# --------------------------------------------------------------------------- #


_FIXTURE_YAML: bytes = textwrap.dedent(
    """\
    version: v1-test
    entries:
      - id: product.gallery.thumbnails
        type: probe
        category: product
        level: modern
        weight: 2
        probe: probes.product.gallery_has_thumbnails
        description: PDP gallery exposes a thumbnail strip that swaps the main image.
        authenticated: false
        transactional: false
      - id: collection.filters.sidebar
        type: probe
        category: collection
        level: core
        weight: 3
        probe: probes.collection.has_sidebar_filters
        description: Collection page renders a sidebar with at least one facet.
        authenticated: false
        transactional: false
    """
).encode("utf-8")

_FIXTURE_HASH: str = hashlib.sha256(_FIXTURE_YAML).hexdigest()


# --------------------------------------------------------------------------- #
# RubricEntry — round-trip + unknown-field rejection
# --------------------------------------------------------------------------- #


def _entry_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "product.gallery.thumbnails",
        "type": "probe",
        "category": "product",
        "level": "modern",
        "weight": 2,
        "probe": "probes.product.gallery_has_thumbnails",
        "description": "PDP gallery exposes a thumbnail strip.",
        "authenticated": False,
        "transactional": False,
        "capture_judge": None,
    }
    base.update(overrides)
    return base


def _capture_judge_entry_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "homepage.hero.coherent",
        "type": "capture_judge",
        "category": "homepage",
        "level": "advanced",
        "weight": 2,
        "probe": None,
        "description": "Hero is visually coherent.",
        "authenticated": False,
        "transactional": False,
        "capture_judge": {
            "judge_prompt": "Is the hero visually coherent?",
            "pages": ["home"],
        },
    }
    base.update(overrides)
    return base


def _scale_entry_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "site.scale",
        "type": "scale",
        "description": "Per-page scale + catalog counts.",
    }
    base.update(overrides)
    return base


def test_rubric_entry_round_trip() -> None:
    raw = _entry_dict()
    entry = RubricEntry.model_validate(raw)
    assert entry.model_dump() == raw
    # JSON round-trip too — confirms no exotic default coercion.
    assert RubricEntry.model_validate_json(entry.model_dump_json()) == entry


def test_rubric_entry_rejects_unknown_field() -> None:
    raw = _entry_dict(extra_field="nope")
    with pytest.raises(ValidationError, match="extra_field"):
        RubricEntry.model_validate(raw)


@pytest.mark.parametrize("weight", [0, -1, 4, 99])
def test_rubric_entry_rejects_out_of_range_weight(weight: int) -> None:
    raw = _entry_dict(weight=weight)
    with pytest.raises(ValidationError, match="weight"):
        RubricEntry.model_validate(raw)


def test_rubric_entry_rejects_unknown_level() -> None:
    raw = _entry_dict(level="legendary")
    with pytest.raises(ValidationError):
        RubricEntry.model_validate(raw)


def test_rubric_entry_rejects_unknown_category() -> None:
    raw = _entry_dict(category="not-a-real-category")
    with pytest.raises(ValidationError):
        RubricEntry.model_validate(raw)


# --------------------------------------------------------------------------- #
# RubricEntry — per-type contract
# --------------------------------------------------------------------------- #


def test_probe_entry_requires_probe_field() -> None:
    raw = _entry_dict(probe=None)
    with pytest.raises(ValidationError, match="requires a 'probe' dotted reference"):
        RubricEntry.model_validate(raw)


def test_probe_entry_rejects_capture_judge_block() -> None:
    raw = _entry_dict(
        capture_judge={"judge_prompt": "x", "pages": ["home"]},
    )
    with pytest.raises(ValidationError, match="must not set 'capture_judge'"):
        RubricEntry.model_validate(raw)


def test_capture_judge_entry_round_trip() -> None:
    raw = _capture_judge_entry_dict()
    entry = RubricEntry.model_validate(raw)
    assert entry.type == "capture_judge"
    assert entry.capture_judge is not None
    assert entry.capture_judge.pages == ("home",)


def test_capture_judge_entry_requires_capture_judge_block() -> None:
    raw = _capture_judge_entry_dict(capture_judge=None)
    with pytest.raises(ValidationError, match="requires an inline 'capture_judge' block"):
        RubricEntry.model_validate(raw)


def test_capture_judge_entry_rejects_probe_field() -> None:
    raw = _capture_judge_entry_dict(probe="probes.something")
    with pytest.raises(ValidationError, match="must not set 'probe'"):
        RubricEntry.model_validate(raw)


def test_scale_entry_round_trip() -> None:
    raw = _scale_entry_dict()
    entry = RubricEntry.model_validate(raw)
    assert entry.type == "scale"
    assert entry.category is None
    assert entry.level is None
    assert entry.weight is None
    assert entry.probe is None
    assert entry.capture_judge is None


@pytest.mark.parametrize(
    "field, value",
    [
        ("category", "product"),
        ("level", "core"),
        ("weight", 2),
        ("probe", "probes.x"),
        ("authenticated", False),
        ("transactional", False),
    ],
)
def test_scale_entry_rejects_disallowed_fields(field: str, value: object) -> None:
    raw = _scale_entry_dict(**{field: value})
    with pytest.raises(ValidationError, match=f"must not set '{field}'"):
        RubricEntry.model_validate(raw)


def test_scale_entry_rejects_capture_judge_block() -> None:
    raw = _scale_entry_dict(
        capture_judge={"judge_prompt": "x", "pages": ["home"]},
    )
    with pytest.raises(ValidationError, match="must not set 'capture_judge'"):
        RubricEntry.model_validate(raw)


def test_rubric_rejects_two_scale_entries() -> None:
    a = RubricEntry.model_validate(_scale_entry_dict(id="site.scale.a"))
    b = RubricEntry.model_validate(_scale_entry_dict(id="site.scale.b"))
    with pytest.raises(ValidationError, match="at most one type='scale' entry"):
        Rubric(version="v1", content_hash="0" * 64, entries=(a, b))


# --------------------------------------------------------------------------- #
# Rubric — duplicate id + unknown-field rejection
# --------------------------------------------------------------------------- #


def test_rubric_rejects_duplicate_entry_ids() -> None:
    entry = RubricEntry.model_validate(_entry_dict())
    with pytest.raises(ValidationError, match="duplicate entry id"):
        Rubric(version="v1", content_hash="0" * 64, entries=(entry, entry))


def test_rubric_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="oops"):
        Rubric.model_validate(
            {
                "version": "v1",
                "content_hash": "0" * 64,
                "entries": [_entry_dict()],
                "oops": True,
            }
        )


def test_rubric_rejects_empty_entries() -> None:
    with pytest.raises(ValidationError):
        Rubric(version="v1", content_hash="0" * 64, entries=())


def test_rubric_rejects_malformed_content_hash() -> None:
    with pytest.raises(ValidationError):
        Rubric(
            version="v1",
            content_hash="not-a-sha256",
            entries=(RubricEntry.model_validate(_entry_dict()),),
        )


# --------------------------------------------------------------------------- #
# Loader — deterministic hash + structural validation
# --------------------------------------------------------------------------- #


def test_load_rubric_bytes_returns_deterministic_hash() -> None:
    rubric = load_rubric_bytes(_FIXTURE_YAML)
    assert rubric.version == "v1-test"
    assert rubric.content_hash == _FIXTURE_HASH
    assert len(rubric.entries) == 2  # noqa: PLR2004
    assert rubric.entries[0].id == "product.gallery.thumbnails"
    assert rubric.entries[1].weight == 3  # noqa: PLR2004
    # Hash is stable across calls.
    assert load_rubric_bytes(_FIXTURE_YAML).content_hash == _FIXTURE_HASH


def test_compute_content_hash_matches_sha256() -> None:
    assert compute_content_hash(_FIXTURE_YAML) == _FIXTURE_HASH


def test_load_rubric_reads_file(tmp_path: Path) -> None:
    yaml_path = tmp_path / "v1.yaml"
    yaml_path.write_bytes(_FIXTURE_YAML)
    rubric = load_rubric(yaml_path)
    assert rubric.content_hash == _FIXTURE_HASH


def test_load_rubric_bytes_rejects_unknown_field_in_yaml() -> None:
    bad = _FIXTURE_YAML.replace(b"transactional: false", b"transactional: false\n    bogus: 1", 1)
    with pytest.raises(RubricLoadError, match="bogus"):
        load_rubric_bytes(bad)


def test_load_rubric_bytes_rejects_out_of_range_weight_in_yaml() -> None:
    bad = _FIXTURE_YAML.replace(b"weight: 2", b"weight: 7", 1)
    with pytest.raises(RubricLoadError, match="weight"):
        load_rubric_bytes(bad)


def test_load_rubric_bytes_rejects_non_mapping_root() -> None:
    bad = b"- just a list\n- of items\n"
    with pytest.raises(RubricLoadError, match="mapping"):
        load_rubric_bytes(bad)


def test_load_rubric_bytes_rejects_malformed_yaml() -> None:
    bad = b"version: v1\nentries:\n  - id: x\n   bad-indent: y\n"
    with pytest.raises(RubricLoadError, match="parse"):
        load_rubric_bytes(bad)


def test_load_rubric_distinguishes_payloads_by_hash() -> None:
    other = _FIXTURE_YAML.replace(b"v1-test", b"v1-test-2", 1)
    a = load_rubric_bytes(_FIXTURE_YAML)
    b = load_rubric_bytes(other)
    assert a.content_hash != b.content_hash
