"""Aggregate per-episode summary_info.json files into study-level JSONs.

After an AgentLab study finishes, each episode directory holds a
``summary_info.json`` enriched by :func:`shop_guru.eval.run._surface_judgement_in_summary`.
This module walks those files, joins them with the task spec list (which
carries ``shop_slug`` and ``skill``), and writes two artifacts into the
study directory:

- ``results.json`` — canonical envelope
  (``{study, shop, variant, config, counts, results[]}``) with one row
  per task. Row shape is produced by
  :func:`shop_guru.eval.score.build_result_row` and matches what
  :mod:`shop_guru.eval.rejudge` emits, so the two files can be diffed
  one-to-one.
- ``aggregate.json`` — totals, overall success rate, and breakdowns by
  shop and by skill.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .score import build_result_row, build_results_envelope

logger = logging.getLogger(__name__)

RESULTS_FILENAME = "results.json"
AGGREGATE_FILENAME = "aggregate.json"


def _index_tasks(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return ``{task_id: task_dict}`` for fast lookup during the join."""
    return {t["id"]: t for t in tasks if "id" in t}


def _count_screenshots(episode_dir: Path) -> int:
    """Count ``screenshot_step_*.png`` files — matches ``_load_screenshots``."""
    return sum(1 for _ in episode_dir.glob("screenshot_step_*.png"))


def _extract_per_task(
    summary_path: Path, task_index: dict[str, dict[str, Any]], study_dir: Path
) -> dict[str, Any] | None:
    """Turn one ``summary_info.json`` into a canonical result row."""
    try:
        summary = json.loads(summary_path.read_text())
    except Exception as exc:
        logger.warning("could not read %s: %s", summary_path, exc)
        return None

    task_id = summary.get("shopguru_task_id")
    if not task_id:
        # Not a shop_guru episode (or the judgement promotion step skipped it).
        return None

    episode_dir_abs = summary_path.parent
    try:
        episode_dir = str(episode_dir_abs.relative_to(study_dir))
    except ValueError:
        episode_dir = str(episode_dir_abs)

    # Live path has no "prior" — this IS the first judgement. Leaving
    # ``elapsed_s`` None because the live hook doesn't time the judge call.
    return build_result_row(
        task_id=task_id,
        episode_dir=episode_dir,
        task_spec=task_index.get(task_id, {}),
        summary=summary,
        judgement=summary.get("judgement") or {},
        prior_verdict=None,
        screenshots_available=_count_screenshots(episode_dir_abs),
        elapsed_s=None,
    )


def _missing_task_row(task: dict[str, Any]) -> dict[str, Any]:
    """Synthetic failure row for a spec task that produced no summary_info.json.

    Tasks land here when ray cancelled them past --avg-step-timeout and
    they exhausted --n-relaunch retries (or the harness died before
    writing summary_info.json). Keeping them in the result set with
    success=False makes the aggregate denominator match the task spec
    count: a hung task counts against the success rate instead of
    silently disappearing from the totals.
    """
    return build_result_row(
        task_id=task.get("id"),
        episode_dir=None,
        task_spec=task,
        summary={},
        judgement={
            "failure_reason": (
                "no summary_info.json — task incomplete (cancelled by "
                "--avg-step-timeout or exhausted --n-relaunch retries)"
            )
        },
    )


def _bucket_rate(results: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    """Group results by ``key`` and compute per-bucket success stats."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        groups[r.get(key) or "<unknown>"].append(r)

    out: dict[str, dict[str, Any]] = {}
    for name, items in groups.items():
        total = len(items)
        n_success = sum(1 for i in items if i["success"])
        out[name] = {
            "total": total,
            "n_success": n_success,
            "success_rate": (n_success / total) if total else 0.0,
        }
    return out


def write_results_summary(
    study_dir: Path,
    tasks: list[dict[str, Any]],
    *,
    shop: str,
    variant: str,
    config: dict[str, Any],
) -> tuple[Path, Path]:
    """Write ``results.json`` and ``aggregate.json`` into ``study_dir``.

    Returns the pair of paths. Safe to call on a study dir that has no
    summary files yet — it will produce an aggregate with ``total: 0``.

    ``shop`` / ``variant`` / ``config`` populate the shared envelope so
    ``results.json`` has the same top-level shape as a rejudge file.
    """
    study_dir = Path(study_dir)
    task_index = _index_tasks(tasks)

    start = time.time()
    results: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()
    for summary_path in sorted(study_dir.rglob("summary_info.json")):
        row = _extract_per_task(summary_path, task_index, study_dir)
        if row is not None:
            results.append(row)
            tid = row.get("task_id")
            if tid:
                seen_task_ids.add(tid)

    # Backfill failure rows for spec tasks that produced no summary —
    # the denominator should match the task list, not the count of
    # episodes that finished. Without this, a hung task that exhausts
    # --n-relaunch silently disappears from the aggregate.
    n_incomplete = 0
    for task_id, task in task_index.items():
        if task_id in seen_task_ids:
            continue
        results.append(_missing_task_row(task))
        n_incomplete += 1

    # Deterministic order: shop → skill → task_id so diffs across runs
    # line up and the file is easier to eyeball.
    results.sort(
        key=lambda r: (
            r.get("shop_slug") or "",
            r.get("skill") or "",
            r.get("task_id") or "",
        )
    )

    envelope = build_results_envelope(
        study=str(study_dir),
        shop=shop,
        variant=variant,
        config=config,
        rows=results,
        elapsed_s=round(time.time() - start, 2),
    )

    total = envelope["counts"]["total"]
    success_rate = envelope["counts"]["success_rate"]

    # aggregate.json keeps its richer breakdowns (per-shop / per-skill).
    # Not using ``build_results_envelope`` here on purpose — this file is
    # meant for a different consumer (dashboards, roll-ups).
    aggregate: dict[str, Any] = {
        "total": total,
        "n_success": envelope["counts"]["n_success"],
        "n_failed": envelope["counts"]["n_failed"],
        "success_rate": success_rate,
        "n_incomplete": n_incomplete,
        "n_forced_by_budget": sum(1 for r in results if r.get("forced_by_budget")),
        "n_impossible_task": sum(1 for r in results if r.get("impossible_task")),
        "n_reached_captcha": sum(1 for r in results if r.get("reached_captcha")),
        "n_errors": sum(1 for r in results if r.get("err_msg")),
        "by_shop": _bucket_rate(results, "shop_slug"),
        "by_skill": _bucket_rate(results, "skill"),
        "study_dir": str(study_dir),
    }

    results_path = study_dir / RESULTS_FILENAME
    aggregate_path = study_dir / AGGREGATE_FILENAME
    results_path.write_text(json.dumps(envelope, indent=2, default=str))
    aggregate_path.write_text(json.dumps(aggregate, indent=2, default=str))

    logger.info(
        "wrote %s (%d tasks, success_rate=%.3f) and %s",
        results_path,
        total,
        success_rate,
        aggregate_path,
    )
    return results_path, aggregate_path
