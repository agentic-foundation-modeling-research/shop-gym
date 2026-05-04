"""CLI driver: load ShopGuru tasks, register them, run an AgentLab Study.

This module wires everything together end-to-end:

1. Loads + filters ShopGuru benchmark tasks via :func:`load_shopguru_tasks`.
2. Writes the task list to a temp JSON file and exports the env vars that
   :mod:`shop_guru.eval.__init__` reads on import — this is how worker
   processes (joblib) re-register the same tasks without IPC.
3. Registers the tasks in the current process, builds a ``bgym.Benchmark``,
   then kicks off an AgentLab ``Study`` with the agent selected by
   ``--model`` (see :mod:`shop_guru.eval.models`). The agent's base URL
   is threaded through :class:`CustomAIModelArgs` — no env vars.

Usage::

    uv run python -m shop_guru.eval.run --shop mock_shop --skill e2e
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from shop_guru._dotenv import load_project_env
from shop_guru._paths import repo_root
from shop_guru.cli import _default_config

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = "gpt-5"

# The judge only fires when the last chat message has role "assistant"
# (send_msg_to_user) or "infeasible" (report_infeasible). The base agent
# configs in shop_guru.eval.models ship with subsets=("bid",) and no
# extra_instructions, so the agent never sees either terminator and
# episodes that hit the step budget silently score 0 with no judgement
# attached.
SHOPGURU_AGENT_SUBSETS = ("chat", "infeas", "bid", "nav", "tab")

SHOPGURU_TERMINAL_INSTRUCTIONS = """\
You MUST end every episode with exactly one of these two terminal actions —
there is no other way to finish:

