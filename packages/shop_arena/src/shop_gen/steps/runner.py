"""Step DAG runner — registry, topological resolution, staleness, execution.

Implements the orchestration core documented in
``docs/specs/shop_arena/shop_gen.md`` §5.7. The runner owns the three
responsibilities listed there:

1. **Build the DAG** for a set of registered steps and resolve a
   deterministic topological order (cycles + missing dependencies are
   rejected up front).
2. **Compute staleness** for every step from the persisted state in
   ``<out_dir>/.shop_gen/state.json`` (output missing OR input changed
   OR upstream stale OR fingerprint mismatch OR last status FAILED /
   RUNNING).
3. **Run stale steps** in topological order, persisting the resulting
   :class:`~shop_gen.steps.state.StepStateRecord` after every transition
   so a crash mid-run is recoverable.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shop_gen.steps.base import Step, StepContext, StepInput, StepStatus
from shop_gen.steps.state import (
    StateFile,
    StepStateRecord,
    compute_fingerprint,
    read_state,
    upsert_step_state,
    write_state,
)


class DAGError(ValueError):
    """Base class for DAG-resolution failures."""


class CycleError(DAGError):
    """Raised when ``resolve_dag`` detects a directed cycle."""


class MissingDependencyError(DAGError):
    """Raised when a step references an upstream id that is not registered."""


class DuplicateStepError(ValueError):
    """Raised when the same step id is registered more than once."""


class Registry:
    """In-memory registry of pipeline steps keyed by :attr:`Step.id`.

    The pipeline (T1.6) builds a config-aware registry per run and hands
    the registered steps to :func:`run_pipeline`. The registry validates
    only id-uniqueness; structural validation (depends_on closure, cycle
    freedom, ``StepInput`` ⊆ ``depends_on``) lives in :func:`resolve_dag`.
    """

    def __init__(self) -> None:
        self._steps: dict[str, Step] = {}

    def register(self, step: Step) -> None:
        """Register ``step``.

        Args:
            step: Step to add.

        Raises:
            DuplicateStepError: A step with ``step.id`` is already registered.
        """
        if step.id in self._steps:
            raise DuplicateStepError(f"step id {step.id!r} already registered")
        self._steps[step.id] = step

    def get(self, step_id: str) -> Step | None:
        """Return the registered step with id ``step_id`` or ``None``."""
        return self._steps.get(step_id)

    def all(self) -> list[Step]:
        """Return the registered steps in registration order."""
        return list(self._steps.values())

    def ids(self) -> list[str]:
        """Return the registered step ids in registration order."""
        return list(self._steps)

    def __len__(self) -> int:
        return len(self._steps)

    def __contains__(self, step_id: object) -> bool:
        return step_id in self._steps


def resolve_dag(steps: Iterable[Step]) -> list[Step]:
    """Return ``steps`` in a deterministic topological order.

    The order is determined by Kahn's algorithm with id-sorted
    tie-breaking, so two runs against the same registered set produce
    the same execution order regardless of registration order.

    Args:
        steps: Steps to order. Duplicate ids collapse to the last
            occurrence (the runner relies on the caller — usually
            :class:`Registry` — to enforce uniqueness).

    Returns:
        Topologically sorted list of steps.

    Raises:
        MissingDependencyError: A ``depends_on`` id (or any
            ``StepInput.step_id`` in ``inputs``) is absent from
            ``steps``, or a ``StepInput`` is missing from
            ``depends_on``.
        CycleError: A directed cycle exists among ``depends_on`` edges.
    """
    by_id: dict[str, Step] = {}
    for step in steps:
        by_id[step.id] = step

    _validate_dependencies(by_id)

    # Kahn's algorithm with id-sorted tie-breaking for determinism.
    in_degree: dict[str, int] = dict.fromkeys(by_id, 0)
    children: dict[str, list[str]] = {sid: [] for sid in by_id}
    for step in by_id.values():
        for dep in step.depends_on:
            in_degree[step.id] += 1
            children[dep].append(step.id)

    queue: list[str] = sorted(sid for sid, deg in in_degree.items() if deg == 0)
    order: list[Step] = []
    while queue:
        sid = queue.pop(0)
        order.append(by_id[sid])
        for child in sorted(children[sid]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                # Insert preserving id-sorted order so dequeue is deterministic.
                _insert_sorted(queue, child)

    if len(order) != len(by_id):
        remaining = sorted(set(by_id) - {step.id for step in order})
        raise CycleError(f"cycle detected among steps: {remaining}")

    return order


def select_ancestors_inclusive(steps: Iterable[Step], stop_at: str) -> list[Step]:
    """Return ``stop_at`` and every transitive ``depends_on`` ancestor.

    Used by :func:`shop_gen.pipeline.run` to honour the CLI's ``--to STEP``
    flag (spec §5.7.4): the runner is restricted to the upstream cone of
    ``stop_at`` so the pipeline halts once that step has produced its
    outputs. Order within the returned list is irrelevant — callers pass
    it through :func:`resolve_dag` before execution.

    Args:
        steps: Steps to slice. The full per-run registry is the typical
            input.
        stop_at: Step id at which execution should stop.

    Returns:
        A list containing ``stop_at`` and all of its transitive
            ancestors. No duplicates; order is registration order with
            ancestors filtered in.

    Raises:
        MissingDependencyError: ``stop_at`` is not present in ``steps``,
            or one of its transitive ``depends_on`` ids is unregistered.
    """
    by_id: dict[str, Step] = {step.id: step for step in steps}
    if stop_at not in by_id:
        raise MissingDependencyError(
            f"--to target {stop_at!r} is not registered for this run",
        )
    keep: set[str] = set()
    pending: list[str] = [stop_at]
    while pending:
        sid = pending.pop()
        if sid in keep:
            continue
        step = by_id.get(sid)
        if step is None:
            raise MissingDependencyError(
                f"step {stop_at!r} transitively depends on unregistered step {sid!r}",
            )
        keep.add(sid)
        pending.extend(step.depends_on)
    return [step for step in by_id.values() if step.id in keep]


def _validate_dependencies(by_id: dict[str, Step]) -> None:
    """Validate ``depends_on`` closure and the ``StepInput`` ⊆ ``depends_on`` rule.

    Raises:
        MissingDependencyError: A ``depends_on`` id is absent from ``by_id``,
            or a ``StepInput`` references an unregistered step, or a
            ``StepInput`` is not declared in ``depends_on``.
    """
    for step in by_id.values():
        for dep in step.depends_on:
            if dep not in by_id:
                raise MissingDependencyError(
                    f"step {step.id!r} depends on unregistered step {dep!r}",
                )
        declared = set(step.depends_on)
        for ref in step.inputs:
            if not isinstance(ref, StepInput):
                continue
            if ref.step_id not in by_id:
                raise MissingDependencyError(
                    f"step {step.id!r} has StepInput({ref.step_id!r}) "
                    "but no such step is registered",
                )
            if ref.step_id not in declared:
                raise MissingDependencyError(
                    f"step {step.id!r} has StepInput({ref.step_id!r}) "
                    "but does not declare it in depends_on",
                )


def _insert_sorted(queue: list[str], value: str) -> None:
    """Insert ``value`` into ``queue`` keeping the list lexicographically sorted."""
    lo, hi = 0, len(queue)
    while lo < hi:
        mid = (lo + hi) // 2
        if queue[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    queue.insert(lo, value)


def _resolve_output_path(path: Path, run_root: Path) -> Path:
    """Resolve a ``Step.outputs`` path against ``run_root``.

    Absolute paths are returned unchanged; relative paths are joined to
    ``run_root`` so a step's declared outputs travel with the workspace.
    """
    return path if path.is_absolute() else run_root / path


def compute_staleness(
    steps_in_topo_order: list[Step],
    state: StateFile,
    *,
    run_root: Path,
    force_ids: frozenset[str] = frozenset(),
) -> dict[str, bool]:
    """Compute per-step staleness against the persisted state.

    The check follows spec §5.7: a step is stale if any of the
    following hold:

    * its id is in ``force_ids`` (``--from`` / ``--only`` plumbing);
    * it has no recorded :class:`StepStateRecord`, or the record's
      fingerprint is ``None``, or its status is
      :attr:`~shop_gen.steps.base.StepStatus.FAILED` /
      :attr:`~shop_gen.steps.base.StepStatus.RUNNING`
      (RUNNING ⇒ crash mid-run);
    * any declared output is missing on disk;
    * any declared input is missing on disk, or any upstream
      ``StepInput`` references a step without a recorded fingerprint;
    * the recorded fingerprint differs from the freshly computed one;
    * any upstream step is stale (cascade).

    Args:
        steps_in_topo_order: Steps in topological order — caller must
            run :func:`resolve_dag` first so the cascade visits each
            upstream before its descendants.
        state: Currently persisted state document.
        run_root: Workspace root used to resolve relative output and
            input paths (typically ``ctx.out_dir``).
        force_ids: Step ids to mark stale unconditionally.

    Returns:
        Mapping ``step.id -> is_stale`` covering every step in
        ``steps_in_topo_order``.
    """
    stale: dict[str, bool] = {}
    for step in steps_in_topo_order:
        if step.id in force_ids:
            stale[step.id] = True
            continue
        if any(stale.get(dep, False) for dep in step.depends_on):
            stale[step.id] = True
            continue
        record = state.steps.get(step.id)
        if (
            record is None
            or record.fingerprint is None
            or record.status in {StepStatus.FAILED, StepStatus.RUNNING, StepStatus.PENDING}
        ):
            stale[step.id] = True
            continue
        if any(not _resolve_output_path(out, run_root).exists() for out in step.outputs):
            stale[step.id] = True
            continue
        try:
            current_fp = compute_fingerprint(step, state, run_root=run_root)
        except (FileNotFoundError, KeyError):
            stale[step.id] = True
            continue
        stale[step.id] = current_fp != record.fingerprint
    return stale


@dataclass(frozen=True, slots=True)
class RunResult:
    """Outcome of a single :func:`run_pipeline` invocation.

    Attributes:
        ran: Step ids that executed during this invocation, in
            topological order.
        skipped: Step ids that were FRESH and therefore skipped, in
            topological order.
    """

    ran: tuple[str, ...]
    skipped: tuple[str, ...]


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 ``YYYY-MM-DDTHH:MM:SSZ`` string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_pipeline(
    steps: Iterable[Step],
    ctx: StepContext,
    *,
    force_ids: frozenset[str] = frozenset(),
) -> RunResult:
    """Resolve the DAG, run stale steps in topological order, persist state.

    The runner writes ``state.json`` after every transition
    (RUNNING on entry, FRESH on success, FAILED on exception) so the
    next invocation can resume from the last clean checkpoint.

    Args:
        steps: Registered steps. Order is irrelevant — :func:`resolve_dag`
            sorts them topologically.
        ctx: Execution context. ``ctx.out_dir`` must already exist; the
            runner owns ``<out_dir>/.shop_gen/state.json`` below it.
        force_ids: Step ids to force-run regardless of their stored
            fingerprint. Downstream descendants cascade to stale via
            :func:`compute_staleness`.

    Returns:
        :class:`RunResult` summarising what ran vs what was skipped.

    Raises:
        CycleError: ``depends_on`` contains a cycle.
        MissingDependencyError: A step references an unregistered upstream id.
        Exception: Any exception raised by ``Step.run`` is re-raised
            after persisting the FAILED state record.
    """
    ordered = resolve_dag(steps)

    state = read_state(ctx.out_dir)
    stale = compute_staleness(
        ordered,
        state,
        run_root=ctx.out_dir,
        force_ids=force_ids,
    )

    ran: list[str] = []
    skipped: list[str] = []

    for step in ordered:
        if not stale[step.id]:
            skipped.append(step.id)
            continue

        prior = state.steps.get(step.id)
        prior_fp = prior.fingerprint if prior is not None else None
        state = upsert_step_state(
            state,
            StepStateRecord(
                id=step.id,
                phase=step.phase,
                status=StepStatus.RUNNING,
                fingerprint=prior_fp,
                ts=_now_iso(),
            ),
        )
        write_state(ctx.out_dir, state)

        try:
            step.run(ctx)
        except Exception:
            state = upsert_step_state(
                state,
                StepStateRecord(
                    id=step.id,
                    phase=step.phase,
                    status=StepStatus.FAILED,
                    fingerprint=None,
                    ts=_now_iso(),
                ),
            )
            write_state(ctx.out_dir, state)
            raise

        new_fp = compute_fingerprint(step, state, run_root=ctx.out_dir)
        state = upsert_step_state(
            state,
            StepStateRecord(
                id=step.id,
                phase=step.phase,
                status=StepStatus.FRESH,
                fingerprint=new_fp,
                ts=_now_iso(),
            ),
        )
        write_state(ctx.out_dir, state)
        ran.append(step.id)

    return RunResult(ran=tuple(ran), skipped=tuple(skipped))


__all__ = [
    "CycleError",
    "DAGError",
    "DuplicateStepError",
    "MissingDependencyError",
    "Registry",
    "RunResult",
    "compute_staleness",
    "resolve_dag",
    "run_pipeline",
    "select_ancestors_inclusive",
]
