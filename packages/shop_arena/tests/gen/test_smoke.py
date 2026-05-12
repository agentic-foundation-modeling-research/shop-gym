"""Smoke tests for shop_arena.gen."""

import pytest

from shop_arena.gen import __version__
from shop_arena.gen.cli import main


def test_version_is_string() -> None:
    assert isinstance(__version__, str)


def test_cli_list_steps_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list-steps"]) == 0
    assert "shop-gen pipeline steps" in capsys.readouterr().out
