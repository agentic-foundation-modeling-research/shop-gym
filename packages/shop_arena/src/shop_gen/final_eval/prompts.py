"""Prompt-template loader for the Phase 5 ``final_eval`` step.

Externalises the markdown body the post-build LLM judge consumes (impl
plan T6.2). The eventual ``final_eval`` step (T6.3) renders the
template against the captured :class:`SmokeReport` and the merged
``capabilities.json``, dispatches the call through the runtime's
``LLMCompleter``, and persists the verdict into ``final_eval.json``
(spec §5.5.5).

One file lives next to this module under
:mod:`shop_gen.final_eval.prompts` (the package directory):

* ``quality_judge.md`` — :func:`str.format` template carrying four
  slots:

  * ``{base_url}`` — dev-server base URL (``http://127.0.0.1:<port>``).
  * ``{capabilities}`` — JSON-rendered ``capabilities.json`` body.
  * ``{screenshots_table}`` — markdown table of captured screenshots
    (one row per ``(step, viewport)`` pair).
  * ``{failures_table}`` — markdown table of smoke-flow failures (or
    a placeholder when the run was clean).

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


def _read_prompt_file(name: str) -> str:
    """Read ``<prompts dir>/<name>`` as UTF-8 text."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


__all__ = ["load_quality_judge_prompt"]
