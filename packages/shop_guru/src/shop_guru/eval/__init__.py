"""ShopGuru evaluation harness on top of BrowserGym + AgentLab.

Public API:

    from shop_guru.eval import (
        JudgementResult,
        ShopGuruBrowserTask,
        build_shopguru_benchmark,
        load_shopguru_tasks,
        register_shopguru_tasks,
    )

Worker bootstrap:
    When this module is imported, it reads the task-spec env var and,
    if the file exists, registers every task found inside it. This is
    what lets joblib/Ray workers pick up the same registration that
    the main process performed, without any IPC. Judge config is
    carried on :class:`shop_guru.eval.exp_args.ShopGuruExpArgs`, not the
    task, so the bootstrap no longer needs the judge env vars for
    registration. ``run.py`` still exports them for other consumers
    (e.g. :mod:`shop_guru.eval.rejudge`) to read directly.

    SHOPGURU_TASK_SPEC       Path to a JSON file containing the task list.
    SHOPGURU_MAX_STEPS       Step budget; lets the task detect the
                             budget-exhaustion case cleanly.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .aggregate import write_results_summary
from .benchmark import build_shopguru_benchmark
from .judge import JudgementResult, judge_trace
from .loader import load_shopguru_tasks
from .register import register_shopguru_tasks
from .score import build_result_row, build_results_envelope
from .task import ShopGuruBrowserTask

logger = logging.getLogger(__name__)

__all__ = [
    "JudgementResult",
    "ShopGuruBrowserTask",
    "build_result_row",
    "build_results_envelope",
    "build_shopguru_benchmark",
    "judge_trace",
    "load_shopguru_tasks",
    "register_shopguru_tasks",
    "write_results_summary",
]


def _bootstrap_from_env() -> None:
    spec = os.environ.get("SHOPGURU_TASK_SPEC")
    if not spec:
        return
    path = Path(spec)
    if not path.exists():
        logger.warning("SHOPGURU_TASK_SPEC points to missing file: %s", path)
        return
    try:
        tasks = json.loads(path.read_text())
    except Exception as exc:
        logger.warning("failed to load SHOPGURU_TASK_SPEC=%s: %s", path, exc)
        return
    if not isinstance(tasks, list):
        logger.warning("SHOPGURU_TASK_SPEC JSON must be a list, got %s", type(tasks))
        return
    max_steps_env = os.environ.get("SHOPGURU_MAX_STEPS")
    try:
        max_steps = int(max_steps_env) if max_steps_env else None
    except ValueError:
        logger.warning("SHOPGURU_MAX_STEPS=%r not an int; ignoring", max_steps_env)
        max_steps = None
    register_shopguru_tasks(tasks, max_steps=max_steps)


_bootstrap_from_env()
