"""Smoke tests for shop_guru."""

from shop_guru import __version__
from shop_guru.cli import main


def test_version_is_string() -> None:
    assert isinstance(__version__, str)


def test_cli_exits_cleanly() -> None:
    assert main([]) == 0
