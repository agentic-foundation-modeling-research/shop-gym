"""Lock the v0.1 public surface defined in spec §8.1.

If you intentionally extend the public API, update both the spec and
`harness.__all__` together; this test then needs to be updated in lockstep.
"""

from __future__ import annotations

import importlib

import harness

# Exact names listed in `docs/specs/harness/plan_exec_loop.md` §8.1.
_EXPECTED_PUBLIC: frozenset[str] = frozenset(
    {
        # Types
        "AgentRuntime",
        "IterationMetadata",
        "ProtocolCheckResult",
        "Task",
        "TaskList",
        "TaskStatus",
        "Trajectory",
        "TrajectoryStep",
        # Config & result
        "PlanExecLoopConfig",
        "PlanExecLoopResult",
        "Prompts",
        # Entry points
        "get_runtime",
        "run_plan_exec_loop",
    }
)


def test_dunder_all_matches_spec_exactly() -> None:
    assert frozenset(harness.__all__) == _EXPECTED_PUBLIC


def test_every_spec_symbol_is_importable_from_top_level() -> None:
    for name in _EXPECTED_PUBLIC:
        assert hasattr(harness, name), f"missing top-level export: {name}"
        # Re-import via `from harness import name` to mirror the spec wording.
        module = importlib.import_module("harness")
        assert getattr(module, name) is getattr(harness, name)


def test_star_import_yields_only_spec_symbols() -> None:
    namespace: dict[str, object] = {}
    exec("from harness import *", namespace)
    leaked = {name for name in namespace if not name.startswith("_") and name != "__builtins__"}
    assert leaked == set(_EXPECTED_PUBLIC)
