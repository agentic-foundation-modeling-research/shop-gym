"""Project-level ``.env`` loader for shop_guru.

Mirrors :mod:`shop_arena.util._dotenv`: walks upward from the current
working directory to find a ``.env``, populates ``os.environ`` *without*
overwriting already-set values (shell exports win), and remembers it
ran so subsequent calls are cheap.

The shop_guru CLIs (``shop_guru.eval.run``, ``shop_guru.eval.rejudge``,
the ``e2e`` generator) call :func:`load_project_env` before constructing
any LLM SDK client. The OpenAI and Anthropic SDKs read
``OPENAI_BASE_URL`` / ``ANTHROPIC_BASE_URL`` rather than CLI flags.
"""

from __future__ import annotations

from dotenv import find_dotenv, load_dotenv

_loaded: bool = False
"""Module-level once-flag (cleared by :func:`reset_for_testing`)."""


def load_project_env() -> None:
    """Populate ``os.environ`` from the project ``.env`` (idempotent).

    Walks upward from the current working directory to find a ``.env``
    file and loads it with ``override=False`` so values already exported
    in the shell take precedence. Subsequent calls are no-ops.

    No error is raised when the file is missing — operators may have
    exported the variables directly. Credential validation is the
    caller's responsibility.
    """
    global _loaded  # noqa: PLW0603 — module-scoped once-flag
    if _loaded:
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)
    _loaded = True


def reset_for_testing() -> None:
    """Clear the once-flag so a test can re-trigger the ``.env`` load."""
    global _loaded  # noqa: PLW0603 — module-scoped once-flag
    _loaded = False


__all__ = ["load_project_env", "reset_for_testing"]
