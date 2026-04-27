"""Step DAG primitives for the ``shop_gen`` pipeline.

The :mod:`shop_gen.steps.base` module defines the typed contract every
pipeline step satisfies (``Step`` Protocol, ``StepContext``, ``StepStatus``,
and the ``InputRef`` union). The :mod:`shop_gen.steps.state` module owns
the ``state.json`` reader/writer and the per-step fingerprint hash. The
companion runner lands in T1.4 and consumes both.

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
from shop_gen.steps.state import (
    SCHEMA_VERSION,
    STATE_DIR_NAME,
    STATE_FILE_NAME,
    StateFile,
    StepStateRecord,
    compute_fingerprint,
    hash_file,
    read_state,
    state_path,
    upsert_step_state,
    write_state,
)

__all__ = [
    "SCHEMA_VERSION",
    "STATE_DIR_NAME",
    "STATE_FILE_NAME",
    "FileInput",
    "InputRef",
    "StateFile",
    "Step",
    "StepContext",
    "StepInput",
    "StepStateRecord",
    "StepStatus",
    "compute_fingerprint",
    "hash_file",
    "read_state",
    "state_path",
    "upsert_step_state",
    "write_state",
]
