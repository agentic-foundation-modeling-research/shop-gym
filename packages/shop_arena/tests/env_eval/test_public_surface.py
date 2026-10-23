"""Public-surface re-exports tracked per milestone.

Spec §5.10 lists ``evaluate``, ``EvalConfig``, ``EvalResult`` as the
public surface; the impl plan adds ``errors`` to that list. M0 landed
the error half; the first M1 task added ``EvalConfig`` / ``EvalResult``;
subsequent M1 work added ``evaluate``. URL-cohort structural comparison
adds ``compare_urls`` and its configuration/result types. This test pins
the current contract so a regression in ``__init__.py`` is caught.
"""

from __future__ import annotations

from shop_arena import env_eval
from shop_arena.env_eval import errors as errors_module

# Names re-exported by the current package surface.
CURRENT_PUBLIC_SURFACE: frozenset[str] = frozenset(
    {
        "CompareConfig",
        "CompareResult",
        "EnvEvalError",
        "EvalConfig",
        "EvalResult",
        "MetricsValidationError",
        "PageDiscoveryError",
        "ResumeError",
        "ShopUnreachableError",
        "StructureComparisonError",
        "__version__",
        "compare_urls",
        "errors",
        "evaluate",
        "render_graph_html",
    },
)


def test_all_matches_current_surface() -> None:
    """``__all__`` is exactly the documented surface — no accidental leaks."""
    assert set(env_eval.__all__) == CURRENT_PUBLIC_SURFACE


def test_every_exported_name_is_attribute() -> None:
    """Every name in ``__all__`` resolves on the package object."""
    for name in env_eval.__all__:
        assert hasattr(env_eval, name), f"missing re-export: {name}"


def test_error_classes_are_identical_to_errors_module() -> None:
    """Top-level error names are the *same objects* as in ``errors``.

    A re-export must preserve identity so ``except`` clauses work
    interchangeably with ``shop_arena.env_eval.errors``.
    """
    assert env_eval.EnvEvalError is errors_module.EnvEvalError
    assert env_eval.ShopUnreachableError is errors_module.ShopUnreachableError
    assert env_eval.PageDiscoveryError is errors_module.PageDiscoveryError
    assert env_eval.MetricsValidationError is errors_module.MetricsValidationError
    assert env_eval.ResumeError is errors_module.ResumeError
    assert env_eval.StructureComparisonError is errors_module.StructureComparisonError


def test_errors_submodule_is_re_exported() -> None:
    """``shop_arena.env_eval.errors`` is reachable via the package object."""
    assert env_eval.errors is errors_module
