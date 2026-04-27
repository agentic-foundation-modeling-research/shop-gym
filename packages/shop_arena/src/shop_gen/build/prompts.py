"""Prompt-template loader for the Phase 4 build harness loop.

Externalises the markdown bodies that
:mod:`shop_gen.build.loop.RunBuildHarnessLoopStep` (T5.6) hands to
:func:`harness.run_plan_exec_loop` as the agents constitution + planner
body + executor bodies for the gen tasks and the consolidate task. Spec
§5.5.2 + §5.5.4.

Four files live next to this module under
:mod:`shop_gen.build.prompts` (the package directory):

* ``agents.md`` — the shared constitution rendered into
  :class:`harness.PlanExecLoopConfig.agents_md`. Returned verbatim.
* ``planner.md`` — the planner-iteration body rendered into
  :class:`harness.Prompts.planner`. Returned verbatim.
* ``execute.md`` — the executor body for every ``gen_*`` task. The
  harness renders the ``{{verifier_feedback}}`` slot from the previous
  iteration's verifier dispatch (verifiers spec §5.5).
* ``consolidate_execute.md`` — the executor body the build loop driver
  selects when the harness routes the ``consolidate`` task (spec
  §5.5.4). Carries the same ``{{verifier_feedback}}`` slot so the
  consolidation pass can react to its own verifier failures across
  iterations.

The four files are checked into the repo and considered API: changes
flow through prompt-engineering review, not silent edits to the loop
driver.

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
_CONSOLIDATE_EXECUTE_FILE: Final[str] = "consolidate_execute.md"

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
def load_consolidate_execute_prompt() -> str:
    """Return the executor body for the mandatory ``consolidate`` task.

    The build-loop driver swaps this body in when the harness selects
    ``consolidate`` (spec §5.5.4). It carries the same
    ``{{verifier_feedback}}`` placeholder as :func:`load_execute_prompt`
    so the consolidation pass reacts to its own verifier failures across
    iterations.

    Returns:
        The consolidate-executor prompt text, terminated by a single
        newline.

    Raises:
        FileNotFoundError: ``consolidate_execute.md`` is missing.
        ValueError: The body is missing the
            ``{{verifier_feedback}}`` placeholder.
    """
    body = _read_prompt_file(_CONSOLIDATE_EXECUTE_FILE)
    if VERIFIER_FEEDBACK_PLACEHOLDER not in body:
        raise ValueError(
            f"{_CONSOLIDATE_EXECUTE_FILE}: consolidate-executor prompt "
            f"must contain the '{VERIFIER_FEEDBACK_PLACEHOLDER}' "
            "placeholder so the harness can inject prior-iteration "
            "verifier feedback (verifiers spec §5.5).",
        )
    return body


def _read_prompt_file(name: str) -> str:
    """Read ``<prompts dir>/<name>`` as UTF-8 text."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


__all__ = [
    "VERIFIER_FEEDBACK_PLACEHOLDER",
    "load_agents_md",
    "load_consolidate_execute_prompt",
    "load_execute_prompt",
    "load_planner_prompt",
]
