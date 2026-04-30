"""Prompt-template loader for the Phase 4 build harness loop.

Externalises the markdown bodies that
:mod:`shop_gen.build.loop.RunBuildHarnessLoopStep` (T5.6) hands to
:func:`harness.run_plan_exec_loop` as the agents constitution + planner
body + executor body. Spec §5.5.2 + §5.5.4.

Five files live next to this module under
:mod:`shop_gen.build.prompts` (the package directory):

* ``agents.md`` — the shared constitution rendered into
  :class:`harness.PlanExecLoopConfig.agents_md`. Returned verbatim.
* ``planner.md`` — the planner-iteration body rendered into
  :class:`harness.Prompts.planner`. Returned verbatim.
* ``execute.md`` — the executor body for every ``gen_*`` task and the
  mandatory final ``visual_fix`` task. The harness renders the
  ``{{verifier_feedback}}`` slot from the previous iteration's
  verifier dispatch (verifiers spec §5.5).
* ``quality_judge.md`` / ``cross_task_consistency.md`` /
  ``visual_judge.md`` — the ``str.format()`` templates the verifier
  dispatcher renders (T5.5; ``visual_judge`` per the visual-verifier
  spec §9.2).

The files are checked into the repo and considered API: changes flow
through prompt-engineering review, not silent edits to the loop driver.

Lookups are cached so repeated calls are free; the disk read happens
lazily on first use, keeping the parent package import-safe (no I/O at
module import time).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Final

_PROMPTS_DIR: Final[Path] = Path(__file__).resolve().parent / "prompts"
_AGENTS_FILE: Final[str] = "agents.md"
_PLANNER_FILE: Final[str] = "planner.md"
_EXECUTE_FILE: Final[str] = "execute.md"
_QUALITY_JUDGE_FILE: Final[str] = "quality_judge.md"
_CROSS_TASK_CONSISTENCY_FILE: Final[str] = "cross_task_consistency.md"
_VISUAL_JUDGE_FILE: Final[str] = "visual_judge.md"

VERIFIER_FEEDBACK_PLACEHOLDER: Final[str] = "{{verifier_feedback}}"
"""The placeholder the harness renders with verifier feedback (verifiers spec §5.5).

Re-exported so the build-loop driver and its tests can reference the
exact token string without re-deriving it.
"""


@cache
def load_agents_md() -> str:
    """Return the build-harness-loop AGENTS.md constitution.

    The whole file body is the agents-md text. The harness writes it
    verbatim into ``<run_dir>/AGENTS.md`` before the planner spawns; both
    the planner and every executor iteration reads it from there.

    Returns:
        The agents-md text, terminated by a single newline.

    Raises:
        FileNotFoundError: ``agents.md`` is missing.
    """
    return _read_prompt_file(_AGENTS_FILE)


@cache
def load_planner_prompt() -> str:
    """Return the planner-iteration prompt body.

    The whole file body is the planner prompt. The harness writes it
    into ``<run_dir>/prompts/planner.md`` and renders it as the planner
    iteration's tool-use body.

    Returns:
        The planner prompt text, terminated by a single newline.

    Raises:
        FileNotFoundError: ``planner.md`` is missing.
    """
    return _read_prompt_file(_PLANNER_FILE)


@cache
def load_execute_prompt() -> str:
    """Return the executor body for every ``gen_*`` task.

    Carries a ``{{verifier_feedback}}`` placeholder — the harness
    substitutes the previous iteration's verifier feedback into that
    slot before every executor invocation (verifiers spec §5.5).

    Returns:
        The executor prompt text, terminated by a single newline.

    Raises:
        FileNotFoundError: ``execute.md`` is missing.
        ValueError: The body is missing the
            ``{{verifier_feedback}}`` placeholder. The harness only
            injects feedback when the placeholder is present, so a
            silently dropped placeholder would mask retry failures.
    """
    body = _read_prompt_file(_EXECUTE_FILE)
    if VERIFIER_FEEDBACK_PLACEHOLDER not in body:
        raise ValueError(
            f"{_EXECUTE_FILE}: executor prompt must contain "
            f"the '{VERIFIER_FEEDBACK_PLACEHOLDER}' placeholder so the "
            "harness can inject prior-iteration verifier feedback "
            "(verifiers spec §5.5).",
        )
    return body


@cache
def load_quality_judge_prompt() -> str:
    """Return the ``str.format()`` template for the ``quality_judge`` verifier (T5.5).

    The template carries three slots:

    * ``{task_id}`` — selected task id at dispatch time.
    * ``{capabilities}`` — JSON-rendered ``capabilities.json`` body.
    * ``{source_blocks}`` — concatenated hydrogen source files for
      review.

    Returns:
        The template body, terminated by a single newline.

    Raises:
        FileNotFoundError: ``quality_judge.md`` is missing.
    """
    return _read_prompt_file(_QUALITY_JUDGE_FILE)


@cache
def load_cross_task_consistency_prompt() -> str:
    """Return the ``str.format()`` template for the ``cross_task_consistency`` verifier (T5.5).

    The template carries two slots:

    * ``{collection_handles}`` — JSON-rendered list of collection
      handles from ``data/collections.json``.
    * ``{source_blocks}`` — concatenated hydrogen source files for
      review.

    Returns:
        The template body, terminated by a single newline.

    Raises:
        FileNotFoundError: ``cross_task_consistency.md`` is missing.
    """
    return _read_prompt_file(_CROSS_TASK_CONSISTENCY_FILE)


@cache
def load_visual_judge_prompt() -> str:
    """Return the ``str.format()`` template for the ``visual_judge`` verifier (T1.2).

    The template carries six slots the verifier renders before each
    iteration (visual-verifier spec §9.2):

    * ``{base_url}`` — dev-server base URL the playwright skill drives.
    * ``{task_id}`` — selected task id at dispatch time.
    * ``{capabilities_slice}`` — JSON-rendered capabilities filtered
      to the task's page bucket(s) (§5.3.1).
    * ``{route_list}`` — rendered list of routes the agent must
      render at desktop + mobile viewports.
    * ``{verdict_schema}`` — JSON schema the agent must emit into
      ``verdict.json`` (§9.3).
    * ``{prior_feedback_or_empty}`` — prior-iteration verifier
      feedback for this task, or the empty string.

    Returns:
        The template body, terminated by a single newline.

    Raises:
        FileNotFoundError: ``visual_judge.md`` is missing.
    """
    return _read_prompt_file(_VISUAL_JUDGE_FILE)


def _read_prompt_file(name: str) -> str:
    """Read ``<prompts dir>/<name>`` as UTF-8 text."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


__all__ = [
    "VERIFIER_FEEDBACK_PLACEHOLDER",
    "load_agents_md",
    "load_cross_task_consistency_prompt",
    "load_execute_prompt",
    "load_planner_prompt",
    "load_quality_judge_prompt",
    "load_visual_judge_prompt",
]
