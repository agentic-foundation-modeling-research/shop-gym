"""``ExpArgs`` subclass that invokes the judge after each episode.

Overrides :meth:`ExpArgs.run` to: call ``super().run()`` (which runs
the episode and writes ``step_*.pkl.gz`` / ``summary_info.json``), then
reload the episode from disk via :mod:`shop_guru.eval.score` and write
the judgement back into ``summary_info.json``.

This module deliberately lives inside ``shop_guru.eval`` so that when
joblib/Ray workers unpickle a ``ShopGuruExpArgs`` instance, the class
import transitively imports :mod:`shop_guru.eval`, which fires
``_bootstrap_from_env`` and re-registers every ShopGuru task in the
worker process — the same trick
:class:`shop_guru.eval.benchmark.ShopGuruEnvArgs` uses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentlab.experiments.loop import ExpArgs

from shop_guru.eval.score import (
    JudgeConfig,
    judge_episode,
    load_episode,
    merge_judgement_into_summary,
)

logger = logging.getLogger(__name__)


@dataclass
class ShopGuruExpArgs(ExpArgs):
    """``ExpArgs`` that runs the ShopGuru judge as a post-episode hook.

    Fields beyond the parent class hold everything the judge needs that
    isn't already on ``env_args`` — the judge config (model, API key,
    image caps) and the task dict itself. The task dict carries
    ``intent`` and ``success_criteria``; we don't pull them from the
    benchmark YAML at hook time because workers don't have the YAML
    handy.
    """

    judge_model: str | None = None
    judge_api_key: str | None = None
    judge_max_images: int = 10
    judge_image_scale: float = 1.0
    shop_task: dict[str, Any] = field(default_factory=dict)

    def run(self) -> None:  # type: ignore[override]
        super().run()
        try:
            self._run_shopguru_judge()
        except Exception:
            # Never let a judge failure poison the surrounding study run
            # — the episode itself completed, we just failed to score it.
            # ``run.py._surface_judgement_in_summary`` can still pick up
            # partial task_info from the step pickles as a safety net.
            logger.exception(
                "shop_guru post-episode judge failed for exp_dir=%s", self.exp_dir
            )

    def _run_shopguru_judge(self) -> None:
        if self.exp_dir is None:
            logger.warning(
                "ShopGuruExpArgs.run: exp_dir is None, skipping judge"
            )
            return
        if not self.judge_model:
            logger.warning(
                "ShopGuruExpArgs.run: judge_model missing; skipping judge",
            )
            return

        episode_dir = Path(self.exp_dir)
        benchmark_tasks = [self.shop_task] if self.shop_task else []
        episode = load_episode(episode_dir, benchmark_tasks)
        if episode is None:
            logger.warning(
                "ShopGuruExpArgs.run: could not reconstruct episode from %s; "
                "skipping judge",
                episode_dir,
            )
            return

        config = JudgeConfig(
            model=self.judge_model,
            api_key=self.judge_api_key,
            max_images=self.judge_max_images,
            image_scale=self.judge_image_scale,
        )
        result = judge_episode(episode, config)
        merge_judgement_into_summary(episode_dir, episode, result)

        logger.info(
            "[shop_guru.judge] task=%s verdict=%s forced_by_budget=%s%s",
            episode.task_id,
            result.verdict,
            episode.forced_by_budget,
            f" reason={result.failure_reason}" if not result.verdict else "",
        )


__all__ = ["ShopGuruExpArgs"]