- `send_msg_to_user("<one- or two-sentence summary of what you did and any \
answer the task asked for>")` — call this as soon as you believe the goal is \
met. Once called, the episode ends and a judge inspects the trace.
- `report_infeasible("<short reason>")` — call this when the goal is \
genuinely impossible (e.g., the item doesn't exist, the page is broken).

Hard rules:
1. The episode has a strict step budget. If you run out of steps without \
calling one of the terminators above, the task is recorded as a failure and \
no judgement runs. Err on the side of sending `send_msg_to_user` early with \
your best answer rather than exploring indefinitely.
2. Do not keep clicking or scrolling after the goal is satisfied — stop and \
call `send_msg_to_user`.
3. A single dead end (404, missing element) is not enough to declare the task \
infeasible. Back out and try another path first. Only use `report_infeasible` \
after you have made a genuine attempt and confirmed no path works.
"""


def _configure_shopguru_agent(base_agent_args: Any) -> Any:
    """Return a :class:`ShopGuruGenericAgentArgs` with a terminal-aware action set.

    Deep-copies the supplied base agent args so we never mutate the
    module-level singleton in :mod:`shop_guru.eval.models`, then rebuilds
    it as a :class:`~shop_guru.eval.agent.ShopGuruGenericAgentArgs`. The
    subclass tacks memory + plan onto ``AgentInfo.extra_info`` per step
    so the offline judge can reconstruct the trajectory from step pickles
    without a GenericAgent monkey-patch.
    """
    from browsergym.experiments.benchmark import HighLevelActionSetArgs

    from .agent import ShopGuruGenericAgentArgs

    agent_args = copy.deepcopy(base_agent_args)
    current = agent_args.flags.action.action_set
    agent_args.flags.action.action_set = HighLevelActionSetArgs(
        subsets=SHOPGURU_AGENT_SUBSETS,
        multiaction=current.multiaction,
    )
    agent_args.flags.extra_instructions = SHOPGURU_TERMINAL_INSTRUCTIONS
    agent_args.flags.use_memory = True
    agent_args.flags.use_hints = False
    agent_args.flags.obs.use_past_error_logs = True
    # Rebuild as the ShopGuru subclass so Study dispatches to our
    # get_action override. __post_init__ on GenericAgentArgs computes
    # agent_name from chat_model_args.model_name.
    return ShopGuruGenericAgentArgs(
        chat_model_args=agent_args.chat_model_args,
        flags=agent_args.flags,
        max_retry=agent_args.max_retry,
    )


def _build_task_lookup(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index tasks by id so the ExpArgs swap can look up the matching dict.

    ``env_args.task_name`` is the registered gym id
    ``"shop_guru.<task_id>"``; stripping the prefix yields the key.
    """
    return {t["id"]: t for t in tasks if t.get("id")}


def _to_shopguru_exp_args(
    exp_args: Any,
    args: argparse.Namespace,
    task_lookup: dict[str, dict[str, Any]],
) -> Any:
    """Wrap a plain ``ExpArgs`` in our :class:`ShopGuruExpArgs` subclass.

    Preserves every field Study set on the original (agent_args,
    env_args, logging levels, order), then attaches the judge config
    + the matching task dict so the post-episode hook can run.
    """
    from .exp_args import ShopGuruExpArgs

    task_name = getattr(exp_args.env_args, "task_name", "") or ""
    task_id = task_name.split(".", 1)[1] if "." in task_name else None
    shop_task = task_lookup.get(task_id, {}) if task_id else {}
    if not shop_task:
        logger.warning(
            "no shop_task dict found for task_name=%r; post-episode judge "
            "will skip this episode",
            task_name,
        )

    new_args = ShopGuruExpArgs(
        agent_args=exp_args.agent_args,
        env_args=exp_args.env_args,
        logging_level=exp_args.logging_level,
        logging_level_stdout=exp_args.logging_level_stdout,
        judge_model=args.judge_model,
        judge_api_key=os.environ.get("SHOPGURU_JUDGE_API_KEY"),
        judge_max_images=args.max_images,
        judge_image_scale=args.image_scale,
        shop_task=shop_task,
    )
    # Preserve the order the planner assigned so dependency ordering
    # (if any) stays intact. Study sets this after constructing ExpArgs.
    if getattr(exp_args, "order", None) is not None:
        new_args.order = exp_args.order
    return new_args


def _surface_judgement_in_summary(results_dir: Path) -> int:
    """Safety net: lift per-episode task_info into each summary_info.json.

    :class:`~shop_guru.eval.exp_args.ShopGuruExpArgs` writes the
    judgement + ShopGuru metadata into ``summary_info.json`` as its
    post-episode hook, so in the happy path this pass is a no-op. We
    still run it after the study for episodes where the hook crashed
    (or for legacy study dirs created before this refactor): walking
    the step pickles lets us at least surface the task metadata even
    when the judgement itself is missing.

    Returns the number of summary files updated.
    """
    import gzip
    import pickle

    updated = 0
    if not results_dir.exists():
        return 0

    for summary_path in results_dir.rglob("summary_info.json"):
        episode_dir = summary_path.parent
        step_files = sorted(
            episode_dir.glob("step_*.pkl.gz"),
            key=lambda p: int(p.stem.split("_")[1].split(".")[0]),
        )
        if not step_files:
            continue
        try:
            with gzip.open(step_files[-1], "rb") as fh:
                final_step = pickle.load(fh)
        except Exception as exc:
            logger.warning("could not load %s: %s", step_files[-1], exc)
            continue

        task_info = getattr(final_step, "task_info", None) or {}
        if not isinstance(task_info, dict) or not task_info:
            continue

        try:
            summary = json.loads(summary_path.read_text())
        except Exception as exc:
            logger.warning("could not read %s: %s", summary_path, exc)
            continue

        # Shallow-merge: keep AgentLab's fields and any keys the
        # post-episode hook already wrote, add whatever's missing.
        # ``judgement`` stays in the list so older pickles (that still
        # had the inline judge stamping task_info) continue to surface.
        # ``url_trajectory`` is omitted — the task no longer writes it;
        # downstream readers reconstruct it from step pickles via
        # ``score._extract_url_trajectory_from_steps``.
        for key in (
            "judgement",
            "forced_by_budget",
            "terminal_role",
            "n_validate_calls",
            "max_steps",
            "shopguru_task_id",
            "shopguru_task_type",
        ):
            if key in task_info and key not in summary:
                summary[key] = task_info[key]

        summary_path.write_text(json.dumps(summary, indent=4, default=str))
        updated += 1

    logger.info("promoted judgement into %d summary_info.json file(s)", updated)
    return updated


def _build_parser(
    *,
    prog: str = "shop_guru-agentlab",
    description: str = "Run ShopGuru benchmarks through AgentLab + BrowserGym.",
    include_task_id: bool = True,
    default_n_jobs: int = 1,
) -> argparse.ArgumentParser:
    """Shared argparse for run.py and run_all.py.

    ``include_task_id`` is False for the all-tasks driver, which has no
    reason to expose a single-task filter. ``default_n_jobs`` lets the
    all-tasks driver opt into parallel execution without changing
    run.py's sequential default.
    """
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config(),
        help="Shops YAML (default: bundled default.yaml).",
    )
    parser.add_argument(
        "--shop",
        required=True,
        help=(
            "Shop slug to evaluate. Required — every invocation is scoped "
            "to a single shop so results group cleanly under "
            "<results-dir>/<shop>/."
        ),
    )
    parser.add_argument(
        "--skill",
        action="append",
        help=(
            "Restrict to one or more skill names (repeatable). Pass "
            "`--skill all` as a single value to run every skill available "
            "for the shop and tag the study folder with `_all`; `all` "
            "cannot be combined with other --skill values."
        ),
    )
    if include_task_id:
        parser.add_argument(
            "--task-id",
            action="append",
            help="Restrict to one or more task ids (repeatable).",
        )
    # MODEL_CHOICES / DEFAULT_MODEL are plain strings — importing them
    # does NOT trigger any agentlab imports, which matters because
    # _build_parser runs before _resolve_environment sets
    # AGENTLAB_EXP_ROOT. The actual agent construction happens later
    # via build_agent() inside _execute_study.
    from shop_guru.eval.models import DEFAULT_MODEL, MODEL_CHOICES

    parser.add_argument(
        "--model",
        choices=MODEL_CHOICES,
        default=DEFAULT_MODEL,
        help=(
            f"Agent model to evaluate. Resolved against "
            f"shop_guru.eval.models.build_agent() (default: {DEFAULT_MODEL})."
        ),
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help=f"Judge model name (default: {DEFAULT_JUDGE_MODEL}).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=30,
        help="Max steps per episode (default: 30).",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=10,
        help="Max screenshots forwarded to the judge per episode (default: 10).",
    )
    parser.add_argument(
        "--image-scale",
        type=float,
        default=1.0,
        help=(
            "Downscale factor for screenshots before they reach the judge. "
            "Values in (0, 1) trigger a PIL resize per screenshot; 1.0 "
            "(default) skips the resize entirely."
        ),
    )
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=default_n_jobs,
        help=(
            "Parallel workers. 1 = sequential, >1 = joblib "
            f"(default: {default_n_jobs})."
        ),
    )
    parser.add_argument(
        "--n-relaunch",
        type=int,
        default=3,
        help=(
            "Number of retry rounds for failed/incomplete tasks. Tasks "
            "cancelled by --avg-step-timeout count as incomplete, so a "
            "value of >=2 lets a hung task get retry rounds before "
            "being abandoned (default: 3)."
        ),
    )
    parser.add_argument(
        "--avg-step-timeout",
        type=int,
        default=90,
        help=(
            "Per-step wallclock budget in seconds. The total episode cap "
            "is max_steps * avg_step_timeout (30 * 90 = 2700s by "
            "default). Only enforced under the ray backend (n_jobs > 1); "
            "ray cancels tasks that exceed the cap, so hangs in Playwright "
            "or rate-limited LLM calls don't stall the study indefinitely "
            "(default: 90)."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help=(
            "task_seed threaded into every ShopGuruEnvArgs. Changes the "
            "study folder's episode names (AgentLab bakes the seed into "
            "`{agent}_on_{task}_{seed}`) so repeated invocations with "
            "different seeds land in sibling dirs without collisions. "
            "Loop externally to collect multiple generations (default: 0)."
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=(
            "Where AgentLab writes study results. Sets $AGENTLAB_EXP_ROOT. "
            "Defaults to <repo-root>/outputs/shop_guru."
        ),
    )
    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        default=True,
        help="Run the browser headless (default).",
    )
    parser.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        help="Run the browser with a visible window.",
    )
    return parser


