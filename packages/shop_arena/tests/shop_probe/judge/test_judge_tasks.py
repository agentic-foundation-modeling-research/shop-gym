"""Tests for `shop_probe.judge.tasks` (T4.3 acceptance — spec §5.5 step 1, §5.8).

Covers:

* :class:`JudgeTask` round-trip and unknown-field rejection.
* Multi-page / interaction-heavy invariants (≥ 2 distinct surfaces and
  interactions per task) per spec §5.5 step 1.
* :func:`load_judge_tasks` deterministic content hash over a fixture
  YAML.
* Loader-level error handling for malformed YAML and bad shapes.
* :class:`JudgeTaskSet` size bounds (``8 ≤ len ≤ 12``) per spec §5.5
  step 1 ("~10 tasks").
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from shop_probe.judge.tasks import (
    JudgeTask,
    JudgeTaskLoadError,
    JudgeTaskSet,
    compute_content_hash,
    load_judge_tasks,
    load_judge_tasks_bytes,
)

# --------------------------------------------------------------------------- #
# Fixture YAML — frozen here so the hash assertion is deterministic.
# --------------------------------------------------------------------------- #


def _padded_task_yaml(count: int = 8) -> bytes:
    """Yield a YAML document with ``count`` synthetic tasks.

    Used to exercise the ``8 ≤ len ≤ 12`` bound without depending on
    the shipped ``v1.yaml``.
    """
    body = ["version: v1-test", "tasks:"]
    for i in range(count):
        body.extend(
            [
                f"  - id: task_{i}",
                f"    description: Synthetic judge task {i}.",
                "    surfaces: [collection, product]",
                "    interactions: [filter, open_pdp]",
                "    rationale: Synthetic.",
            ]
        )
    return ("\n".join(body) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# JudgeTask — round-trip + unknown-field rejection
# --------------------------------------------------------------------------- #


def _task_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "filter_pdp_cart",
        "description": "Filter the bestsellers, open the third PDP, add to cart.",
        "surfaces": ("collection", "product", "cart"),
        "interactions": ("filter", "open_pdp", "add_to_cart"),
        "rationale": "Multi-page filter + PDP + cart sequence.",
    }
    base.update(overrides)
    return base


def test_judge_task_round_trip() -> None:
    raw = _task_dict()
    task = JudgeTask.model_validate(raw)
    assert task.model_dump() == raw
    assert JudgeTask.model_validate_json(task.model_dump_json()) == task


def test_judge_task_rejects_unknown_field() -> None:
    raw = _task_dict(extra_field="nope")
    with pytest.raises(ValidationError, match="extra_field"):
        JudgeTask.model_validate(raw)


@pytest.mark.parametrize("bad_id", ["", "Has-Caps", "with space", "1leading", "trailing-"])
def test_judge_task_rejects_bad_id(bad_id: str) -> None:
    raw = _task_dict(id=bad_id)
    with pytest.raises(ValidationError):
        JudgeTask.model_validate(raw)


def test_judge_task_requires_two_surfaces() -> None:
    raw = _task_dict(surfaces=("collection",))
    with pytest.raises(ValidationError, match="surfaces"):
        JudgeTask.model_validate(raw)


def test_judge_task_requires_two_interactions() -> None:
    raw = _task_dict(interactions=("filter",))
    with pytest.raises(ValidationError, match="interactions"):
        JudgeTask.model_validate(raw)


def test_judge_task_rejects_unknown_surface() -> None:
    raw = _task_dict(surfaces=("collection", "checkout_summary"))
    with pytest.raises(ValidationError):
        JudgeTask.model_validate(raw)


def test_judge_task_rejects_unknown_interaction() -> None:
    raw = _task_dict(interactions=("filter", "yodel"))
    with pytest.raises(ValidationError):
        JudgeTask.model_validate(raw)


def test_judge_task_rejects_duplicate_surfaces() -> None:
    raw = _task_dict(surfaces=("collection", "collection", "product"))
    with pytest.raises(ValidationError, match="duplicate entry in surfaces"):
        JudgeTask.model_validate(raw)


def test_judge_task_rejects_duplicate_interactions() -> None:
    raw = _task_dict(interactions=("filter", "filter", "open_pdp"))
    with pytest.raises(ValidationError, match="duplicate entry in interactions"):
        JudgeTask.model_validate(raw)


# --------------------------------------------------------------------------- #
# JudgeTaskSet — duplicate id, unknown field, size bounds
# --------------------------------------------------------------------------- #


def test_judge_task_set_rejects_duplicate_task_ids() -> None:
    task = JudgeTask.model_validate(_task_dict())
    # Build 8 entries with one duplicate id to satisfy min_length=8.
    others = tuple(
        JudgeTask.model_validate(_task_dict(id=f"task_{i}", description=f"task {i}"))
        for i in range(7)
    )
    with pytest.raises(ValidationError, match="duplicate task id"):
        JudgeTaskSet(version="v1", content_hash="0" * 64, tasks=(task, task, *others))


def test_judge_task_set_rejects_unknown_field() -> None:
    raw = {
        "version": "v1",
        "content_hash": "0" * 64,
        "tasks": [_task_dict(id=f"task_{i}", description=f"task {i}") for i in range(8)],
        "oops": True,
    }
    with pytest.raises(ValidationError, match="oops"):
        JudgeTaskSet.model_validate(raw)


@pytest.mark.parametrize("count", [0, 1, 7])
def test_judge_task_set_rejects_too_few_tasks(count: int) -> None:
    with pytest.raises(JudgeTaskLoadError):
        load_judge_tasks_bytes(_padded_task_yaml(count=count))


def test_judge_task_set_rejects_too_many_tasks() -> None:
    with pytest.raises(JudgeTaskLoadError):
        load_judge_tasks_bytes(_padded_task_yaml(count=13))


def test_judge_task_set_rejects_malformed_content_hash() -> None:
    tasks = tuple(
        JudgeTask.model_validate(_task_dict(id=f"task_{i}", description=f"task {i}"))
        for i in range(8)
    )
    with pytest.raises(ValidationError):
        JudgeTaskSet(version="v1", content_hash="not-a-sha256", tasks=tasks)


# --------------------------------------------------------------------------- #
# Loader — deterministic hash + structural validation
# --------------------------------------------------------------------------- #


def test_load_judge_tasks_bytes_returns_deterministic_hash() -> None:
    payload = _padded_task_yaml(count=8)
    expected = hashlib.sha256(payload).hexdigest()
    task_set = load_judge_tasks_bytes(payload)
    assert task_set.version == "v1-test"
    assert task_set.content_hash == expected
    assert len(task_set.tasks) == 8  # noqa: PLR2004
    # Hash is stable across calls.
    assert load_judge_tasks_bytes(payload).content_hash == expected


def test_compute_content_hash_matches_sha256() -> None:
    payload = _padded_task_yaml(count=8)
    assert compute_content_hash(payload) == hashlib.sha256(payload).hexdigest()


def test_load_judge_tasks_reads_file(tmp_path: Path) -> None:
    yaml_path = tmp_path / "v1.yaml"
    payload = _padded_task_yaml(count=8)
    yaml_path.write_bytes(payload)
    task_set = load_judge_tasks(yaml_path)
    assert task_set.content_hash == hashlib.sha256(payload).hexdigest()


def test_load_judge_tasks_bytes_rejects_unknown_field_in_yaml() -> None:
    # Inject an unknown field into the *first* synthetic task of an
    # otherwise-valid 8-task payload so the loader fails on the field
    # rather than on min_length.
    bad = _padded_task_yaml(count=8).replace(
        b"    rationale: Synthetic.",
        b"    rationale: Synthetic.\n    bogus: 1",
        1,
    )
    with pytest.raises(JudgeTaskLoadError, match="bogus"):
        load_judge_tasks_bytes(bad)


def test_load_judge_tasks_bytes_rejects_non_mapping_root() -> None:
    bad = b"- just a list\n- of items\n"
    with pytest.raises(JudgeTaskLoadError, match="mapping"):
        load_judge_tasks_bytes(bad)


def test_load_judge_tasks_bytes_rejects_malformed_yaml() -> None:
    bad = b"version: v1\ntasks:\n  - id: x\n   bad-indent: y\n"
    with pytest.raises(JudgeTaskLoadError, match="parse"):
        load_judge_tasks_bytes(bad)


def test_load_judge_tasks_distinguishes_payloads_by_hash() -> None:
    a = load_judge_tasks_bytes(_padded_task_yaml(count=8))
    b = load_judge_tasks_bytes(_padded_task_yaml(count=9))
    assert a.content_hash != b.content_hash
