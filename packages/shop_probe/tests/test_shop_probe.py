"""Smoke tests for shop_probe."""

from __future__ import annotations

import pytest

from shop_probe import __version__
from shop_probe.cli import EXIT_USAGE, main


def test_version_is_string() -> None:
    assert isinstance(__version__, str)


def test_cli_no_args_exits_with_usage_error() -> None:
    """``shop-probe`` with no arguments exits via argparse usage error."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == EXIT_USAGE
