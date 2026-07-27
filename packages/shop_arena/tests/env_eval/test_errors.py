"""Behavioral tests for :mod:`shop_arena.env_eval.errors`.

These tests pin down the public-surface contract from spec §8.1: the
the named errors exist, descend from a common base, and can be raised
and caught with a message round-trip intact.
"""

from __future__ import annotations

import pytest

from shop_arena.env_eval import errors


def test_errors_module_all_lists_public_surface() -> None:
    """``__all__`` advertises exactly the documented error vocabulary."""
    assert set(errors.__all__) == {
        "EnvEvalError",
        "ShopUnreachableError",
        "PageDiscoveryError",
        "MetricsValidationError",
        "PagesClassifierError",
        "ResumeError",
        "StructureComparisonError",
    }


@pytest.mark.parametrize(
    "subclass",
    [
        errors.ShopUnreachableError,
        errors.PageDiscoveryError,
        errors.MetricsValidationError,
        errors.PagesClassifierError,
        errors.ResumeError,
        errors.StructureComparisonError,
    ],
)
def test_each_error_inherits_from_envevalerror(subclass: type[Exception]) -> None:
    """Every concrete error descends from the package base class."""
    assert issubclass(subclass, errors.EnvEvalError)


def test_envevalerror_inherits_from_runtimeerror() -> None:
    """The package base error is a :class:`RuntimeError` subclass.

    Choosing :class:`RuntimeError` (over :class:`Exception`) lets
    pyright-strict callers narrow on standard library types when they
    do not want to import the EnvEval surface directly.
    """
    assert issubclass(errors.EnvEvalError, RuntimeError)


def test_shopunreachableerror_round_trips_message() -> None:
    """Raising a concrete error preserves its message through ``str()``."""
    with pytest.raises(errors.ShopUnreachableError) as exc_info:
        raise errors.ShopUnreachableError("homepage 503: example.com")

    assert str(exc_info.value) == "homepage 503: example.com"


def test_concrete_errors_can_be_caught_via_base() -> None:
    """``except EnvEvalError`` catches any concrete EnvEval failure."""
    with pytest.raises(errors.EnvEvalError):
        raise errors.PageDiscoveryError("no product hrefs found")
    with pytest.raises(errors.EnvEvalError):
        raise errors.MetricsValidationError("schema rejected")
    with pytest.raises(errors.EnvEvalError):
        raise errors.ResumeError("config snapshot mismatch")
