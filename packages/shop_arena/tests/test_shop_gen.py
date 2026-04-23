"""Smoke tests for shop_gen."""

import pytest

from shop_gen import __version__
from shop_gen.cli import main


def test_version_is_string() -> None:
    assert isinstance(__version__, str)


def test_cli_exits_cleanly() -> None:
    assert main([]) == 0
