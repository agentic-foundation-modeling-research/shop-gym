"""Command-line runner for solving ShopGuru explorer-generated tasks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from shop_guru.solver import Solver

PROG = "python packages/shop_guru/solver.py"
REPO_ROOT = Path(__file__).parent.parent.parent.expanduser().resolve()
DEFAULT_TIMEOUT_SECONDS = 5 * 60
DEFAULT_MAX_STEPS = 20


def main(argv: list[str] | None = None) -> int:
    """Run solver agents for generated task configs.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. ``0`` on success.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    task_config_dir = args.task_config_dir or args.task_gen_dir / "task_configs"
    solutions_dir = args.solutions_dir or args.task_gen_dir / "solutions"
    configs = load_task_configs(task_config_dir, task_ids=args.task_id)

    solve_tasks(
        configs,
        solutions_dir=solutions_dir,
        website_url=args.website_url,
        website_nickname=args.website_nickname,
        cwd=args.cwd,
        timeout_seconds=args.timeout_seconds,
        max_steps=args.max_steps,
        max_tasks=args.max_tasks,
        build_only=args.build_only,
        force=args.force,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Solve ShopGuru explorer-generated task configs with a Pi agent.",
    )
    parser.add_argument(
        "--task-gen-dir",
        type=Path,
        required=True,
        help="Task-generation directory containing task_configs/.",
    )
    parser.add_argument(
        "--task-config-dir",
        type=Path,
        default=None,
        help="Explicit task config directory. Defaults to <task-gen-dir>/task_configs.",
    )
    parser.add_argument(
        "--solutions-dir",
        type=Path,
        default=None,
        help="Directory for solver artifacts. Defaults to <task-gen-dir>/solutions.",
    )
    parser.add_argument(
        "--website-url",
        required=True,
        help="Hosted storefront origin to solve against.",
    )
    parser.add_argument(
        "--website-nickname",
        required=True,
        help="Stable nickname used inside task verifier URLs.",
    )
    parser.add_argument(
        "--task-id",
        type=int,
        action="append",
        default=None,
        help="Task id to solve. May be passed multiple times. Defaults to all tasks.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=REPO_ROOT,
        help=f"Working directory for the agent process. Default: {REPO_ROOT}.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-task agent timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help=f"Maximum solver actions per task. Default: {DEFAULT_MAX_STEPS}.",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="Maximum number of supported tasks to solve after filtering. Defaults to all.",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Only write prompt artifacts; do not invoke Pi.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild and rerun tasks even when answer.json already exists.",
    )
    return parser


def load_task_configs(
    task_config_dir: Path,
    *,
    task_ids: list[int] | None,
) -> list[dict[str, Any]]:
    """Load explorer-generated task configs sorted by numeric task id."""
    if not task_config_dir.exists():
        raise FileNotFoundError(f"Task config directory does not exist: {task_config_dir}")

    selected_ids = set(task_ids) if task_ids is not None else None
    configs: list[dict[str, Any]] = []
    for config_path in sorted(task_config_dir.glob("*.json"), key=task_config_sort_key):
        config = load_task_config(config_path)
        task_id = config["task_id"]
        if selected_ids is not None and task_id not in selected_ids:
            continue
        configs.append(config)
    return configs


def task_config_sort_key(path: Path) -> tuple[int, str]:
    """Sort numeric task config file names before non-numeric names."""
    try:
        return int(path.stem), path.stem
    except ValueError:
        return sys.maxsize, path.stem


def load_task_config(config_path: Path) -> dict[str, Any]:
    """Load and validate one generated task config."""
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    if not isinstance(config, dict):
        raise ValueError(f"Expected task config object in {config_path}")
    if not isinstance(config.get("task_id"), int):
        raise ValueError(f"Expected integer task_id in {config_path}")
    if not isinstance(config.get("goal"), str):
        raise ValueError(f"Expected string goal in {config_path}")
    if not isinstance(config.get("eval"), list):
        raise ValueError(f"Expected eval list in {config_path}")
    return config


def solve_tasks(
    configs: list[dict[str, Any]],
    *,
    solutions_dir: Path,
    website_url: str,
    website_nickname: str,
    cwd: Path,
    timeout_seconds: int,
    max_steps: int,
    max_tasks: int | None,
    build_only: bool,
    force: bool,
) -> None:
    """Build prompts and optionally invoke the solver for supported tasks."""
    solver = Solver(
        solutions_dir,
        website_url=website_url,
        website_nickname=website_nickname,
        max_steps=max_steps,
    )
    attempted_tasks = 0
    for config in configs:
        task_id = config["task_id"]
        if has_fuzzy_match(config):
            print(f"Skipping task {task_id}: fuzzy_match eval is not supported yet.")
            continue

        if max_tasks is not None and attempted_tasks >= max_tasks:
            break

        answer_path = solutions_dir / str(task_id) / "answer.json"
        if answer_path.exists() and not force:
            print(f"Skipping task {task_id}: answer already exists.")
            continue

        attempted_tasks += 1
        prompt_path = solver.build_prompt(config)
        print(f"Built prompt for task {task_id}: {prompt_path}")
        if build_only:
            continue

        solved = solver.solve(config, cwd=cwd, timeout=timeout_seconds)
        if not solved:
            raise RuntimeError(f"Solver did not produce expected artifacts for task {task_id}")


def has_fuzzy_match(config: dict[str, Any]) -> bool:
    """Return whether a task config uses a fuzzy string matcher."""
    for eval_item in config.get("eval", []):
        if not isinstance(eval_item, dict):
            continue
        if eval_item.get("eval_type") != "string_match":
            continue
        reference_answer = eval_item.get("reference_answer")
        if isinstance(reference_answer, dict) and "fuzzy_match" in reference_answer:
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
