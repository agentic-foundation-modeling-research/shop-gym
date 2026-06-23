"""Unit tests for ``shop_arena.gen.build.verifiers._history`` (impl plan T2.1).

Covers the sibling-iter scan that powers the ``visual_judge`` per-task
retry budget. The ADVISORY downgrade itself lands in T2.2 — these tests
only lock down the count.
"""

from __future__ import annotations

import json
from pathlib import Path

from shop_arena.gen.build.verifiers._history import count_prior_task_fails


def _write_record(
    iters_root: Path,
    *,
    iter_id: str,
    verifier_name: str,
    task_id: str,
    verdict: str,
) -> Path:
    """Write a dispatch-shaped per-verifier telemetry record."""
    record_dir = iters_root / iter_id / "checks" / "verifiers"
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / f"{verifier_name}.json"
    record_path.write_text(
        json.dumps(
            {
                "iter_id": iter_id,
                "name": verifier_name,
                "task_id": task_id,
                "verdict": verdict,
                "started_at": "2024-01-01T00:00:00+00:00",
                "duration_ms": 1,
                "feedback": "",
                "details": {},
            },
        ),
        encoding="utf-8",
    )
    return record_path


def test_count_prior_task_fails_returns_zero_when_iters_dir_missing(
    tmp_path: Path,
) -> None:
    """A cold run_dir with no ``iters/`` tree must not raise."""
    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0001",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 0
    )


def test_count_prior_task_fails_counts_zero_with_no_siblings(tmp_path: Path) -> None:
    """Empty siblings → 0."""
    (tmp_path / "iters").mkdir()
    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0001",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 0
    )


def test_count_prior_task_fails_counts_one_prior_fail(tmp_path: Path) -> None:
    """Single sibling FAIL against the same task → 1."""
    iters_root = tmp_path / "iters"
    _write_record(
        iters_root,
        iter_id="exec-0001",
        verifier_name="visual_judge",
        task_id="gen_homepage",
        verdict="fail",
    )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0002",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 1
    )


def test_count_prior_task_fails_counts_three_consecutive_fails(tmp_path: Path) -> None:
    """SC3 fixture: 3 prior FAILs against the same task accumulate."""
    iters_root = tmp_path / "iters"
    for i in range(1, 4):
        _write_record(
            iters_root,
            iter_id=f"exec-{i:04d}",
            verifier_name="visual_judge",
            task_id="gen_homepage",
            verdict="fail",
        )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0004",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 3
    )


def test_count_prior_task_fails_counts_five_with_mixed_history(tmp_path: Path) -> None:
    """5 FAILs interleaved with PASSes against the same task → 5."""
    iters_root = tmp_path / "iters"
    pattern = ("fail", "pass", "fail", "fail", "pass", "fail", "fail")
    for i, verdict in enumerate(pattern, start=1):
        _write_record(
            iters_root,
            iter_id=f"exec-{i:04d}",
            verifier_name="visual_judge",
            task_id="gen_homepage",
            verdict=verdict,
        )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id=f"exec-{len(pattern) + 1:04d}",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 5
    )


def test_count_prior_task_fails_excludes_current_iter(tmp_path: Path) -> None:
    """The current iter's record is skipped even when it is a FAIL."""
    iters_root = tmp_path / "iters"
    _write_record(
        iters_root,
        iter_id="exec-0001",
        verifier_name="visual_judge",
        task_id="gen_homepage",
        verdict="fail",
    )
    _write_record(
        iters_root,
        iter_id="exec-0002",
        verifier_name="visual_judge",
        task_id="gen_homepage",
        verdict="fail",
    )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0002",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 1
    )


def test_count_prior_task_fails_filters_other_tasks(tmp_path: Path) -> None:
    """FAILs against a different ``task_id`` are not counted."""
    iters_root = tmp_path / "iters"
    _write_record(
        iters_root,
        iter_id="exec-0001",
        verifier_name="visual_judge",
        task_id="gen_homepage",
        verdict="fail",
    )
    _write_record(
        iters_root,
        iter_id="exec-0002",
        verifier_name="visual_judge",
        task_id="gen_product",
        verdict="fail",
    )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0003",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 1
    )


def test_count_prior_task_fails_filters_other_verifiers(tmp_path: Path) -> None:
    """Records from a different verifier file are not counted."""
    iters_root = tmp_path / "iters"
    _write_record(
        iters_root,
        iter_id="exec-0001",
        verifier_name="quality_judge",
        task_id="gen_homepage",
        verdict="fail",
    )
    _write_record(
        iters_root,
        iter_id="exec-0002",
        verifier_name="visual_judge",
        task_id="gen_homepage",
        verdict="fail",
    )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0003",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 1
    )


def test_count_prior_task_fails_only_counts_fail_verdict(tmp_path: Path) -> None:
    """``pass`` / ``advisory`` / ``error`` records are ignored."""
    iters_root = tmp_path / "iters"
    for i, verdict in enumerate(("pass", "advisory", "error", "fail"), start=1):
        _write_record(
            iters_root,
            iter_id=f"exec-{i:04d}",
            verifier_name="visual_judge",
            task_id="gen_homepage",
            verdict=verdict,
        )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-9999",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 1
    )


def test_count_prior_task_fails_ignores_malformed_records(tmp_path: Path) -> None:
    """Garbled / non-object JSON cannot count toward the budget."""
    iters_root = tmp_path / "iters"
    bad_dir = iters_root / "exec-0001" / "checks" / "verifiers"
    bad_dir.mkdir(parents=True)
    (bad_dir / "visual_judge.json").write_text("{not json", encoding="utf-8")
    list_dir = iters_root / "exec-0002" / "checks" / "verifiers"
    list_dir.mkdir(parents=True)
    (list_dir / "visual_judge.json").write_text("[]", encoding="utf-8")
    _write_record(
        iters_root,
        iter_id="exec-0003",
        verifier_name="visual_judge",
        task_id="gen_homepage",
        verdict="fail",
    )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0004",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 1
    )


def test_count_prior_task_fails_ignores_non_exec_dirs(tmp_path: Path) -> None:
    """Only ``exec-*`` iter dirs are scanned (per spec §5.4 glob)."""
    iters_root = tmp_path / "iters"
    _write_record(
        iters_root,
        iter_id="bootstrap",  # not exec-*
        verifier_name="visual_judge",
        task_id="gen_homepage",
        verdict="fail",
    )
    _write_record(
        iters_root,
        iter_id="exec-0001",
        verifier_name="visual_judge",
        task_id="gen_homepage",
        verdict="fail",
    )

    assert (
        count_prior_task_fails(
            run_dir=tmp_path,
            iter_id="exec-0002",
            verifier_name="visual_judge",
            task_id="gen_homepage",
        )
        == 1
    )
