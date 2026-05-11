"""Project-level ``.env`` loader shared across shop_arena CLIs.

:mod:`shop_arena.gen.cli` honours a project-root ``.env`` so operators do
not have to ``export`` API keys and routing URLs (``OPENAI_API_KEY``,
``OPENAI_BASE_URL``, ``ANTHROPIC_API_KEY``, ``ANTHROPIC_BASE_URL``) on
every invocation.

The loader is import-safe (no I/O at import time) and idempotent — the
first call walks upward from the current working directory to find a
``.env`` (matching :func:`dotenv.find_dotenv` semantics), populates
``os.environ`` *without* overwriting already-set values (shell exports
win), and remembers it ran so subsequent calls are cheap.
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
