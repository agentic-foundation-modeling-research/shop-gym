"""Builds the AgentLab/bgym ``Benchmark`` wrapping our registered tasks."""

from __future__ import annotations

from dataclasses import dataclass

from agentlab.experiments.loop import EnvArgs as AgentLabEnvArgs
from browsergym.experiments.benchmark import Benchmark, HighLevelActionSetArgs


@dataclass
class ShopGuruEnvArgs(AgentLabEnvArgs):
    """``EnvArgs`` subclass whose only job is to live in *our* package.

    Joblib workers are fresh processes: they unpickle ``exp_args`` and
    call ``env_args.make_env`` without ever importing ``shop_guru.eval``.
    That means the bootstrap in :mod:`shop_guru.eval.__init__` doesn't
    run and ``gym.make("browsergym/shop_guru.<id>")`` raises
    ``NameNotFound``.

    By making ``env_args`` an instance of a class defined in
    ``shop_guru.eval.benchmark``, unpickling transitively imports
    ``shop_guru.eval`` in the worker, which runs ``_bootstrap_from_env``
    and re-registers the tasks from ``SHOPGURU_TASK_SPEC`` before
    ``make_env`` runs.

    We inherit from ``agentlab.experiments.loop.EnvArgs`` (not the
    browsergym one) so that ``Study._convert_env_args`` keeps our
    subclass as-is — it replaces anything matching only the bgym base
    with a fresh ``AgentLabEnvArgs``, which silently erased the
    subclass and re-introduced the NameNotFound bug.
    """


def _default_action_set_args() -> HighLevelActionSetArgs:
    # Same mix visualwebarena uses: bid-click, nav, tabs, infeasibility
    # report, plus chat for the terminal "done" message the judge waits
    # on. Vision-capable agents get all the locators they need.
    return HighLevelActionSetArgs(
        subsets=("chat", "bid", "nav", "tab", "infeas"),
        multiaction=False,
        strict=False,
        retry_with_force=True,
        demo_mode="off",
    )


def build_shopguru_benchmark(
    gym_task_names: list[str],
    max_steps: int = 30,
    name: str = "shop_guru",
    seeds: list[int] | None = None,
) -> Benchmark:
    """Assemble a ``bgym.Benchmark`` covering the given registered tasks.

    Each task id must already be registered via
    :func:`register_shopguru_tasks`. ``backends=[]`` because our task
    class doesn't need any ``prepare_backend`` hook.
    """
    if not gym_task_names:
        raise ValueError("gym_task_names is empty — nothing to benchmark")

    fixed_seeds = seeds if seeds is not None else [0]
    env_args_list = [
        ShopGuruEnvArgs(
            task_name=task_name,
            task_seed=int(seed),
            max_steps=max_steps,
            headless=True,
            record_video=False,
            wait_for_user_message=False,
            viewport=None,
            slow_mo=None,
            storage_state=None,
            task_kwargs=None,
        )
        for task_name in gym_task_names
        for seed in fixed_seeds
    ]

    return Benchmark(
        name=name,
        high_level_action_set_args=_default_action_set_args(),
        is_multi_tab=False,  # SandboxShops don't rely on multi-tab flows
        supports_parallel_seeds=True,
        backends=[],
        env_args_list=env_args_list,
    )


__all__ = ["ShopGuruEnvArgs", "build_shopguru_benchmark"]
