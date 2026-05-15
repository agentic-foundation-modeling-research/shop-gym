"""Sibling-iter history scan for the per-task retry budget (impl plan T2.1).

Spec §5.4 caps the executor → verifier retry loop at a configurable
number of consecutive ``visual_judge`` FAILs against the same task id.
The harness exposes no per-task retry counter, so the verifier enforces
the cap itself by reading **its own past verdicts** from sibling iter
dirs.

This module owns the "count my prior FAILs" half of that contract; the
ADVISORY downgrade (T2.2) consumes :func:`count_prior_task_fails` and
turns its return value into a verifier-level decision.

The on-disk shape we read is the dispatch layer's per-verifier
telemetry file (``harness.verifiers.dispatch._write_verifier_record``)::

    {
      "iter_id": "exec-0001",
      "name": "visual_judge",
      "task_id": "gen_homepage",
      "verdict": "fail",
      "started_at": "...",
      "duration_ms": 123,
      "feedback": "...",
      "details": {...}
    }

Malformed / missing records are silently ignored — they cannot count
toward the budget and a cold ``runs/`` tree must not raise from inside
the verifier.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, cast

_ITERS_DIRNAME: Final[str] = "iters"
"""Per-spec §5.4: sibling iters live under ``<run_dir>/iters/``."""

_ITER_DIR_GLOB: Final[str] = "exec-*"
"""Iter-id pattern emitted by the harness loop (e.g. ``exec-0001``)."""

_VERIFIERS_DIR_PARTS: Final[tuple[str, ...]] = ("checks", "verifiers")
"""Sub-path inside an iter dir where dispatch writes ``<name>.json``."""


def count_prior_task_fails(
    *,
    run_dir: Path,
    iter_id: str,
    verifier_name: str,
    task_id: str,
) -> int:
    """Count prior ``verdict == "fail"`` entries for one verifier+task.

    Walks ``<run_dir>/iters/exec-*/checks/verifiers/<verifier_name>.json``,
    skipping the current iteration. Each surviving record contributes
    to the count when both:

    - its ``verdict`` field equals ``"fail"`` (case-sensitive — the
      dispatch layer always writes the lowercase enum value), and
    - its ``task_id`` field equals ``task_id``.

    Records that fail to parse, are missing required keys, or do not
    match the (verdict, task_id) pair are ignored. Missing ``iters/``
    tree returns ``0`` so a brand-new run never crashes the budget
    check.

    Args:
        run_dir: Build-loop workspace root (the ``run_dir`` the
            harness threads through every verifier context).
        iter_id: Current iteration id; matched against the parent
            directory name to skip self-reads.
        verifier_name: Telemetry file stem (e.g. ``"visual_judge"``).
        task_id: Task whose prior FAILs we are counting.

    Returns:
        Non-negative count of prior FAIL records for this
        (verifier, task) pair.
    """
    iters_root = run_dir / _ITERS_DIRNAME
    if not iters_root.is_dir():
        return 0
    record_name = f"{verifier_name}.json"
    count = 0
    for iter_dir in iters_root.glob(_ITER_DIR_GLOB):
        if iter_dir.name == iter_id:
            continue
        record_path = iter_dir.joinpath(*_VERIFIERS_DIR_PARTS, record_name)
        if not record_path.is_file():
            continue
        if _record_is_task_fail(record_path, task_id=task_id):
            count += 1
    return count


def _record_is_task_fail(path: Path, *, task_id: str) -> bool:
    """Return True iff the on-disk record is a FAIL against ``task_id``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    payload_dict = cast("dict[str, Any]", payload)
    return payload_dict.get("verdict") == "fail" and payload_dict.get("task_id") == task_id


__all__ = ["count_prior_task_fails"]
