"""``manifest.json`` builder for §5.10 synthesis.

Assembles the run summary written to
``<run_dir>/artifact/manifest.json``. Reads ``plan.md`` to count tasks
and parse the omitted-area block, and (best-effort) ``run.json`` for
the harness final status / iteration counters.

The plan-parsing helpers live here rather than in a shared module
because they are shaped by the manifest schema (per-row counts, area /
reason record). The structurally similar parser in
:mod:`shop_arena.explore.coverage` returns slug *sets* and is intentionally
kept separate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from shop_arena.explore.capabilities import Conflict


def build_manifest(
    *,
    run_dir: Path,
    conflicts: list[Conflict],
) -> dict[str, Any]:
    """Assemble the ``manifest.json`` payload (spec §5.10 step 4)."""
    plan_md_path = run_dir / "plan.md"
    plan_md = plan_md_path.read_text(encoding="utf-8") if plan_md_path.is_file() else ""
    plan_tasks_total, plan_tasks_done, plan_tasks_blocked = _count_plan_tasks(plan_md)
    omitted_areas = _parse_omitted_areas(plan_md)
    run_summary = _read_run_summary(run_dir)

    return {
        "run_id": run_dir.name,
        "domain": run_dir.parent.name,
        "runtime": run_summary.get("runtime", ""),
        "harness_status": run_summary.get("final_status", ""),
        "iters": {
            "plan": int(run_summary.get("plan_iter_count", 0) or 0),
            "exec": int(run_summary.get("exec_iter_count", 0) or 0),
        },
        "plan_tasks_total": plan_tasks_total,
        "plan_tasks_done": plan_tasks_done,
        "plan_tasks_blocked": plan_tasks_blocked,
        "omitted_areas": omitted_areas,
        "capability_conflicts": [c.model_dump(mode="json") for c in conflicts],
        "synthesized_at": _utc_now_iso(),
        "paths": {
            "manual": "artifact/manual.md",
            "capabilities": "artifact/capabilities.json",
            "stats": "artifact/stats.json",
            "manifest": "artifact/manifest.json",
            "prefetch": "artifact/prefetch",
        },
    }


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _read_run_summary(run_dir: Path) -> dict[str, Any]:
    """Best-effort read of ``run.json``.

    Missing or malformed ``run.json`` collapses to ``{}`` so synthesis
    can still emit a manifest (e.g. when called via
    ``--synthesize-only`` against a run_dir that pre-dates a harness
    crash). The harness itself is the source of truth for the run
    summary; we only mirror selected fields into the manifest.
    """
    path = run_dir / "run.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return cast(dict[str, Any], raw)


def _count_plan_tasks(plan_md: str) -> tuple[int, int, int]:
    """Count task rows under the ``## Tasks`` section of ``plan.md``.

    Returns ``(total, done, blocked)`` where ``done`` is ``[x]`` and
    ``blocked`` is ``[!]``. Pending and in-progress rows are counted in
    ``total`` only.
    """
    total = done = blocked = 0
    in_tasks = False
    for line in plan_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_tasks = stripped.lower().startswith("## tasks")
            continue
        if not in_tasks:
            continue
        if not stripped.startswith("- ["):
            continue
        marker = stripped[3:4]
        total += 1
        if marker == "x":
            done += 1
        elif marker == "!":
            blocked += 1
    return total, done, blocked


def _parse_omitted_areas(plan_md: str) -> list[dict[str, str]]:
    """Read the ``## Omitted Areas`` block of ``plan.md`` into records.

    Each line of the form ``- <area> — <reason>`` (em dash or hyphen)
    becomes ``{"area": ..., "reason": ...}``. Lines with no separator
    yield ``{"area": ..., "reason": ""}``.
    """
    items: list[dict[str, str]] = []
    in_block = False
    for line in plan_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_block = stripped.lower().startswith("## omitted")
            continue
        if not in_block or not stripped.startswith("- "):
            continue
        body = stripped[2:].strip()
        if " — " in body:
            area, _, reason = body.partition(" — ")
        elif " - " in body:
            area, _, reason = body.partition(" - ")
        else:
            area, reason = body, ""
        items.append({"area": area.strip(), "reason": reason.strip()})
    return items


def _utc_now_iso() -> str:
    """Return ``datetime.now(UTC)`` as an RFC 3339 ``Z`` timestamp."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