def _resolve_environment(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[Path, Path]:
    """Validate CLI paths and export env vars needed before agentlab imports.

    Also normalizes ``args.skill`` into two derived attributes used
    downstream: ``args.skill_filter`` (list passed to the loader — None
    means "no filter") and ``args.skill_tokens`` (labels appended to the
    study folder suffix).

    Returns ``(config_path, results_dir)``. Both are resolved absolute
    paths. Must be called before any ``agentlab.*`` import because
    AgentLab reads ``AGENTLAB_EXP_ROOT`` at import time.
    """
    config_path = args.config.resolve()
    if not config_path.exists():
        parser.error(f"config file not found: {config_path}")

    # Normalize the --skill flag. `all` is a sentinel meaning "no filter,
    # but tag the study folder explicitly" so scripted sweeps can pass a
    # uniform --skill value for every invocation.
    raw_skills = args.skill or []
    if "all" in raw_skills:
        if len(raw_skills) > 1:
            parser.error(
                "--skill all cannot be combined with other --skill values"
            )
        args.skill_filter = None
        args.skill_tokens = ["all"]
    else:
        args.skill_filter = raw_skills or None
        args.skill_tokens = sorted(raw_skills)

    # Default results land in the repo-wide outputs/ tree (already gitignored)
    # alongside other generated artifacts (outputs/shops/, ...).
    results_root = (
        args.results_dir or repo_root() / "outputs" / "shop_guru"
    ).resolve()
    # One subdir per shop so studies across shops don't interleave timestamps.
    results_dir = results_root / args.shop
    results_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AGENTLAB_EXP_ROOT"] = str(results_dir)
    logger.info("AGENTLAB_EXP_ROOT=%s", results_dir)
    return config_path, results_dir


def _prepare_tasks(
    args: argparse.Namespace,
    config_path: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load + filter tasks, persist the spec for workers, register them.

    Returns ``(tasks, gym_task_names)`` — the task dicts (with
    ``shop_slug``/``skill`` injected) and the registered gym ids in
    matching order.
    """
    # Deferred so the base-url override above is in place first.
    from shop_guru.eval import load_shopguru_tasks, register_shopguru_tasks

    tasks = load_shopguru_tasks(
        config_path=config_path,
        benchmarks_root=repo_root() / "outputs" / "shop_guru",
        shops=[args.shop],
        skills=args.skill_filter,
        task_ids=getattr(args, "task_id", None),
    )
    if not tasks:
        raise SystemExit("no tasks matched the given filters — nothing to run")

    # Persist the task list so worker processes can re-register by reading
    # the env vars that shop_guru.eval.__init__ watches. delete=False is
    # required so the file survives until workers read it.
    spec_file = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="w",
        suffix=".json",
        prefix="shopguru_tasks_",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(tasks, spec_file)
        spec_file.flush()
    finally:
        spec_file.close()
    spec_path = Path(spec_file.name)

    os.environ["SHOPGURU_TASK_SPEC"] = str(spec_path)
    os.environ["SHOPGURU_JUDGE_MODEL"] = args.judge_model
    os.environ["SHOPGURU_MAX_STEPS"] = str(args.max_steps)
    os.environ["SHOPGURU_IMAGE_SCALE"] = str(args.image_scale)
    # Don't override SHOPGURU_JUDGE_API_KEY if already present; the judge
    # falls back to OPENAI_API_KEY when neither is set.

    gym_task_names = register_shopguru_tasks(tasks, max_steps=args.max_steps)
    logger.info("running %d shop_guru task(s): %s", len(gym_task_names), gym_task_names)
    return tasks, gym_task_names


def _execute_study(
    args: argparse.Namespace,
    gym_task_names: list[str],
    tasks: list[dict[str, Any]],
    *,
    stdout_log_level: int = logging.INFO,
    show_progress: bool = False,
) -> Any:
    """Build the benchmark + agent and run the AgentLab study. Returns the Study.

    ``stdout_log_level`` is threaded through to every ``ExpArgs.run()``
    worker via AgentLab's ``Study``. ``show_progress`` pins ``study.dir``
    before ``run()`` starts and spawns a tqdm watcher thread that polls
    for new ``summary_info.json`` files — useful when the caller has
    silenced INFO logs and wants just "X/N done" in the terminal.

    Once ``Study`` has built its default ``exp_args_list`` (plain
    :class:`ExpArgs`), each entry is swapped for a
    :class:`~shop_guru.eval.exp_args.ShopGuruExpArgs` carrying the judge
    config + the matching task dict. The subclass invokes the judge as
    a post-episode hook (see ``docs/arch.md``).
    """
    from shop_guru.eval import build_shopguru_benchmark

    benchmark = build_shopguru_benchmark(
        gym_task_names=gym_task_names,
        max_steps=args.max_steps,
        seeds=[args.seed],
    )
    for env_args in benchmark.env_args_list:
        env_args.headless = args.headless
        env_args.viewport = {"width": 1280, "height": 800}

    # Deferred import: agentlab.experiments.study reads AGENTLAB_EXP_ROOT
    # at module load, so it has to wait until _resolve_environment has
    # run. The agent's base_url is threaded in explicitly via
    # CustomAIModelArgs / CustomAnthropicModelArgs.
    from agentlab.experiments.study import Study

    from shop_guru.eval.models import build_agent

    agent_args = _configure_shopguru_agent(build_agent(args.model))

    # Study folder carries any --skill filter so sibling runs on the same
    # shop are self-describing. `args.skill_tokens` is [] when no filter
    # was passed, ["all"] for the explicit sentinel, or the sorted skill
    # names otherwise.
    study_suffix = "_".join(args.skill_tokens)

    study = Study(
        agent_args=[agent_args],
        benchmark=benchmark,
        logging_level_stdout=stdout_log_level,
        suffix=study_suffix,
        avg_step_timeout=args.avg_step_timeout,
    )

    # Swap every plain ExpArgs for a ShopGuruExpArgs so each episode
    # kicks off the post-episode judge hook when its run() returns.
    task_lookup = _build_task_lookup(tasks)
    study.exp_args_list = [
        _to_shopguru_exp_args(ea, args, task_lookup) for ea in study.exp_args_list
    ]

    # Ray is the only backend with working per-task timeouts: AgentLab
    # disables its joblib SIGALRM path because it can't kill Playwright
    # sync calls reliably (see exp_utils.run_exp). ray.cancel(force=True)
    # actually terminates the worker, so a hung click()/observation can
    # be reaped after avg_step_timeout * max_steps.
    parallel_backend = "sequential" if args.n_jobs == 1 else "ray"

    run_kwargs = {
        "n_jobs": args.n_jobs,
        "parallel_backend": parallel_backend,
        "n_relaunch": args.n_relaunch,
    }

    if not show_progress:
        study.run(**run_kwargs)
        return study

    import threading

    # Pin the study dir up front so the watcher thread has a fixed
    # location to poll. make_dir() is a no-op on subsequent calls.
    study.make_dir()
    total = len(benchmark.env_args_list)
    stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_progress,
        args=(study.dir, total, stop),
        daemon=True,
    )
    watcher.start()
    try:
        study.run(**run_kwargs)
    finally:
        stop.set()
        watcher.join(timeout=5)
    return study


def _watch_progress(study_dir: Path, total: int, stop: Any) -> None:
    """Poll ``study_dir`` for episode summaries and update a tqdm bar.

    Runs in a daemon thread. ``stop`` is a ``threading.Event`` the caller
    signals when the study finishes (or crashes).
    """
    from tqdm import tqdm

    pbar = tqdm(total=total, desc="shop_guru tasks", unit="task", leave=True)
    last = 0
    try:
        while not stop.is_set():
            count = sum(1 for _ in study_dir.rglob("summary_info.json"))
            if count > last:
                pbar.update(count - last)
                last = count
            if stop.wait(2.0):
                break
        # Final sync — catches any summaries written between the last
        # poll and the stop signal.
        count = sum(1 for _ in study_dir.rglob("summary_info.json"))
        if count > last:
            pbar.update(count - last)
    finally:
        pbar.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Populate OPENAI_BASE_URL / ANTHROPIC_BASE_URL / API keys from
    # the project `.env` before any SDK client gets constructed.
    load_project_env()
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path, results_dir = _resolve_environment(args, parser)
    try:
        tasks, gym_task_names = _prepare_tasks(args, config_path)
    except SystemExit as exc:
        logger.error("%s", exc)
        return 2

    _execute_study(args, gym_task_names, tasks)
    _surface_judgement_in_summary(results_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
