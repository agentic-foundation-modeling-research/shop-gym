"""Step DAG primitives for the ``shop_gen`` pipeline.

The :mod:`shop_gen.steps.base` module defines the typed contract every
pipeline step satisfies (``Step`` Protocol, ``StepContext``, ``StepStatus``,
and the ``InputRef`` union). The companion runner / state-store modules
land in subsequent tasks (T1.3, T1.4) and consume those primitives.

Spec: ``docs/specs/shop_arena/shop_gen.md`` §5.7.
"""

from __future__ import annotations

from shop_gen.steps.base import (
    FileInput,
    InputRef,
    Step,
    StepContext,
    StepInput,
    StepStatus,
)

__all__ = [
    "FileInput",
    "InputRef",
    "Step",
    "StepContext",
    "StepInput",
    "StepStatus",
]
