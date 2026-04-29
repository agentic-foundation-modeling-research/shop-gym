"""Tests for the ``shop_gen`` top-level public surface (T7.1).

The package promises a small, explicit surface: ``run``, ``ShopGenConfig``,
``ShopGenResult``, and the standard ``__version__`` string. Anything else
stays under its submodule (e.g. ``shop_gen.cli.main``,
``shop_gen.pipeline.status``).
"""

from __future__ import annotations

import importlib
import inspect

# The exact ``from shop_gen import ...`` named in the T7.1 check.
# Importing at module scope is itself the smoke test: it must not raise.
from shop_gen import (
    ShopGenConfig,
    ShopGenResult,
    __version__,
    run,
)


def test_imports_work_per_spec_check() -> None:
    """T7.1 named import surface is callable / class-shaped as expected."""
    assert callable(run)
    assert inspect.isclass(ShopGenConfig)
    assert inspect.isclass(ShopGenResult)


def test_all_matches_spec_public_surface() -> None:
    """``__all__`` is exactly the T7.1 top-level set, sorted."""
    module = importlib.import_module("shop_gen")
    expected = {
        "ShopGenConfig",
        "ShopGenResult",
        "__version__",
        "run",
    }
    assert set(module.__all__) == expected
    # ``__all__`` is the one place we promise; keep it sorted for diff stability.
    assert list(module.__all__) == sorted(module.__all__)


def test_all_names_in_all_are_resolvable() -> None:
    """Every name in ``__all__`` must actually exist on the module."""
    module = importlib.import_module("shop_gen")
    for name in module.__all__:
        assert hasattr(module, name), f"{name} listed in __all__ but missing"


def test_version_is_v0_2_0() -> None:
    """``__version__`` is bumped to the v0.2.0 release per T7.4."""
    assert __version__ == "0.2.0"
