"""Project ``.env`` loader for the capture-judge clients.

The capture-judge (:mod:`shop_probe.agent.judge`) supports two
providers, selected by a ``--capture-judge-model`` prefix:

* ``anthropic:<id>`` — needs ``ANTHROPIC_API_KEY`` (or
  ``ANTHROPIC_AUTH_TOKEN`` for the OAuth bearer flow); honors
  ``ANTHROPIC_BASE_URL`` for routing through a private gateway.
* ``openai:<id>`` — needs ``OPENAI_API_KEY``; honors
  ``OPENAI_BASE_URL`` for the same routing role.

This module surfaces all of those through a project-level ``.env`` so
operators do not have to ``export`` them on every invocation. It is
import-safe: :func:`load_agent_env` is a no-op until called explicitly.
The first call walks upward from the current working directory to find
a ``.env`` file (matching :func:`dotenv.find_dotenv` semantics),
populates ``os.environ`` *without* overwriting already-set values
(shell exports win), and remembers it ran so subsequent calls are
cheap.
"""

from __future__ import annotations

import os
from typing import Final, Literal

from dotenv import find_dotenv, load_dotenv

_loaded: bool = False
"""Module-level once-flag (cleared by :func:`reset_for_testing`)."""

_ANTHROPIC_AUTH_KEYS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
)
"""Either of these unblocks the Anthropic SDK client constructor."""

_OPENAI_AUTH_KEYS: Final[tuple[str, ...]] = ("OPENAI_API_KEY",)
"""Required for the OpenAI SDK client constructor."""

JudgeProvider = Literal["anthropic", "openai"]


class MissingJudgeCredentialsError(RuntimeError):
    """Raised when no credential is present for the requested provider after ``.env`` load."""


def load_agent_env() -> None:
    """Populate ``os.environ`` from the project ``.env`` (idempotent).

    Walks upward from the current working directory to find a ``.env``
    file and loads it with ``override=False`` so values already exported
    in the shell take precedence. Subsequent calls are no-ops.

    No error is raised when the file is missing — operators may have
    exported the variables directly. Credential validation is the
    caller's responsibility (see :func:`require_credentials`).
    """
    global _loaded  # noqa: PLW0603 — module-scoped once-flag
    if _loaded:
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)
    _loaded = True


def require_credentials(provider: JudgeProvider) -> None:
    """Validate that the SDK for ``provider`` can authenticate.

    Call after :func:`load_agent_env` so ``.env``-sourced values are in
    scope. Raises a clear, actionable error instead of letting the SDK
    surface its own opaque ``TypeError`` from inside the cohort runner's
    generic exception handler.

    Args:
        provider: ``"anthropic"`` or ``"openai"``.

    Raises:
        MissingJudgeCredentialsError: When no credential for
            ``provider`` is present in the environment.
    """
    if provider == "anthropic":
        keys = _ANTHROPIC_AUTH_KEYS
        hint = (
            "Anthropic capture-judge needs ANTHROPIC_API_KEY (or "
            "ANTHROPIC_AUTH_TOKEN) in the environment."
        )
    else:
        keys = _OPENAI_AUTH_KEYS
        hint = "OpenAI capture-judge needs OPENAI_API_KEY in the environment."
    if any(os.environ.get(k) for k in keys):
        return
    raise MissingJudgeCredentialsError(
        f"{hint} Add it to a project `.env` (see `.env.example`) or export it in your shell."
    )


def reset_for_testing() -> None:
    """Clear the once-flag so a test can re-trigger the ``.env`` load."""
    global _loaded  # noqa: PLW0603 — module-scoped once-flag
    _loaded = False
