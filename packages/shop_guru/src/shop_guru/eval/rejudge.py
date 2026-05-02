"""Standalone re-judger for an existing ShopGuru study.

Reads a completed AgentLab study directory (one subdir per episode,
each with ``exp_args.pkl``, ``step_*.pkl.gz``, ``screenshot_step_*.png``,
and ``summary_info.json``) and re-runs the ShopGuru judge offline — no
browser, no agent, just the persisted trajectory. Every judge
hyperparameter (model, base URL, ``max_images``, ``image_scale``) can
be swept without touching the original results.

Usage::

    uv run python -m shop_guru.eval.rejudge \\
        outputs/shop_guru/mock_shop/2026-04-21_18-15-34_...-all \\
        --max-images 10 --image-scale 0.5

The script writes one aggregate JSON under the study dir
(``rejudge_<ts>_imgs<n>_scale<s>.json``) with per-episode old-vs-new
verdicts plus a summary row. Multiple invocations with different flags
produce sibling files and never clobber.

All the heavy lifting — loading the episode and running the judge —
lives in :mod:`shop_guru.eval.score`. This module is the CLI and the
aggregation shell around it.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from shop_guru._dotenv import load_project_env
from shop_guru._paths import repo_root
from shop_guru.cli import _default_config

from .judge import JudgementResult
from .loader import load_shopguru_tasks
from .score import (
    EpisodeData,
    JudgeConfig,
    build_result_row,
    build_results_envelope,
    judge_episode,
    load_episode,
)

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = "gpt-5"


# ---------------------------------------------------------------------------
# Episode discovery
# ---------------------------------------------------------------------------


def _discover_episodes(study_dir: Path) -> list[Path]:
    """Every subdir that contains an ``exp_args.pkl`` is an episode."""
    episodes: list[Path] = []
    for entry in sorted(study_dir.iterdir()):
        if entry.is_dir() and (entry / "exp_args.pkl").exists():
            episodes.append(entry)
    return episodes


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------


def _load_summary(episode_dir: Path) -> dict[str, Any]:
    """Read ``summary_info.json`` if present; return ``{}`` otherwise.

    ``build_result_row`` uses the dict to pull ``n_steps``, ``err_msg``,
    ``terminal_role``, ``forced_by_budget``, etc. — any field the rejudge
    row inherits from the original run.
    """
    summary_path = episode_dir / "summary_info.json"
    if not summary_path.exists():
        return {}
    try:
        return json.loads(summary_path.read_text())
    except Exception as exc:
        logger.warning("could not read %s: %s", summary_path, exc)
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shop_guru-rejudge",
        description=(
            "Re-run the ShopGuru judge on a completed study directory, "
            "sweeping judge hyperparameters without a browser."
        ),
    )
    parser.add_argument(
        "study",
        type=Path,
        help="Path to the study directory (the one containing per-episode subdirs).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config(),
        help="Shops YAML (default: bundled featured_v1.yml).",
    )
    parser.add_argument(
        "--shop",
        default=None,
        help=(
            "Shop slug (default: infer from the study's parent directory "
            "name, e.g. outputs/shop_guru/<shop>/<study>)."
        ),
    )
    parser.add_argument(
        "--variant",
        choices=("sandbox", "real"),
        default=None,
        help=(
            "Benchmark variant. Default: infer from the study folder name "
            "(looks for '_sandbox' or '_real'); falls back to 'sandbox'."
        ),
    )
    parser.add_argument(
        "--task-id",
        action="append",
        default=None,
        help="Restrict to one or more episode task ids (repeatable).",
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help=f"Judge model (default: {DEFAULT_JUDGE_MODEL}).",
    )
    parser.add_argument(
        "--judge-api-key",
        default=None,
        help=(
            "Judge API key (default: $SHOPGURU_JUDGE_API_KEY, then "
            "$OPENAI_API_KEY)."
        ),
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=10,
        help="Max screenshots forwarded to the judge (default: 10).",
    )
    parser.add_argument(
        "--image-scale",
        type=float,
        default=1.0,
        help=(
            "Downscale factor for each screenshot before sending to the "
            "judge. Values in (0, 1) trigger a PIL resize; 1.0 (default) "
            "skips the resize entirely."
        ),
    )
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help="Parallel LLM calls via ThreadPoolExecutor (default: 1).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path for the aggregate JSON. Default: "
            "<study>/rejudge_<ts>_imgs<n>_scale<s>.json."
        ),
    )
    parser.add_argument(
        "--suffix",
        default=None,
        help=(
            "Optional suffix appended to the auto-generated output "
            "filename (before .json). Useful for tagging a sweep, e.g. "
            "--suffix no_gt. Ignored when --output is provided."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover episodes and print the plan; skip the LLM calls.",
    )
    return parser


def _infer_shop_and_variant(study: Path, explicit_shop: str | None) -> tuple[str, str]:
    """Recover (shop, variant) from ``outputs/shop_guru/<shop>/<study>``."""
    shop = explicit_shop or study.parent.name
    name = study.name
    if "real" in name:
        variant = "real"
    elif "sandbox" in name:
        variant = "sandbox"
    else:
        variant = "sandbox"
    return shop, variant


def _default_output(study: Path, config: JudgeConfig, suffix: str | None = None) -> Path:
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    scale_str = f"{config.image_scale:.2f}".replace(".", "p")
    stem = (
        f"rejudge_{ts}_imgs{config.max_images}"
        f"_scale{scale_str}_{config.model}"
    )
    if suffix:
        stem = f"{stem}_{suffix}"
    return study / f"{stem}.json"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Populate OPENAI_BASE_URL / API keys from the project `.env`
    # before any SDK client gets constructed.
    load_project_env()
    parser = _build_parser()
    args = parser.parse_args(argv)

    study = args.study.resolve()
    if not study.is_dir():
        parser.error(f"study dir does not exist: {study}")

    config_path = args.config.resolve()
    if not config_path.exists():
        parser.error(f"config file not found: {config_path}")

    shop, variant = _infer_shop_and_variant(study, args.shop)
    if args.variant is not None:
        variant = args.variant
    logger.info("inferred shop=%s variant=%s", shop, variant)

    benchmark_tasks = load_shopguru_tasks(
        config_path=config_path,
        benchmarks_root=repo_root() / "outputs" / "shop_guru",
        variant=variant,
        shops=[shop],
    )
    logger.info("loaded %d benchmark task(s) for shop=%s", len(benchmark_tasks), shop)

    episode_dirs = _discover_episodes(study)
    if not episode_dirs:
        parser.error(f"no episode subdirs found in {study}")

    id_filter = set(args.task_id) if args.task_id else None

    episodes: list[EpisodeData] = []
    for episode_dir in episode_dirs:
        data = load_episode(episode_dir, benchmark_tasks)
        if data is None:
            continue
        if id_filter is not None and data.task_id not in id_filter:
            continue
        episodes.append(data)

    if not episodes:
        parser.error("no episodes matched the filter — nothing to judge")

    config = JudgeConfig(
        model=args.judge_model,
        api_key=(
            args.judge_api_key
            or os.environ.get("SHOPGURU_JUDGE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        ),
        max_images=args.max_images,
        image_scale=args.image_scale,
    )

    logger.info(
        "rejudging %d episode(s) with model=%s max_images=%d image_scale=%.2f n_jobs=%d",
        len(episodes),
        config.model,
        config.max_images,
        config.image_scale,
        args.n_jobs,
    )

    if args.dry_run:
        for ep in episodes:
            logger.info(
                "[dry-run] task=%s terminal=%s prior_verdict=%s screenshots=%d",
                ep.task_id,
                ep.terminal_role,
                ep.prior_verdict,
                len(ep.screenshots_b64),
            )
        return 0

    output_path = (
        args.output.resolve()
        if args.output
        else _default_output(study, config, args.suffix)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Index benchmark_tasks once so every row can pick up shop_slug /
    # skill / type without re-scanning. build_result_row reads the
    # original summary_info.json for n_steps, err_msg, etc.
    task_index = {t["id"]: t for t in benchmark_tasks if t.get("id")}

    results: list[dict[str, Any]] = []
    start = time.time()
    total_episodes = len(episodes)

    def _run(ep: EpisodeData) -> dict[str, Any]:
        t0 = time.time()
        try:
            result = judge_episode(ep, config)
        except Exception as exc:
            logger.exception("rejudge failed for task=%s", ep.task_id)
            # Build a JudgementResult so the crash row has the same schema
            # (including ``prompt_messages``, ``raw_response``, etc.) as
            # the happy path. Every rejudge row is a full model_dump().
            result = JudgementResult(
                verdict=False,
                reasoning=None,
                failure_reason=f"rejudge crashed: {type(exc).__name__}: {exc}",
                model_used=config.model,
                error=traceback.format_exc(),
            )
        return build_result_row(
            task_id=ep.task_id,
            episode_dir=ep.episode_dir.name,
            task_spec=task_index.get(ep.task_id, {}),
            summary=_load_summary(ep.episode_dir),
            judgement=result.model_dump(),
            prior_verdict=ep.prior_verdict,
            screenshots_available=len(ep.screenshots_b64),
            elapsed_s=round(time.time() - t0, 2),
        )

    def _log_progress(row: dict[str, Any]) -> None:
        done = len(results)
        running_pass = sum(1 for r in results if r["verdict"])
        logger.info(
            "[rejudge] %d/%d done (pass=%d) task=%s new_verdict=%s prior=%s elapsed=%.1fs",
            done,
            total_episodes,
            running_pass,
            row["task_id"],
            row["verdict"],
            row["prior_verdict"],
            row["elapsed_s"],
        )

    if args.n_jobs <= 1:
        for ep in episodes:
            row = _run(ep)
            results.append(row)
            _log_progress(row)
    else:
        with ThreadPoolExecutor(max_workers=args.n_jobs) as pool:
            futures = {pool.submit(_run, ep): ep for ep in episodes}
            for fut in as_completed(futures):
                row = fut.result()
                results.append(row)
                _log_progress(row)

    results.sort(key=lambda r: r["task_id"])

    # Agreement matrix vs the original judgement — rejudge-specific and
    # lives alongside the canonical counts via ``extra_counts``.
    priors = [r for r in results if isinstance(r["prior_verdict"], bool)]
    prior_pass = sum(1 for r in priors if r["prior_verdict"])
    agreements = sum(1 for r in priors if r["prior_verdict"] == r["verdict"])
    flips_pass_to_fail = sum(
        1 for r in priors if r["prior_verdict"] and not r["verdict"]
    )
    flips_fail_to_pass = sum(
        1 for r in priors if not r["prior_verdict"] and r["verdict"]
    )
    prior_success_rate = (prior_pass / len(priors)) if priors else 0.0
    agreement_rate = (agreements / len(priors)) if priors else 0.0

    extra_counts = {
        "prior_pass": prior_pass,
        "prior_fail": len(priors) - prior_pass,
        "agreements": agreements,
        "flips_pass_to_fail": flips_pass_to_fail,
        "flips_fail_to_pass": flips_fail_to_pass,
        "missing_prior": len(results) - len(priors),
        "prior_success_rate": prior_success_rate,
        "agreement_rate": agreement_rate,
    }

    envelope = build_results_envelope(
        study=str(study),
        shop=shop,
        variant=variant,
        config={
            "model": config.model,
            "max_images": config.max_images,
            "image_scale": config.image_scale,
        },
        rows=results,
        elapsed_s=round(time.time() - start, 2),
        extra_counts=extra_counts,
    )

    output_path.write_text(json.dumps(envelope, indent=2, default=str))
    total = envelope["counts"]["total"]
    n_success = envelope["counts"]["n_success"]
    success_rate = envelope["counts"]["success_rate"]
    logger.info(
        "wrote %d result(s) to %s — n_success=%d/%d (success_rate=%.3f) "
        "agreements=%d/%d (agreement_rate=%.3f)",
        total,
        output_path,
        n_success,
        total,
        success_rate,
        agreements,
        len(priors),
        agreement_rate,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
