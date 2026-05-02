"""Shared scoring path: load an episode from disk and run the judge.

The live harness (:class:`shop_guru.eval.exp_args.ShopGuruExpArgs`) and
the offline driver (:mod:`shop_guru.eval.rejudge`) both call into this
module. The task object itself no longer invokes the judge — everything
the judge needs is persisted to ``exp_dir`` by AgentLab's
``ExpArgs.run()``:

- Per-step action + agent reasoning: ``step_*.pkl.gz`` (``StepInfo``).
- Per-step screenshots: ``screenshot_step_*.png``.
- Goal text: ``goal_object.pkl.gz``.
- Task metadata + URL trajectory: merged into ``summary_info.json`` by
  ``ExpArgs.save_summary_info`` from the task's ``task_info``.

Memory + plan reach the step pickles via
:class:`shop_guru.eval.agent.ShopGuruGenericAgent`, which copies them
into ``AgentInfo.extra_info`` before AgentLab pickles the step.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .judge import JudgementResult, judge_trace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trajectory helpers — rendering + disk walking
# ---------------------------------------------------------------------------


def render_trajectory(entries: list[dict[str, Any]]) -> list[str]:
    """Flatten trajectory entries into judge-friendly multi-line steps.

    Each entry becomes one block::

        [step N]
        think: ...
        memory: ...
        plan (step P): ...
        action: ...

    Missing fields are skipped. The output is passed to
    :func:`shop_guru.eval.judge.judge_trace` as ``agent_steps``.
    """
    out: list[str] = []
    for entry in entries:
        step = entry.get("step")
        parts = [f"[step {step}]"]
        if entry.get("think"):
            parts.append(f"think: {entry['think']}")
        if entry.get("memory"):
            parts.append(f"memory: {entry['memory']}")
        # AgentLab's GenericAgent initializes ``plan = "No plan yet"`` and
        # ``plan_step = -1`` and keeps that sentinel on every step until the
        # agent actually generates a plan. Skip the line in that case so the
        # judge prompt doesn't get "plan (step -1): No plan yet" noise.
        plan = entry.get("plan")
        plan_step = entry.get("plan_step")
        if plan and plan_step != -1 and plan != "No plan yet":
            parts.append(f"plan (step {plan_step}): {plan}")
        if entry.get("action"):
            parts.append(f"action: {entry['action']}")
        out.append("\n".join(parts))
    return out


def _render_agent_steps(chat_messages: list[dict[str, Any]]) -> list[str]:
    """Fallback: flatten chat.messages into plain-text steps.

    Only used when an episode has no step pickles (older runs, or a
    crash before the first step was saved). The live path always has
    step pickles.
    """
    steps: list[str] = []
    for msg in chat_messages:
        role = msg.get("role", "?")
        body = msg.get("message", "")
        if not body:
            continue
        steps.append(f"[{role}] {body}")
    return steps


def _apply_rule_gate(
    success_criteria: dict[str, Any] | None,
    url_trajectory: list[tuple[int, str]],
    terminal_role: str,
    model_used: str,
) -> JudgementResult | None:
    """Deterministic checks that can decide a verdict without the LLM.

    Two rules, applied in order:

    1. ``expected_outcome == "infeasible"`` — the task is supposed to be
       refused. Pass iff the agent reported infeasible. No LLM call.
    2. ``url_contains`` — the agent must have visited a URL containing
       the substring at some point. Mid-journey breadcrumb (collection,
       product, policy, /cart), not a final-URL requirement. Miss → fail
       without LLM. Hit → return ``None`` so the LLM still scores the
       semantic content (cart contents, intent satisfaction, etc.).

    Returns the decided ``JudgementResult`` or ``None`` to defer.
    """
    if not success_criteria:
        return None

    if success_criteria.get("expected_outcome") == "infeasible":
        agent_refused = terminal_role == "infeasible"
        return JudgementResult(
            verdict=agent_refused,
            reasoning=(
                "Rule: task expected infeasible; agent correctly refused."
                if agent_refused
                else "Rule: task expected infeasible but agent did not refuse."
            ),
            failure_reason=(
                None
                if agent_refused
                else (
                    success_criteria.get("infeasible_reason")
                    or "agent did not report infeasible"
                )
            ),
            model_used=model_used,
        )

    url_contains = success_criteria.get("url_contains")
    if url_contains:
        visited = any(url_contains in url for _, url in url_trajectory)
        if not visited:
            return JudgementResult(
                verdict=False,
                reasoning=(
                    f"Rule: agent never visited a URL containing {url_contains!r}."
                ),
                failure_reason=(
                    f"required URL checkpoint {url_contains!r} not in trajectory"
                ),
                model_used=model_used,
            )

    return None


# ---------------------------------------------------------------------------
# Episode loading
# ---------------------------------------------------------------------------


@dataclass
class EpisodeData:
    """Everything the judge needs to score one episode from disk."""

    episode_dir: Path
    task_id: str
    task_intent: str
    chat_messages: list[dict[str, Any]]
    url_trajectory: list[tuple[int, str]]
    trajectory: list[dict[str, Any]]
    screenshots_b64: list[str]
    final_result: str
    terminal_role: str  # "assistant" / "infeasible" / "budget" / "none"
    forced_by_budget: bool
    success_criteria: dict[str, Any] | None
    prior_verdict: bool | None  # previous judgement in summary_info.json, if any
    n_validate_calls: int
    max_steps: int | None


@dataclass
class JudgeConfig:
    model: str
    api_key: str | None
    max_images: int
    image_scale: float


def _load_pickle_gz(path: Path) -> Any:
    with gzip.open(path, "rb") as fh:
        return pickle.load(fh)


def _load_pickle(path: Path) -> Any:
    with open(path, "rb") as fh:
        return pickle.load(fh)


def _step_files(episode_dir: Path) -> list[Path]:
    """Return ``step_*.pkl.gz`` paths sorted by step index."""
    return sorted(
        episode_dir.glob("step_*.pkl.gz"),
        key=lambda p: int(p.stem.split("_")[1].split(".")[0]),
    )


def _load_screenshots(episode_dir: Path) -> list[str]:
    """Return base64-encoded PNGs for every screenshot, ordered by step."""
    screenshots: list[tuple[int, bytes]] = []
    for png in episode_dir.glob("screenshot_step_*.png"):
        try:
            idx = int(png.stem.removeprefix("screenshot_step_"))
        except ValueError:
            continue
        screenshots.append((idx, png.read_bytes()))
    screenshots.sort(key=lambda t: t[0])
    return [base64.b64encode(data).decode("ascii") for _, data in screenshots]


def _load_task_intent(episode_dir: Path) -> str:
    """Extract the goal text from ``goal_object.pkl.gz``.

    The pickle is a tuple of content blocks; we concatenate every
    ``{"type": "text", "text": ...}`` block to survive multimodal goals.
    """
    path = episode_dir / "goal_object.pkl.gz"
    if not path.exists():
        return ""
    goal = _load_pickle_gz(path)
    if isinstance(goal, str):
        return goal
    parts: list[str] = []
    if isinstance(goal, (list, tuple)):
        for block in goal:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if text:
                    parts.append(text)
    return "\n".join(parts)


def _load_task_name(episode_dir: Path) -> str | None:
    """Pull ``task_name`` from ``exp_args.pkl`` without importing shop_guru."""
    path = episode_dir / "exp_args.pkl"
    if not path.exists():
        return None
    try:
        exp_args = _load_pickle(path)
    except Exception as exc:
        logger.warning("could not load %s: %s", path, exc)
        return None
    env_args = getattr(exp_args, "env_args", None)
    return getattr(env_args, "task_name", None) if env_args else None


def _extract_url_trajectory_from_steps(episode_dir: Path) -> list[tuple[int, str]]:
    """Reconstruct ``(step, url)`` pairs from the persisted step pickles.

    BrowserGym includes ``"url": page.url`` in every observation dict
    (see ``browsergym.core.env``), so each ``StepInfo.obs["url"]`` is the
    URL the agent saw on that step. This replaces the old task-side
    ``_url_trajectory`` capture that shipped the same data through
    ``task_info``.
    """
    entries: list[tuple[int, str]] = []
    for path in _step_files(episode_dir):
        try:
            step_info = _load_pickle_gz(path)
        except Exception as exc:
            logger.debug("could not load %s: %s", path, exc)
            continue
        obs = getattr(step_info, "obs", None)
        if not isinstance(obs, dict):
            continue
        url = obs.get("url")
        if not url:
            continue
        step = getattr(step_info, "step", None)
        if not isinstance(step, int):
            continue
        entries.append((step, str(url)))
    return entries


def _extract_trajectory_from_steps(episode_dir: Path) -> list[dict[str, Any]]:
    """Walk ``step_*.pkl.gz`` and reconstruct per-step trajectory entries.

    For each pickled ``StepInfo``, pull:

    - ``action`` — the action string the agent emitted on that step.
    - ``agent_info["think"]`` — the per-step reasoning.
    - ``agent_info["extra_info"]["memory" | "plan" | "plan_step"]`` —
      pushed in by :class:`shop_guru.eval.agent.ShopGuruGenericAgent`.
      Older runs that used the monkey-patched recorder won't have them
      here; older runs that ran against a stock ``GenericAgent`` never
      had them at all. Both cases produce a ``None`` for those fields,
      which :func:`render_trajectory` silently drops.

    Returns entries in the same shape ``render_trajectory`` expects.
    """
    entries: list[dict[str, Any]] = []
    for path in _step_files(episode_dir):
        try:
            step_info = _load_pickle_gz(path)
        except Exception as exc:
            logger.debug("could not load %s: %s", path, exc)
            continue

        action = getattr(step_info, "action", None)
        # ``agent_info`` is an ``AgentInfo`` dataclass at pickle time, but
        # older runs (or an unexpected crash path) may have stored a
        # plain dict. ``.get(...)`` works for both — AgentInfo implements
        # it explicitly.
        agent_info = getattr(step_info, "agent_info", None)
        if agent_info is None:
            continue
        extra = agent_info.get("extra_info") if hasattr(agent_info, "get") else None
        if not isinstance(extra, dict):
            extra = {}

        # An action of None marks the post-termination step AgentLab
        # appends; nothing to score there. We also skip steps where both
        # action and think are absent (dummy init step before
        # from_action populated anything).
        think = agent_info.get("think") if hasattr(agent_info, "get") else None
        if action is None and not think:
            continue

        entries.append(
            {
                "step": getattr(step_info, "step", None),
                "think": think,
                "memory": extra.get("memory"),
                "plan": extra.get("plan"),
                "plan_step": extra.get("plan_step"),
                "action": action,
            }
        )
    return entries


def _final_chat_messages(episode_dir: Path) -> list[dict[str, Any]]:
    """Return ``chat.messages`` from the last step's observation.

    Only used to extract the terminal message (assistant/infeasible) and
    as a degenerate fallback when no step pickles contain usable data.
    """
    step_files = _step_files(episode_dir)
    if not step_files:
        return []
    try:
        final_step = _load_pickle_gz(step_files[-1])
    except Exception as exc:
        logger.warning("could not load %s: %s", step_files[-1], exc)
        return []
    obs = getattr(final_step, "obs", None) or {}
    if not isinstance(obs, dict):
        return []
    raw = obs.get("chat_messages") or ()
    return [dict(m) for m in raw]


_FORCED_TERMINATION_MESSAGE = (
    "[forced-termination] Agent exhausted the step budget without "
    "calling send_msg_to_user or report_infeasible. Judging on trace "
    "evidence only."
)


def _derive_final_result(
    chat_messages: list[dict[str, Any]], terminal_role: str
) -> str:
    """Best-effort ``final_result`` string when the task already declared its
    terminal role (via the final step's ``task_info``).

    - ``assistant``/``infeasible``: return the last matching chat message
      body (empty string if the role isn't present, which would be a
      bug, but keeps the judge call safe).
    - ``budget``: synthesize the same placeholder the live task used to
      produce, so the judge prompt is identical to the legacy path.
    """
    if terminal_role == "budget":
        return _FORCED_TERMINATION_MESSAGE
    for msg in reversed(chat_messages):
        if msg.get("role") == terminal_role:
            return msg.get("message", "") or ""
    return ""


def _extract_final_result(
    chat_messages: list[dict[str, Any]],
    max_steps: int | None,
    n_validate_calls: int,
) -> tuple[str, str, bool]:
    """Mirror the terminal-signal logic that lived in ``task.validate``.

    Returns ``(final_result, terminal_role, forced_by_budget)``. For
    episodes that ran out of budget without a terminator, synthesize the
    same "[forced-termination]" message the task used to construct so
    the judge sees identical inputs.
    """
    if chat_messages:
        last = chat_messages[-1]
        role = last.get("role", "")
        body = last.get("message", "")
        if role == "assistant":
            return body, "assistant", False
        if role == "infeasible":
            return body, "infeasible", False

    budget_exhausted = max_steps is not None and n_validate_calls >= max_steps
    if budget_exhausted:
        return _FORCED_TERMINATION_MESSAGE, "budget", True
    return "", "none", False


def _load_final_task_info(episode_dir: Path) -> dict[str, Any]:
    """Return the ``task_info`` dict from the last step pickle (or {}).

    This is the authoritative source for ShopGuru-side termination
    metadata (``terminal_role``, ``forced_by_budget``, ``max_steps``,
    ``n_validate_calls``, ``shopguru_task_id``). AgentLab's
    ``ExpArgs.save_summary_info`` does NOT merge per-step ``task_info``
    into ``summary_info.json``, so ``load_episode`` must read it off the
    step pickle directly — the summary-based fallback only catches
    studies that crashed before the final step was saved.
    """
    step_files = _step_files(episode_dir)
    if not step_files:
        return {}
    try:
        final = _load_pickle_gz(step_files[-1])
    except Exception as exc:
        logger.warning("could not load %s: %s", step_files[-1], exc)
        return {}
    task_info = getattr(final, "task_info", None)
    return task_info if isinstance(task_info, dict) else {}


def _lookup_benchmark_entry(
    task_id: str, benchmark_tasks: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for entry in benchmark_tasks:
        if entry.get("id") == task_id:
            return entry
    return None


def load_episode(
    episode_dir: Path, benchmark_tasks: list[dict[str, Any]]
) -> EpisodeData | None:
    """Reconstruct every input the judge needs, from ``episode_dir`` alone."""
    task_name = _load_task_name(episode_dir)
    task_id = task_name.split(".", 1)[1] if task_name and "." in task_name else None

    summary: dict[str, Any] = {}
    summary_path = episode_dir / "summary_info.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text())
        except Exception as exc:
            logger.warning("could not parse %s: %s", summary_path, exc)

    # Prefer task_info from the last step pickle — it's authoritative
    # for ShopGuru metadata that AgentLab doesn't merge into summary.
    final_task_info = _load_final_task_info(episode_dir)

    if task_id is None:
        task_id = final_task_info.get("shopguru_task_id") or summary.get(
            "shopguru_task_id"
        )
    if not task_id:
        logger.warning("skipping %s — no task id found", episode_dir.name)
        return None

    chat_messages = _final_chat_messages(episode_dir)
    trajectory = _extract_trajectory_from_steps(episode_dir)
    url_trajectory = _extract_url_trajectory_from_steps(episode_dir)

    raw_max_steps = final_task_info.get("max_steps", summary.get("max_steps"))
    max_steps = raw_max_steps if isinstance(raw_max_steps, int) else None
    n_validate_calls = int(
        final_task_info.get("n_validate_calls", summary.get("n_validate_calls") or 0)
        or 0
    )

    # If the task decided on a terminal role, trust it — `_extract_final_result`
    # is only there for legacy episodes whose step pickles don't carry task_info.
    task_terminal_role = final_task_info.get("terminal_role")
    if task_terminal_role in {"assistant", "infeasible", "budget"}:
        terminal_role = task_terminal_role
        forced_by_budget = bool(final_task_info.get("forced_by_budget", False))
        final_result = _derive_final_result(chat_messages, terminal_role)
    else:
        final_result, terminal_role, forced_by_budget = _extract_final_result(
            chat_messages, max_steps, n_validate_calls
        )

    bench_entry = _lookup_benchmark_entry(task_id, benchmark_tasks)
    if bench_entry is None:
        logger.warning(
            "no benchmark entry for task_id=%s — judging without success_criteria",
            task_id,
        )
        task_intent = _load_task_intent(episode_dir)
        success_criteria: dict[str, Any] | None = None
    else:
        task_intent = bench_entry.get("intent") or _load_task_intent(episode_dir)
        raw_criteria = bench_entry.get("success_criteria")
        success_criteria = raw_criteria if isinstance(raw_criteria, dict) else None

    screenshots_b64 = _load_screenshots(episode_dir)
    prior_verdict = None
    prior_judgement = summary.get("judgement")
    if isinstance(prior_judgement, dict):
        prior_verdict = prior_judgement.get("verdict")

    return EpisodeData(
        episode_dir=episode_dir,
        task_id=task_id,
        task_intent=task_intent,
        chat_messages=chat_messages,
        url_trajectory=url_trajectory,
        trajectory=trajectory,
        screenshots_b64=screenshots_b64,
        final_result=final_result,
        terminal_role=terminal_role,
        forced_by_budget=forced_by_budget,
        success_criteria=success_criteria,
        prior_verdict=prior_verdict,
        n_validate_calls=n_validate_calls,
        max_steps=max_steps,
    )


# ---------------------------------------------------------------------------
# Judging + summary writeback
# ---------------------------------------------------------------------------


def judge_episode(episode: EpisodeData, config: JudgeConfig) -> JudgementResult:
    """Score a loaded episode.

    Order of decisions:

    1. Rule gate over ``success_criteria`` — handles
       ``expected_outcome=infeasible`` (verdict mirrors agent refusal)
       and short-circuits ``url_contains`` misses to fail without an
       LLM call.
    2. ``terminal_role="infeasible"`` short-circuit — for tasks that
       weren't expected to be infeasible, an agent giving up is failure.
    3. ``terminal_role="none"`` short-circuit — episode ended with no
       terminator and the budget wasn't exhausted, so there's nothing
       to judge.
    4. LLM judge on intent + trajectory + screenshots.
    """
    rule_result = _apply_rule_gate(
        episode.success_criteria,
        episode.url_trajectory,
        episode.terminal_role,
        config.model,
    )
    if rule_result is not None:
        return rule_result

    if episode.terminal_role == "infeasible":
        return JudgementResult(
            verdict=False,
            reasoning="Agent reported the task as infeasible.",
            failure_reason=episode.final_result or "infeasible report from agent",
            model_used=config.model,
        )
    if episode.terminal_role == "none":
        return JudgementResult(
            verdict=False,
            reasoning=None,
            failure_reason=(
                "Episode ended without a terminator and step budget was not "
                "exhausted (or unknown). Nothing to judge."
            ),
            model_used=config.model,
        )

    if episode.trajectory:
        agent_steps = render_trajectory(episode.trajectory)
    else:
        # Degenerate fallback: no step pickles produced usable entries.
        # Render what we can from chat.messages so the judge at least
        # sees the terminal assistant message in context.
        agent_steps = _render_agent_steps(episode.chat_messages)

    return judge_trace(
        task=episode.task_intent,
        final_result=episode.final_result,
        agent_steps=agent_steps,
        screenshots_b64=episode.screenshots_b64,
        model=config.model,
        api_key=config.api_key,
        max_images=config.max_images,
        url_trajectory=episode.url_trajectory,
        image_scale=config.image_scale,
    )


# Fields from EpisodeData + JudgementResult that downstream consumers
# (aggregate.py, rejudge.py, the UI) read out of summary_info.json.
_SUMMARY_KEYS_FROM_EPISODE = (
    "forced_by_budget",
    "terminal_role",
    "n_validate_calls",
    "max_steps",
    "url_trajectory",
)


def merge_judgement_into_summary(
    episode_dir: Path, episode: EpisodeData, result: JudgementResult
) -> None:
    """Merge the judgement + ShopGuru metadata into ``summary_info.json``.

    Overwrites the ``judgement`` key unconditionally (this is the point
    of calling it) but only fills the metadata fields if they weren't
    already present. That lets a manually-edited summary survive a
    re-run of the scoring hook without getting clobbered.
    """
    summary_path = episode_dir / "summary_info.json"
    summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text())
        except Exception as exc:
            logger.warning("could not read %s: %s", summary_path, exc)
            summary = {}

    summary["judgement"] = result.model_dump()
    # Reward reflects the final verdict so downstream consumers that read
    # ``cum_reward`` (aggregate.py, AgentLab's own stat summaries) see a
    # meaningful 0/1 instead of the placeholder 0.0 task.validate returns.
    summary["cum_reward"] = 1.0 if result.verdict else 0.0
    summary["shopguru_task_id"] = episode.task_id
    summary.setdefault("forced_by_budget", episode.forced_by_budget)
    summary.setdefault("terminal_role", episode.terminal_role)
    summary.setdefault("n_validate_calls", episode.n_validate_calls)
    summary.setdefault("max_steps", episode.max_steps)
    if "url_trajectory" not in summary and episode.url_trajectory:
        summary["url_trajectory"] = [
            {"step": step, "url": url} for step, url in episode.url_trajectory
        ]

    summary_path.write_text(json.dumps(summary, indent=4, default=str))
    # Silence the unused-warning for documented-but-presently-unread keys;
    # keeping the tuple exported so future consumers (and tests) can
    # reference a single source of truth.
    _ = _SUMMARY_KEYS_FROM_EPISODE


# ---------------------------------------------------------------------------
# Shared result-row / envelope shape for results.json + rejudge_*.json
# ---------------------------------------------------------------------------

# Keys lifted verbatim from ``JudgementResult.model_dump()``. Listed
# explicitly so every row has the full set even when the judgement dict
# is empty (e.g. an episode where the hook crashed pre-LLM-call).
_JUDGEMENT_KEYS: tuple[str, ...] = (
    "verdict",
    "reasoning",
    "failure_reason",
    "impossible_task",
    "reached_captcha",
    "raw_response",
    "raw_payload",
    "model_used",
    "finish_reason",
    "usage",
    "error",
    "prompt_messages",
)


def build_result_row(
    *,
    task_id: str,
    episode_dir: str,
    task_spec: dict[str, Any],
    summary: dict[str, Any],
    judgement: dict[str, Any],
    prior_verdict: bool | None = None,
    screenshots_available: int | None = None,
    elapsed_s: float | None = None,
) -> dict[str, Any]:
    """Build the canonical per-task row used by results.json + rejudge_*.json.

    ``task_spec`` is an entry from :func:`load_shopguru_tasks` — carries
    ``shop_slug``, ``skill``, ``type``. ``summary`` is ``summary_info.json``
    contents (has ``n_steps``, ``terminal_role``, ``forced_by_budget``,
    ``err_msg``, etc.). ``judgement`` is ``JudgementResult.model_dump()``
    verbatim — the full evidence trail (reasoning, raw payload, prompt
    messages). Missing values surface as ``None`` so downstream diffs
    don't choke on absent keys.
    """
    verdict = judgement.get("verdict")
    row: dict[str, Any] = {
        # task identity
        "task_id": task_id,
        "shop_slug": task_spec.get("shop_slug"),
        "skill": task_spec.get("skill"),
        "task_type": summary.get("shopguru_task_type") or task_spec.get("type"),
        "episode_dir": episode_dir,
        # episode metadata
        "terminal_role": summary.get("terminal_role"),
        "forced_by_budget": (
            bool(summary["forced_by_budget"])
            if summary.get("forced_by_budget") is not None
            else None
        ),
        "n_steps": summary.get("n_steps"),
        "max_steps": summary.get("max_steps"),
        "screenshots_available": screenshots_available,
        "err_msg": summary.get("err_msg"),
        "elapsed_s": elapsed_s,
        # verdict signals (derived — success/reward mirror the recorded verdict
        # rather than ``cum_reward`` so live + rejudge rows stay consistent)
        "success": bool(verdict) if verdict is not None else False,
        "reward": 1.0 if verdict else 0.0,
        "prior_verdict": prior_verdict,
    }
    for key in _JUDGEMENT_KEYS:
        row[key] = judgement.get(key)
    return row


def build_results_envelope(
    *,
    study: str,
    shop: str,
    variant: str,
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    elapsed_s: float | None = None,
    extra_counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap a list of ``build_result_row`` rows in the shared envelope.

    ``counts`` is computed from ``rows`` — ``total``, ``n_success``,
    ``n_failed``, ``success_rate``. Anything in ``extra_counts`` is
    merged on top (rejudge uses this to add ``prior_pass``,
    ``agreements``, flip counts, etc.).
    """
    total = len(rows)
    n_success = sum(1 for r in rows if r.get("success"))
    counts: dict[str, Any] = {
        "total": total,
        "n_success": n_success,
        "n_failed": total - n_success,
        "success_rate": (n_success / total) if total else 0.0,
    }
    if extra_counts:
        counts.update(extra_counts)
    envelope: dict[str, Any] = {
        "study": study,
        "shop": shop,
        "variant": variant,
        "config": config,
        "counts": counts,
    }
    if elapsed_s is not None:
        envelope["elapsed_s"] = elapsed_s
    envelope["results"] = rows
    return envelope


__all__ = [
    "EpisodeData",
    "JudgeConfig",
    "build_result_row",
    "build_results_envelope",
    "judge_episode",
    "load_episode",
    "merge_judgement_into_summary",
    "render_trajectory",
]
