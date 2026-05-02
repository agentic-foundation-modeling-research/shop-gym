"""BrowserGym task wrapper for a single ShopGuru benchmark entry.

Each ShopGuru task dict (``{id, intent, url, type, success_criteria}``)
becomes one :class:`ShopGuruBrowserTask`. The task navigates to the
starting URL during ``setup()`` and surfaces termination metadata
(terminal role, forced-by-budget flag, etc.) via ``task_info`` on the
final ``validate()`` call.

The task is capture-light by design: screenshots and per-step URLs are
already persisted by AgentLab's ``ExpArgs.run()`` (as
``screenshot_step_*.png`` and ``step_*.pkl.gz`` with ``obs["url"]``), so
the post-episode judge in :class:`shop_guru.eval.exp_args.ShopGuruExpArgs`
reads them off disk rather than shipping them through ``task_info``.
"""

from __future__ import annotations

import logging
from typing import Any

import playwright.sync_api
from browsergym.core.task import AbstractBrowserTask

logger = logging.getLogger(__name__)


class ShopGuruBrowserTask(AbstractBrowserTask):
    """Wraps one ShopGuru task dict as a BrowserGym task (capture-only)."""

    def __init__(
        self,
        seed: int,
        shop_task: dict[str, Any],
        max_steps: int | None = None,
    ) -> None:
        super().__init__(seed)
        self.shop_task = shop_task
        # Budget the TimeLimit wrapper enforces. Used to detect
        # "budget-exhausted" terminations so the hook can still run a
        # judgement instead of a silent truncation.
        self.max_steps = max_steps

        # Match the viewport used by the ShopGuru screenshot-diff pipeline so
        # the judge sees framing consistent with the reference screenshots.
        self.viewport = {"width": 1280, "height": 800}
        self.slow_mo = 0  # ms — no artificial delay, SandboxShops are already slow
        self.timeout = 30_000  # ms — Cloud Run cold starts need headroom

        self._n_validate_calls = 0
        self._forced_by_budget = False
        self._terminal_role: str | None = None  # "assistant" / "infeasible" / "budget"

    @classmethod
    def get_task_id(cls) -> str:
        # Individual tasks are registered under distinct gym ids
        # ("shop_guru.<task-id>") via register_shopguru_tasks; this constant
        # is only used as the class-level fallback.
        return "shop_guru"

    def setup(self, page: playwright.sync_api.Page) -> tuple[str, dict]:
        url = self.shop_task["url"]
        try:
            page.goto(url, timeout=self.timeout)
        except playwright.sync_api.TimeoutError:
            logger.warning("initial navigation to %s timed out; continuing", url)
        goal = self.shop_task["intent"]
        info = {
            "shopguru_task_id": self.shop_task.get("id"),
            "shopguru_task_type": self.shop_task.get("type"),
        }
        return goal, info

    def teardown(self) -> None:  # noqa: D401 — mirrors parent signature
        return None

    def _terminal_signal(
        self, chat_messages: list[dict[str, Any]]
    ) -> tuple[bool, bool]:
        """Return (done, forced_fail) from the latest chat message.

        The final_result string isn't needed here — the post-episode
        judge re-derives it from the persisted chat messages in
        ``score.load_episode``.
        """
        if not chat_messages:
            return False, False
        role = chat_messages[-1].get("role", "")
        if role == "assistant":
            return True, False
        if role == "infeasible":
            return True, True
        return False, False

    def _build_task_info(self) -> dict[str, Any]:
        """Snapshot metadata for the runtime ``task_info`` dict.

        Ends up in ``StepInfo.task_info`` and is surfaced into
        ``summary_info.json`` by ``ShopGuruExpArgs.run`` (or by the
        post-study safety net in ``run._surface_judgement_in_summary``).
        URL trajectory and screenshots aren't included here — both are
        reconstructable from the step pickles AgentLab already writes.
        """
        return {
            "forced_by_budget": self._forced_by_budget,
            "terminal_role": self._terminal_role,
            "n_validate_calls": self._n_validate_calls,
            "max_steps": self.max_steps,
            "shopguru_task_id": self.shop_task.get("id"),
            "shopguru_task_type": self.shop_task.get("type"),
        }

    def validate(
        self,
        page: playwright.sync_api.Page,  # noqa: ARG002 — required by parent signature
        chat_messages: list[dict[str, Any]],
    ) -> tuple[float, bool, str, dict]:
        self._n_validate_calls += 1

        done, forced_fail = self._terminal_signal(chat_messages)
        if done:
            self._terminal_role = "infeasible" if forced_fail else "assistant"

        # Budget-exhaustion fallback: TimeLimit is about to stamp
        # truncated=True on this same step. Surface that as a terminal
        # state so the post-episode hook can still score on evidence.
        budget_exhausted = (
            not done
            and self.max_steps is not None
            and self._n_validate_calls >= self.max_steps
        )
        if budget_exhausted:
            done = True
            self._forced_by_budget = True
            self._terminal_role = "budget"

        if not done:
            return 0.0, False, "", {}

        return 0.0, True, "", self._build_task_info()
