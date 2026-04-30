"""Project ``.env`` loader for the v1.3 agent-driven advanced tier.

The vision completion judge (:mod:`shop_probe.agent.judge`) constructs
an :class:`anthropic.AsyncAnthropic` client which authenticates against
the Anthropic Messages API by reading two environment variables:

* ``ANTHROPIC_API_KEY`` — required (or ``ANTHROPIC_AUTH_TOKEN`` for the
  OAuth bearer flow).
* ``ANTHROPIC_BASE_URL`` — optional; routes traffic through a private
  gateway when set.

This module surfaces both through a project-level ``.env`` so operators
do not have to ``export`` them on every invocation. It is import-safe:
:func:`load_agent_env` is a no-op until called explicitly. The first
call walks upward from the current working directory to find a ``.env``
file (matching :func:`dotenv.find_dotenv` semantics), populates
``os.environ`` *without* overwriting already-set values (shell exports
win), and remembers it ran so subsequent calls are cheap.
"""

from __future__ import annotations

import os
from typing import Final

from dotenv import find_dotenv, load_dotenv

_loaded: bool = False
"""Module-level once-flag (cleared by :func:`reset_for_testing`)."""

_ANTHROPIC_AUTH_KEYS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
)
"""Either of these unblocks the Anthropic SDK client constructor."""


class MissingAnthropicCredentialsError(RuntimeError):
    """Raised when no Anthropic credential is present after ``.env`` load.

    The vision completion judge cannot run without one of
    ``ANTHROPIC_API_KEY`` or ``ANTHROPIC_AUTH_TOKEN`` reachable from the
    process environment.
    """


def load_agent_env() -> None:
    """Populate ``os.environ`` from the project ``.env`` (idempotent).

    Walks upward from the current working directory to find a ``.env``
    file and loads it with ``override=False`` so values already exported
    in the shell take precedence. Subsequent calls are no-ops.

    No error is raised when the file is missing — operators may have
    exported the variables directly. Credential validation is the
    caller's responsibility (see :func:`require_anthropic_credentials`).
    """
    global _loaded  # noqa: PLW0603 — module-scoped once-flag
    if _loaded:
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)
    _loaded = True


def require_anthropic_credentials() -> None:
    """Validate that the Anthropic SDK can authenticate.

    Call after :func:`load_agent_env` so ``.env``-sourced values are in
    scope. Raises a clear, actionable error instead of letting the SDK
    surface its own opaque ``TypeError`` from inside the cohort runner's
    generic exception handler.

    Raises:
        MissingAnthropicCredentialsError: When neither
            ``ANTHROPIC_API_KEY`` nor ``ANTHROPIC_AUTH_TOKEN`` is set in
            the environment.
    """
    if any(os.environ.get(k) for k in _ANTHROPIC_AUTH_KEYS):
        return
    raise MissingAnthropicCredentialsError(
        "shop_probe v1.3 agent-driven probes need ANTHROPIC_API_KEY (or "
        "ANTHROPIC_AUTH_TOKEN) in the environment. Add it to a project "
        "`.env` (see `.env.example`) or export it in your shell."
    )


def reset_for_testing() -> None:
    """Clear the once-flag so a test can re-trigger the ``.env`` load.

    Production code never needs this; tests that exercise
    :func:`load_agent_env` under monkey-patched ``find_dotenv`` /
    ``load_dotenv`` use it to avoid leaking state between cases.
    """
    global _loaded  # noqa: PLW0603 — module-scoped once-flag
    _loaded = False
