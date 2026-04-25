"""Smoke tests for the ``shop_explore`` package.

Detailed CLI behavior is covered under ``tests/shop_explore/``; this
module only guards basic importability of the public version string.
"""

from shop_explore import __version__


def test_version_is_string() -> None:
    assert isinstance(__version__, str)
