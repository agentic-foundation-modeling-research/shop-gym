"""Tests for the ``shop_explore`` top-level public surface (spec §8.1, T5.1).

The package exposes a small, explicit set of names at the top level. Anything
not listed in §8.1 stays under its submodule (e.g. ``shop_explore.prefetch.run``,
``shop_explore.synthesize.synthesize``, ``shop_explore.capabilities.merge_fragments``).
"""

from __future__ import annotations

import importlib
import inspect

# The exact ``from shop_explore import ...`` named in the T5.1 check.
# Importing at module scope is itself the smoke test: it must not raise.
from shop_explore import (
    Capabilities,
    CapabilitiesValidationError,
    ExploreConfig,
    ExploreResult,
    RuntimeName,
    ShopUnreachableError,
    Stats,
    SynthesisError,
    __version__,
    explore,
)
from shop_explore.capabilities import merge_fragments
from shop_explore.prefetch import run as prefetch_run
from shop_explore.synthesize import synthesize as synth


def test_imports_work_per_spec_check() -> None:
    """T5.1 named import surface is callable / class-shaped as expected."""
    assert callable(explore)
    assert inspect.isclass(ExploreConfig)
    assert inspect.isclass(ExploreResult)
    assert inspect.isclass(Capabilities)
    assert inspect.isclass(Stats)


def test_all_matches_spec_public_surface() -> None:
    """``__all__`` is exactly the §8.1 top-level set, sorted."""
    module = importlib.import_module("shop_explore")
    expected = {
        "Capabilities",
        "CapabilitiesValidationError",
        "ExploreConfig",
        "ExploreResult",
        "RuntimeName",
        "ShopUnreachableError",
        "Stats",
        "SynthesisError",
        "__version__",
        "explore",
    }
    assert set(module.__all__) == expected
    # ``__all__`` is the one place we promise; keep it sorted for diff stability.
    assert list(module.__all__) == sorted(module.__all__)


def test_all_names_in_all_are_resolvable() -> None:
    """Every name in ``__all__`` must actually exist on the module."""
    module = importlib.import_module("shop_explore")
    for name in module.__all__:
        assert hasattr(module, name), f"{name} listed in __all__ but missing"


def test_namespaced_helpers_are_not_in_all() -> None:
    """Helpers the spec keeps under submodules must not bleed into ``__all__``.

    §8.1 lists ``prefetch.run``, ``synthesize.synthesize``, and
    ``capabilities.merge_fragments`` as namespaced — they stay reachable via
    their submodule but must not be promoted into the public re-export set.
    Submodule attributes (``shop_explore.prefetch`` etc.) are intentionally
    accessible as a side effect of the re-export imports; only ``__all__``
    defines the *promised* public surface.
    """
    module = importlib.import_module("shop_explore")
    for leaked in ("run", "merge_fragments", "compute"):
        assert leaked not in module.__all__


def test_submodule_entry_points_still_reachable() -> None:
    """The §8.1 namespaced functions remain importable through their submodule."""
    assert callable(merge_fragments)
    assert callable(prefetch_run)
    assert callable(synth)


def test_version_is_a_string() -> None:
    """``__version__`` is a non-empty string sourced from ``_version``."""
    assert isinstance(__version__, str)
    assert __version__


def test_runtime_name_alias_is_a_literal() -> None:
    """``RuntimeName`` is the spec-stable runtime selector alias."""
    # ``Literal`` aliases are not classes; they expose ``__args__``.
    assert getattr(RuntimeName, "__args__", None) == ("pi", "claude_code")


def test_error_classes_are_exceptions() -> None:
    """The three re-exported errors are real ``Exception`` subclasses."""
    for exc in (CapabilitiesValidationError, ShopUnreachableError, SynthesisError):
        assert issubclass(exc, Exception)
