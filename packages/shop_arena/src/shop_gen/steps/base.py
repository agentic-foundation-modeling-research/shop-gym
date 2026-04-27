"""Step protocol, status enum, input refs, and execution context.

Implements the step contract from
``docs/specs/shop_arena/shop_gen.md`` §5.7.1:

* :class:`Step` — Protocol every pipeline step satisfies.
* :class:`StepContext` — execution context handed to ``Step.run``.
* :class:`StepStatus` — lifecycle status persisted in ``state.json``.
* :class:`FileInput` / :class:`StepInput` — the two arms of the
  :data:`InputRef` union (file path | upstream step id).

The companion runner (T1.4) uses these primitives to build the DAG,
compute per-step fingerprints, and topologically run stale steps.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from harness.runtimes import LLMCompleter
from shop_gen.config import ShopGenConfig


class StepStatus(enum.Enum):
    """Lifecycle status of a single step recorded in ``state.json``.

    The runner derives a step's status by comparing the recorded
    fingerprint (input file hashes ⊕ upstream fingerprints ⊕
    :attr:`Step.version`) against the one computed from the current
    workspace; outputs that do not exist on disk are also treated as
    staleness signals (spec §5.7).

    Members:
        PENDING: Step has never executed; absent from ``state.json``.
        STALE: Recorded fingerprint mismatches the computed one, or any
            declared output is missing, or any upstream step is stale.
        RUNNING: Currently executing; persisted on entry so a crash is
            distinguishable from a clean ``FRESH`` state.
        FRESH: Fingerprint matches and all declared outputs exist.
        FAILED: Most recent run raised an exception.
    """

    PENDING = "pending"
    STALE = "stale"
    RUNNING = "running"
    FRESH = "fresh"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FileInput:
    """File-path input declared by a step.

    The runner hashes the file's bytes when computing the owning
    step's fingerprint (spec §5.7).

    Attributes:
        path: Absolute or run-relative path to the input file.
    """

    path: Path


@dataclass(frozen=True, slots=True)
class StepInput:
    """Reference to an upstream step's output.

    The runner hashes the upstream step's recorded fingerprint when
    computing the owning step's fingerprint (spec §5.7).

    Attributes:
        step_id: ``Step.id`` of the upstream step.
    """

    step_id: str


InputRef = FileInput | StepInput
"""Either a file on disk or an upstream step id (spec §5.7.1)."""


@dataclass(frozen=True, slots=True)
class StepContext:
    """Execution context handed to :meth:`Step.run`.

    Steps must not mutate ``config``; they own only the directories
    documented in their ``outputs`` list. The runner is responsible for
    ensuring ``out_dir`` exists; steps may create any subdirectories
    they need below it.

    Attributes:
        config: Full :class:`~shop_gen.config.ShopGenConfig` for the run.
        out_dir: Resolved run workspace
            (``outputs/shops/<name>/`` per the published artifact layout).
        runtime: Optional one-shot LLM completer for steps that need a
            single non-agent model call (e.g. ``merge_capabilities``
            tie-breaks, ``synth_identity``). Deterministic steps
            (e.g. ``compute_merge_stats``) ignore it; ``None`` is valid
            when no LLM-using step is registered for the run.
    """

    config: ShopGenConfig
    out_dir: Path
    runtime: LLMCompleter | None = None


@runtime_checkable
class Step(Protocol):
    """Pipeline step contract (spec §5.7.1).

    Steps are idempotent: running ``run(ctx)`` twice with the same
    inputs and the same :attr:`version` produces identical outputs.
    The runner enforces this via fingerprint hashing in ``state.json``.

    Attributes:
        id: Globally unique identifier (e.g. ``"synth_collections"``).
        phase: High-level phase the step belongs to — one of
            ``"manual_merge"``, ``"data_synth"``, ``"data_validation"``,
            ``"build"``, ``"final_eval"``.
        inputs: Files and upstream-step references hashed into the
            step's fingerprint.
        outputs: Files this step writes. A missing output makes the
            step ``STALE``.
        depends_on: Upstream step ids. Must be a superset of every
            ``StepInput.step_id`` in :attr:`inputs`.
        version: Bump when the step's behaviour changes; included in
            the fingerprint so cached outputs invalidate automatically.
    """

    id: str
    phase: str
    inputs: list[InputRef]
    outputs: list[Path]
    depends_on: list[str]
    version: int

    def run(self, ctx: StepContext) -> None:
        """Execute the step.

        Args:
            ctx: Execution context (config, ``out_dir``, optional runtime).

        Raises:
            Exception: Any exception terminates the run; the runner
                marks the step ``FAILED`` in ``state.json`` and
                propagates the error to the caller.
        """
        ...
