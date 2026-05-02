"""Project ``.env`` loader for the judge clients.

Mirrors ``shop_arena.probe.agent.env`` from v0.4 but lives under :mod:`shop_arena.probe.judge`
in v1.0. Credentials are required per provider:

* ``anthropic:<id>`` — needs ``ANTHROPIC_API_KEY`` (or
  ``ANTHROPIC_AUTH_TOKEN``); honors ``ANTHROPIC_BASE_URL``.
* ``openai:<id>`` — needs ``OPENAI_API_KEY``; honors ``OPENAI_BASE_URL``.
"""

from __future__ import annotations

import os
from typing import Final, Literal

from shop_arena.util._dotenv import load_project_env

_ANTHROPIC_AUTH_KEYS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
)
_OPENAI_AUTH_KEYS: Final[tuple[str, ...]] = ("OPENAI_API_KEY",)

JudgeProvider = Literal["anthropic", "openai"]


class MissingJudgeCredentialsError(RuntimeError):
    """Raised when no credential is present for the requested provider after ``.env`` load."""


def load_agent_env() -> None:
    """Populate ``os.environ`` from the project ``.env`` (idempotent)."""
    load_project_env()


def require_credentials(provider: JudgeProvider) -> None:
    """Validate that the SDK for ``provider`` can authenticate."""
    if provider == "anthropic":
        keys = _ANTHROPIC_AUTH_KEYS
        hint = (
            "Anthropic judge needs ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) "
            "in the environment."
        )
    else:
        keys = _OPENAI_AUTH_KEYS
        hint = "OpenAI judge needs OPENAI_API_KEY in the environment."
    if any(os.environ.get(k) for k in keys):
        return
    raise MissingJudgeCredentialsError(
        f"{hint} Add it to a project `.env` (see `.env.example`) or export it in your shell."
    )
