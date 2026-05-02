"""Run every ShopGuru task in one Study and write aggregate result JSONs.

This is the batch counterpart to :mod:`shop_guru.eval.run`. It drops the
``--task-id`` filter (use the single-task driver for that) and, once the
Study finishes, walks the study directory to emit:

- ``<study_dir>/results.json``   — one row per task with success + verdict
- ``<study_dir>/aggregate.json`` — totals + per-shop / per-skill rates

Usage::

    uv run python -m shop_guru.eval.run_all
    uv run python -m shop_guru.eval.run_all --shop mock_shop --skill e2e_v1
"""

from __future__ import annotations

import logging
import os
import sys
import time

from shop_guru.eval import write_results_summary
from shop_guru.eval.run import (
    _build_parser,
    _execute_study,
    _prepare_tasks,
    _resolve_environment,
    _surface_judgement_in_summary,
)

logger = logging.getLogger(__name__)

# Each worker launches a Chromium instance, so oversubscribing CPUs hurts
# more than it helps. Half the cores, capped at 8, is a safe default on
# laptops and CI boxes alike; the user can always override with --n-jobs.
_DEFAULT_N_JOBS = max(2, min(8, (os.cpu_count() or 2) // 2))


# Libraries that flood stdout at INFO level during a run. We leave our
# own logger (``shop_guru.*``) and AgentLab's error-level messages alone
# so failures still surface; everything else goes to WARNING.
_NOISY_LIBRARIES = (
    "agentlab",
    "browsergym",
    "openai",
    "httpx",
    "httpcore",
    "urllib3",
    "playwright",
    "PIL",
    "asyncio",
)


def _silence_noisy_loggers() -> None:
    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser(
        prog="shop_guru-agentlab-all",
        description=(
            "Run every ShopGuru task in one study and write per-task + "
            "aggregate result JSONs."
        ),
        include_task_id=False,
        default_n_jobs=_DEFAULT_N_JOBS,
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Disable the quiet progress bar and restore full INFO-level "
            "logging from agentlab / browsergym / openai / playwright."
        ),
    )
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:
        # Quiet mode: WARNING+ only, minimal formatter. tqdm handles the
        # progress display; anything that still logs at WARNING is a real
        # signal worth surfacing.
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
        _silence_noisy_loggers()

    config_path, results_dir = _resolve_environment(args, parser)
    try:
        tasks, gym_task_names = _prepare_tasks(args, config_path)
    except SystemExit as exc:
        logger.error("%s", exc)
        return 2

    start_time = time.monotonic()
    study = _execute_study(
        args,
        gym_task_names,
        tasks,
        stdout_log_level=logging.INFO if args.verbose else logging.WARNING,
        show_progress=not args.verbose,
    )
    elapsed = time.monotonic() - start_time
    logger.warning(
        "Evaluated %d task(s) in %.1fs (%.2fs/task avg)",
        len(gym_task_names),
        elapsed,
        elapsed / len(gym_task_names) if gym_task_names else 0.0,
    )

    _surface_judgement_in_summary(results_dir)

    study_dir = getattr(study, "dir", None) or results_dir
    judge_config = {
        "model": args.judge_model,
        "max_images": args.max_images,
        "image_scale": args.image_scale,
    }
    write_results_summary(
        study_dir,
        tasks,
        shop=args.shop,
        variant=args.variant,
        config=judge_config,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
