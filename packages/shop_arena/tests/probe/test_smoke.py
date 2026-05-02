"""Smoke tests for shop_arena.probe."""

from __future__ import annotations

import pytest

from shop_arena.probe import __version__
from shop_arena.probe.cli import main


def test_version_is_string() -> None:
    assert isinstance(__version__, str)


def test_cli_no_args_exits_with_usage_error() -> None:
    """``shop-probe`` with no arguments exits via argparse usage error (code 2)."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
