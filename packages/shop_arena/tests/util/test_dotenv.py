"""Tests for :mod:`shop_arena.util._dotenv`."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from shop_arena.util import _dotenv


@pytest.fixture(autouse=True)
def _reset_loader() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Clear the once-flag and restore ``os.environ`` around every test.

    ``python-dotenv`` writes directly into ``os.environ``, which is not
    tracked by :class:`pytest.MonkeyPatch`, so we snapshot and restore
    the mapping ourselves.
    """
    _dotenv.reset_for_testing()
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        _dotenv.reset_for_testing()


def test_load_project_env_populates_unset_vars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        'OPENAI_BASE_URL="https://proxy.example/v1"\n',
        encoding="utf-8",
    )

    _dotenv.load_project_env()

    assert os.environ.get("OPENAI_BASE_URL") == "https://proxy.example/v1"


def test_load_project_env_respects_existing_shell_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://shell-wins.example/v1")
    (tmp_path / ".env").write_text(
        'OPENAI_BASE_URL="https://dotenv-loses.example/v1"\n',
        encoding="utf-8",
    )

    _dotenv.load_project_env()

    assert os.environ["OPENAI_BASE_URL"] == "https://shell-wins.example/v1"


def test_load_project_env_is_noop_when_no_dotenv_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    # No .env in tmp_path. find_dotenv walks upward, so make sure
    # whatever the runner finds does not trip the assertion below.
    sentinel = "shop-arena-test-sentinel-should-not-exist"
    monkeypatch.delenv(sentinel, raising=False)

    _dotenv.load_project_env()  # must not raise

    assert sentinel not in os.environ


def test_load_project_env_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text('OPENAI_BASE_URL="https://first.example/v1"\n', encoding="utf-8")

    _dotenv.load_project_env()
    assert os.environ.get("OPENAI_BASE_URL") == "https://first.example/v1"

    # Rewrite the file and call again — once-flag must short-circuit.
    env_path.write_text('OPENAI_BASE_URL="https://second.example/v1"\n', encoding="utf-8")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    _dotenv.load_project_env()

    assert "OPENAI_BASE_URL" not in os.environ
