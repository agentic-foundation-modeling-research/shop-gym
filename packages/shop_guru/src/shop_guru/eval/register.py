"""Gym registration for ShopGuru tasks.

Each ShopGuru task dict becomes a distinct BrowserGym gym id
(``browsergym/shop_guru.<task-id>``) via :func:`register_task`. The task
class itself is :class:`ShopGuruBrowserTask`; per-task parameters (the
task dict, step budget, screenshot cap) are passed as frozen
``task_kwargs`` so they can't be overridden at env-creation time.

Judge config is NOT passed here anymore — it lives on
:class:`shop_guru.eval.exp_args.ShopGuruExpArgs` and is consumed by the
post-episode hook, not the task.
"""

from __future__ import annotations

import logging
from typing import Any

import gymnasium as gym
from browsergym.core.registration import register_task

from shop_guru.eval.task import ShopGuruBrowserTask

logger = logging.getLogger(__name__)


def _already_registered(gym_id: str) -> bool:
    # gym's registry stores ids without the "browsergym/" prefix handling
    # that register_task adds.
    return f"browsergym/{gym_id}" in gym.registry


def register_shopguru_tasks(
    tasks: list[dict[str, Any]],
    max_steps: int | None = None,
) -> list[str]:
    """Register each task as a BrowserGym gym env. Returns the gym ids.

    Registration is idempotent per process — re-registering the same id
    is a no-op and emits a debug log. This lets worker processes safely
    re-import the module after the main process has already registered.

    ``max_steps`` is baked into the task so it can detect the
    budget-exhaustion case before the TimeLimit wrapper truncates. Must
    match the ``max_steps`` passed to ``build_shopguru_benchmark``.
    """
    task_kwargs_base: dict[str, Any] = {"max_steps": max_steps}

    names: list[str] = []
    for entry in tasks:
        task_id = entry.get("id")
        if not task_id:
            logger.warning("skipping task without id: %r", entry)
            continue
        gym_id = f"shop_guru.{task_id}"
        if _already_registered(gym_id):
            logger.debug("shop_guru task already registered: %s", gym_id)
            names.append(gym_id)
            continue
        register_task(
            gym_id,
            ShopGuruBrowserTask,
            task_kwargs={"shop_task": entry, **task_kwargs_base},
        )
        names.append(gym_id)
    logger.info("registered %d shop_guru task(s)", len(names))
    return names
