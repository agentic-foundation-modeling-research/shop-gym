"""M0 scaffold smoke: every spec §5.10 module is importable.

This guards the package skeleton. As real implementations land in
M1+, public-surface tests under ``test_public_surface.py`` will assert
on ``__all__`` membership; this file only checks the module graph.
"""

from __future__ import annotations

import importlib

from shop_arena import env_eval

# Mirrors spec ``docs/specs/shop_arena/env_eval.md`` §5.10. Submodules
# are intentionally empty stubs at M0; importing them must not raise.
EXPECTED_MODULES = (
    "shop_arena.env_eval",
    "shop_arena.env_eval.cli",
    "shop_arena.env_eval.config",
    "shop_arena.env_eval.env",
    "shop_arena.env_eval.errors",
    "shop_arena.env_eval.pages",
    "shop_arena.env_eval.pipeline",
    "shop_arena.env_eval.resume",
    "shop_arena.env_eval.action",
    "shop_arena.env_eval.action.heuristic",
    "shop_arena.env_eval.observation",
    "shop_arena.env_eval.observation.axtree_stats",
    "shop_arena.env_eval.observation.axtree_text",
    "shop_arena.env_eval.observation.rubric",
    "shop_arena.env_eval.transition",
    "shop_arena.env_eval.transition.bfs",
    "shop_arena.env_eval.transition.canonicalize",
    "shop_arena.env_eval.transition.graph",
    "shop_arena.env_eval.transition.rules",
    "shop_arena.env_eval.transition.stateful",
    "shop_arena.env_eval.schema",
    "shop_arena.env_eval.schema.manifest",
    "shop_arena.env_eval.schema.metrics",
    "shop_arena.env_eval.structure",
    "shop_arena.env_eval.structure.compare",
    "shop_arena.env_eval.structure.distance",
    "shop_arena.env_eval.structure.schema",
    "shop_arena.env_eval.structure.snapshot",
    "shop_arena.env_eval.visualize",
    "shop_arena.env_eval.visualize.transition_graph",
)


def test_every_spec_module_imports() -> None:
    """Every module listed in spec §5.10 imports without side effects."""
    for name in EXPECTED_MODULES:
        importlib.import_module(name)


def test_version_is_v0_1_2() -> None:
    """``__version__`` is the current env-eval package version."""
    assert env_eval.__version__ == "0.1.2"


def test_py_typed_marker_exists() -> None:
    """``py.typed`` ships so downstream pyright sees inline types."""
    from importlib import resources

    assert resources.files("shop_arena.env_eval").joinpath("py.typed").is_file()
