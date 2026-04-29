"""Prompt-template loader for the Phase 5 ``final_eval`` step.

Externalises the markdown body the post-build LLM judge consumes (impl
plan T6.2). The eventual ``final_eval`` step (T6.3) renders the
template against the captured :class:`SmokeReport` and the merged
``capabilities.json``, dispatches the call through the runtime's
``LLMCompleter``, and persists the verdict into ``final_eval.json``
(spec §5.5.5).

Two files live next to this module under
:mod:`shop_gen.final_eval.prompts` (the package directory):

* ``quality_judge.md`` — :func:`str.format` template carrying four
  slots:

  * ``{base_url}`` — dev-server base URL (``http://127.0.0.1:<port>``).
  * ``{capabilities}`` — JSON-rendered ``capabilities.json`` body.
  * ``{screenshots_table}`` — markdown table of captured screenshots
    (one row per ``(step, viewport)`` pair).
  * ``{failures_table}`` — markdown table of smoke-flow failures (or
    a placeholder when the run was clean).
* ``visual_sweep.md`` — :func:`str.format` template carrying six
  slots the all-pages visual sweep (impl plan T5.2, spec §9.4) renders
  per page bucket: ``{base_url}``, ``{bucket}``,
  ``{capabilities_slice}``, ``{route_list}``, ``{verdict_schema}``,
  ``{prior_feedback_or_empty}``. Same structured-score schema and
  "judge only what you have rendered" instruction as the build-loop
  ``visual_judge`` prompt; the verdict is **advisory** rather than
  gating.

The file is checked into the repo and considered API: changes flow
through prompt-engineering review, not silent edits to the
``final_eval`` step driver.

Lookups are cached so repeated calls are free; the disk read happens
lazily on first use, keeping the parent package import-safe (no I/O at
module import time).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Final

_PROMPTS_DIR: Final[Path] = Path(__file__).resolve().parent / "prompts"
_QUALITY_JUDGE_FILE: Final[str] = "quality_judge.md"
_VISUAL_SWEEP_FILE: Final[str] = "visual_sweep.md"


@cache
def load_quality_judge_prompt() -> str:
    """Return the ``str.format()`` template for the post-build LLM judge.

    The template carries four slots:

    * ``{base_url}`` — dev-server base URL the smoke flow walked.
    * ``{capabilities}`` — JSON-rendered ``capabilities.json`` body.
    * ``{screenshots_table}`` — markdown table of captured screenshots.
    * ``{failures_table}`` — markdown table of smoke-flow failures.

    Returns:
        The template body, terminated by a single newline.

    Raises:
        FileNotFoundError: ``quality_judge.md`` is missing.
    """
    return _read_prompt_file(_QUALITY_JUDGE_FILE)


@cache
def load_visual_sweep_prompt() -> str:
    """Return the ``str.format()`` template for the final-eval visual sweep (T5.2).

    The visual sweep fans one nested agent iteration out per page
    bucket of the published storefront (spec §5.6, §9.4). Each
    bucket's iteration renders this template via ``str.format()`` with
    the per-bucket slots :func:`shop_gen.final_eval.visual_sweep.run_visual_sweep`
    resolves before submitting the call to the runtime.

    The template carries six slots, mirroring the per-iteration
    ``visual_judge`` prompt (build §9.2) with two scope-only
    differences: the prompt is scoped to a single page bucket name,
    and the verdict the agent emits is **advisory** — recorded into
    ``final_eval.json`` for human review and never used to gate the
    run (§9.4).

    * ``{base_url}`` — dev-server base URL the playwright skill drives.
    * ``{bucket}`` — page-bucket name handed to this iteration
      (e.g. ``"homepage"``, ``"collection"``).
    * ``{capabilities_slice}`` — JSON-rendered capabilities filtered
      to the bucket's keys (§5.3.1).
    * ``{route_list}`` — rendered list of routes the agent must
      render at desktop + mobile viewports.
    * ``{verdict_schema}`` — JSON schema the agent must emit into
      ``verdict.json`` (§9.3, shared with the build-loop verifier).
    * ``{prior_feedback_or_empty}`` — prior-iteration reviewer
      feedback for this bucket, or the empty string.

    Returns:
        The template body, terminated by a single newline.

    Raises:
        FileNotFoundError: ``visual_sweep.md`` is missing.
    """
    return _read_prompt_file(_VISUAL_SWEEP_FILE)


def _read_prompt_file(name: str) -> str:
    """Read ``<prompts dir>/<name>`` as UTF-8 text."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


__all__ = ["load_quality_judge_prompt", "load_visual_sweep_prompt"]
