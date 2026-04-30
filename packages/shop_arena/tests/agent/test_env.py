"""Hermetic tests for ``shop_probe.agent.env``.

Validates the ``.env`` loader contract:

* ``load_agent_env`` is idempotent (the once-flag suppresses re-loads).
* Shell-exported values are preserved (``override=False``).
* ``require_anthropic_credentials`` fails fast with a clear error when
  neither ``ANTHROPIC_API_KEY`` nor ``ANTHROPIC_AUTH_TOKEN`` is set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shop_probe.agent.env import (
    MissingAnthropicCredentialsError,
    load_agent_env,
    require_anthropic_credentials,
    reset_for_testing,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Clear the once-flag and Anthropic env vars before every test."""
    reset_for_testing()
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(key, raising=False)


def test_load_agent_env_reads_dotenv_into_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Values from ``.env`` populate ``os.environ`` on first call."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_API_KEY=sk-from-dotenv\nANTHROPIC_BASE_URL=https://gateway.example/\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    load_agent_env()

    import os  # noqa: PLC0415 — read after the loader populated the env.

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-dotenv"
    assert os.environ["ANTHROPIC_BASE_URL"] == "https://gateway.example/"


def test_load_agent_env_does_not_override_shell_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Already-set environment variables win over ``.env`` (``override=False``)."""
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-shell")

    load_agent_env()

    import os  # noqa: PLC0415

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-shell"


def test_load_agent_env_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The once-flag prevents a second ``find_dotenv`` walk on repeat calls."""
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-first\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    load_agent_env()

    # Mutate the file; a second load must NOT pick up the change because
    # the once-flag short-circuits before ``find_dotenv``.
    env_file.write_text("ANTHROPIC_API_KEY=sk-second\n", encoding="utf-8")
    load_agent_env()

    import os  # noqa: PLC0415

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-first"


def test_load_agent_env_missing_dotenv_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``.env`` file → no error (operators may export directly)."""
    monkeypatch.chdir(tmp_path)

    load_agent_env()  # must not raise.


def test_require_anthropic_credentials_passes_when_api_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ANTHROPIC_API_KEY`` alone satisfies the precondition."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")

    require_anthropic_credentials()  # must not raise.


def test_require_anthropic_credentials_passes_when_auth_token_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ANTHROPIC_AUTH_TOKEN`` alone satisfies the precondition."""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-x")

    require_anthropic_credentials()  # must not raise.


def test_require_anthropic_credentials_raises_when_neither_set() -> None:
    """Neither key set → actionable :class:`MissingAnthropicCredentialsError`."""
    with pytest.raises(MissingAnthropicCredentialsError, match="ANTHROPIC_API_KEY"):
        require_anthropic_credentials()
