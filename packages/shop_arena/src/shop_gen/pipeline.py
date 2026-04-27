"""Pipeline orchestrator for ``shop_gen`` runs.

Implements the public entry points described in
``docs/specs/shop_arena/shop_gen.md`` §5.7-§5.8 and the impl plan task
T1.6 (``docs/impl/shop_gen_implementation.md``):

* :func:`run` — resolve the run workspace, build the config-aware step
  registry, and drive :func:`shop_gen.steps.runner.run_pipeline` against
  it. Returns a :class:`~shop_gen.config.ShopGenResult` whose paths
  forward-declare the published artifacts even when the registered
  step set is empty (every phase below v0.1 still in progress).
* :func:`status` — read ``<out_dir>/.shop_gen/state.json`` and return
  one :class:`StepStatusEntry` per recorded step. Read-only; safe to
  call against a workspace that has never been touched.
* :func:`list_steps` — return the static phase → step-ids map. Each
  phase always shows up so ``shop-gen --list-steps`` can render the
  full table even when later milestones haven't registered any steps
  yet.

Phase-aware step registration lives in this module today
because no concrete steps exist yet (M2-M6). Each phase gets a tiny
``_register_<phase>`` hook that downstream milestones will fill in
without touching :func:`run` itself. The hooks keep the
single-seed-vs-multi-seed branching from spec §5.2 / §5.7.2 in one
place: multi-seed adds the manual-merge sub-DAG; single-seed adds the
``copy_seed_manual`` shortcut.

The module is import-safe — no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from shop_gen.config import ShopGenConfig, ShopGenResult
from shop_gen.data_synth import (
    AssembleDataStep,
    GenImagesStep,
    SynthAltTextStep,
    SynthCollectionsStep,
    SynthIdentityStep,
    SynthNavigationStep,
    SynthPagesStep,
    SynthPoliciesStep,
    SynthProductDetailsStep,
    SynthProductSkeletonsStep,
    SynthStoreStep,
)
from shop_gen.manual_merge import (
    ComputeMergeStatsStep,
    CopySeedManualStep,
    MergeCapabilitiesStep,
    MergeManualProseStep,
    WriteMergeManifestStep,
)
from shop_gen.steps.base import StepContext, StepStatus
from shop_gen.steps.runner import Registry, RunResult, run_pipeline
from shop_gen.steps.state import read_state, state_path

PHASES: Final[tuple[str, ...]] = (
    "manual_merge",
    "data_synth",
    "data_validation",
    "build",
    "final_eval",
)
"""Phase names in execution order (spec §5.7.2).

Every phase always appears in :func:`list_steps` output even when no
concrete step has been registered for it yet, so the CLI's
``--list-steps`` table renders consistently across milestones.
"""

_DEFAULT_OUT_ROOT: Final[Path] = Path("outputs") / "shops"
"""Parent of ``<name>/`` when ``ShopGenConfig.out_dir`` is omitted (spec §4.1)."""


@dataclass(frozen=True, slots=True)
class StepStatusEntry:
    """Persisted state of one step, projected for ``--status`` output.

    Mirrors the columns spec §5.7.4 calls out for the status table:
    ``id``, ``phase``, ``status``, ``fingerprint``, ``ts``.

    Attributes:
        id: Step id (matches ``Step.id``).
        phase: Phase the step belongs to.
        status: Most recently observed lifecycle state.
        fingerprint: Hex sha256 from the last successful run, or
            ``None`` for never-completed steps.
        ts: ISO-8601 UTC timestamp of the last transition, or ``None``
            for never-touched steps.
    """

    id: str
    phase: str
    status: StepStatus
    fingerprint: str | None
    ts: str | None


@dataclass(frozen=True, slots=True)
class StatusReport:
    """Snapshot of ``<out_dir>/.shop_gen/state.json`` for the CLI.

    Attributes:
        out_dir: Run workspace inspected.
        has_run: ``True`` when ``state.json`` exists in ``out_dir``.
            ``False`` indicates a fresh workspace (CLI prints
            "no run yet").
        steps: One entry per step recorded in ``state.json``, in the
            insertion order persisted by the runner.
    """

    out_dir: Path
    has_run: bool
    steps: tuple[StepStatusEntry, ...]


def run(
    config: ShopGenConfig,
    *,
    force_ids: frozenset[str] = frozenset(),
) -> ShopGenResult:
    """Execute the ``shop_gen`` pipeline for ``config``.

    Resolves the run workspace, builds the config-aware step registry
    (phase-aware: spec §5.2 + §5.7.2), and drives every stale step in
    topological order via :func:`shop_gen.steps.runner.run_pipeline`.
    Returns a :class:`~shop_gen.config.ShopGenResult` whose paths point
    at the *expected* published artifacts under ``<out_dir>/``;
    callers can inspect each path on disk to see which artifacts the
    current step set actually produced.

    Args:
        config: Validated run configuration.
        force_ids: Step ids to force-run regardless of their stored
            fingerprint. Plumbing for the CLI's ``--from`` / ``--only``
            flags (spec §5.7.4); downstream descendants cascade to
            stale via :func:`shop_gen.steps.runner.compute_staleness`.

    Returns:
        A :class:`~shop_gen.config.ShopGenResult` anchored at the
        resolved ``out_dir``.

    Raises:
        ValueError: ``config.out_dir`` is ``None`` and a default cannot
            be derived (multi-seed without an explicit ``name``).
        shop_gen.steps.runner.CycleError: ``depends_on`` contains a
            cycle.
        shop_gen.steps.runner.MissingDependencyError: A registered
            step references an unregistered upstream id.
        Exception: Any exception raised by a registered ``Step.run`` is
            re-raised after the runner persists ``StepStatus.FAILED``.
    """
    out_dir = _resolve_out_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)

    registry = _build_registry(config)
    ctx = StepContext(config=config, out_dir=out_dir)
    _: RunResult = run_pipeline(registry.all(), ctx, force_ids=force_ids)

    return _result_for(out_dir)


def status(out_dir: Path) -> StatusReport:
    """Read ``state.json`` from ``out_dir`` and project a status table.

    Read-only — never writes or creates the workspace. A directory with
    no ``state.json`` (fresh, never-run, or accidentally pointed at a
    sibling) returns a :class:`StatusReport` with ``has_run=False`` and
    no entries.

    Args:
        out_dir: Run workspace to inspect.

    Returns:
        Snapshot suitable for the CLI's ``--status`` formatter.

    Raises:
        pydantic.ValidationError: The on-disk ``state.json`` does not
            satisfy the closed schema (corrupted workspace).
    """
    has_run = state_path(out_dir).exists()
    state = read_state(out_dir)
    entries = tuple(
        StepStatusEntry(
            id=record.id,
            phase=record.phase,
            status=record.status,
            fingerprint=record.fingerprint,
            ts=record.ts,
        )
        for record in state.steps.values()
    )
    return StatusReport(out_dir=out_dir, has_run=has_run, steps=entries)


def list_steps() -> dict[str, tuple[str, ...]]:
    """Return the registered step ids grouped by phase.

    The returned mapping preserves :data:`PHASES` order and always
    includes every phase, even when no concrete step has been
    registered for it yet (early-milestone state). The Phase 1
    listing is the *union* of the single-seed and multi-seed
    branches, so the CLI surfaces every step name that may appear
    on some run.

    Returns:
        ``{phase_name: (step_id, ...)}``.
    """
    single_seed = _build_registry_from_branch(multi_seed=False)
    multi_seed = _build_registry_from_branch(multi_seed=True)

    grouped: dict[str, list[str]] = {phase: [] for phase in PHASES}
    seen: set[str] = set()
    for reg in (single_seed, multi_seed):
        for step in reg.all():
            if step.id in seen:
                continue
            seen.add(step.id)
            # Steps register a phase that must be one of PHASES; an
            # unknown phase indicates a registration bug, not a user
            # input error, so let the KeyError surface in tests.
            grouped[step.phase].append(step.id)

    return {phase: tuple(grouped[phase]) for phase in PHASES}


# --------------------------------------------------------------------------- #
# Registry construction
# --------------------------------------------------------------------------- #


def _build_registry(config: ShopGenConfig) -> Registry:
    """Build the per-run :class:`Registry` for ``config``.

    Phase-aware: when ``len(config.seeds) > 1`` the multi-seed
    manual-merge sub-DAG (spec §5.7.2) is registered; otherwise the
    single-seed ``copy_seed_manual`` shortcut (spec §5.2) is
    registered. Phases 2-5 are config-independent at v0.1.
    """
    return _build_registry_from_branch(multi_seed=len(config.seeds) > 1, config=config)


def _build_registry_from_branch(
    *,
    multi_seed: bool,
    config: ShopGenConfig | None = None,
) -> Registry:
    """Build a registry by selecting the manual-merge branch.

    Factored out of :func:`_build_registry` so :func:`list_steps` can
    enumerate both branches without constructing a full
    :class:`ShopGenConfig` (spec §5.8 ``--list-steps`` is config-free).
    Steps that need per-run data (e.g. ``merge_capabilities`` reads
    one ``capabilities.json`` per seed) accept ``config=None`` and
    register a placeholder instance so the step id still surfaces in
    the ``--list-steps`` table.
    """
    registry = Registry()
    if multi_seed:
        _register_manual_merge(registry, config=config)
        manual_step_ids: tuple[str, ...] = ("merge_capabilities", "merge_manual_prose")
        stats_aware_manual_step_ids: tuple[str, ...] = (
            *manual_step_ids,
            "compute_merge_stats",
        )
    else:
        _register_single_seed_manual(registry, config=config)
        manual_step_ids = ("copy_seed_manual",)
        stats_aware_manual_step_ids = manual_step_ids
    _register_data_synth(
        registry,
        manual_step_ids=manual_step_ids,
        stats_aware_manual_step_ids=stats_aware_manual_step_ids,
    )
    _register_data_validation(registry)
    _register_build(registry)
    _register_final_eval(registry)
    return registry


def _register_manual_merge(registry: Registry, *, config: ShopGenConfig | None = None) -> None:
    """Register Phase 1 multi-seed manual-merge steps (impl plan T2.1-T2.5).

    Currently registers ``merge_capabilities`` (T2.1),
    ``merge_manual_prose`` (T2.2), ``compute_merge_stats`` (T2.3), and
    ``write_merge_manifest`` (T2.4). T2.5 adds the prompt assets.

    Args:
        registry: Registry to mutate.
        config: Run configuration. ``None`` is the listing branch
            (:func:`list_steps`); steps register a placeholder
            instance so their ids surface in the ``--list-steps`` table
            without requiring real seed paths.
    """
    if config is None:
        seed_capabilities_paths: tuple[Path, ...] = ()
        seed_manual_paths: tuple[Path, ...] = ()
        seed_stats_paths: tuple[Path, ...] = ()
    else:
        seed_capabilities_paths = tuple(
            seed / "artifact" / "capabilities.json" for seed in config.seeds
        )
        seed_manual_paths = tuple(seed / "artifact" / "manual.md" for seed in config.seeds)
        seed_stats_paths = tuple(seed / "artifact" / "stats.json" for seed in config.seeds)
    registry.register(MergeCapabilitiesStep(seed_capabilities_paths=seed_capabilities_paths))
    registry.register(MergeManualProseStep(seed_manual_paths=seed_manual_paths))
    registry.register(ComputeMergeStatsStep(seed_stats_paths=seed_stats_paths))
    registry.register(WriteMergeManifestStep())


def _register_single_seed_manual(
    registry: Registry,
    *,
    config: ShopGenConfig | None = None,
) -> None:
    """Register the single-seed ``copy_seed_manual`` shortcut (spec §5.2).

    Phase 1 collapses to one byte-for-byte copy when ``len(seeds) == 1``:
    the seed's ``capabilities.json`` / ``manual.md`` / ``stats.json`` are
    copied verbatim into ``<out_dir>/manual/``.

    Args:
        registry: Registry to mutate.
        config: Run configuration. ``None`` is the listing branch
            (:func:`list_steps`); the step registers a placeholder
            instance so its id surfaces in the ``--list-steps`` table
            without requiring a real seed path.
    """
    seed_dir: Path | None = None if config is None or len(config.seeds) != 1 else config.seeds[0]
    registry.register(CopySeedManualStep(seed_dir=seed_dir))


def _register_data_synth(
    registry: Registry,
    *,
    manual_step_ids: Sequence[str] = (),
    stats_aware_manual_step_ids: Sequence[str] = (),
) -> None:
    """Register Phase 2 data-synthesis steps.
    Currently registers ``synth_identity`` (T3.3), the three
    identity-fanout steps ``synth_store`` / ``synth_pages`` /
    ``synth_policies`` (T3.4), ``synth_collections`` (T3.5),
    ``synth_product_skeletons`` (T3.6), ``synth_product_details``
    (T3.7), ``synth_navigation`` (T3.8), ``synth_alt_text``
    (T3.9), ``gen_images`` (T3.10), and the terminal
    ``assemble_data`` step (T3.11).

    Args:
        registry: Registry to mutate.
        manual_step_ids: Upstream step ids that produce the merged
            ``manual/capabilities.json`` + ``manual/manual.md``.
            Multi-seed runs pass ``("merge_capabilities",
            "merge_manual_prose")``; single-seed runs pass
            ``("copy_seed_manual",)``. Empty in the listing branch
            (``--list-steps`` does not bind to a specific seed
            count); the placeholder still surfaces the step ids in
            :func:`shop_gen.pipeline.list_steps`.
        stats_aware_manual_step_ids: Like ``manual_step_ids`` but also
            includes the producer of ``manual/stats.json``
            (``compute_merge_stats`` for multi-seed,
            ``copy_seed_manual`` for single-seed). Used by
            ``synth_collections`` so the stats priors propagate
            staleness correctly.
    """
    manual_ids = tuple(manual_step_ids)
    stats_aware_manual_ids = tuple(stats_aware_manual_step_ids)
    registry.register(SynthIdentityStep(manual_step_ids=manual_ids))
    registry.register(SynthStoreStep())
    registry.register(SynthPagesStep(manual_step_ids=manual_ids))
    registry.register(SynthPoliciesStep())
    registry.register(
        SynthCollectionsStep(manual_step_ids=stats_aware_manual_ids),
    )
    registry.register(SynthProductSkeletonsStep())
    registry.register(SynthProductDetailsStep())
    registry.register(SynthAltTextStep())
    registry.register(GenImagesStep())
    registry.register(SynthNavigationStep(manual_step_ids=manual_ids))
    registry.register(AssembleDataStep())


def _register_data_validation(registry: Registry) -> None:
    """Register Phase 3 data-validation steps.

    Wired up in M4 (impl plan T4.1-T4.2); a no-op until those tasks
    land.
    """
    del registry  # placeholder until M4 lands.


def _register_build(registry: Registry) -> None:
    """Register Phase 4 build-harness-loop steps.

    Wired up in M5 (impl plan T5.1-T5.6); a no-op until those tasks
    land.
    """
    del registry  # placeholder until M5 lands.


def _register_final_eval(registry: Registry) -> None:
    """Register Phase 5 final-eval steps.

    Wired up in M6 (impl plan T6.1-T6.3); a no-op until those tasks
    land.
    """
    del registry  # placeholder until M6 lands.


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resolve_out_dir(config: ShopGenConfig) -> Path:
    """Return ``config.out_dir`` or the default ``outputs/shops/<name>/``.

    A multi-seed run with no explicit ``name`` *and* no ``out_dir``
    has nothing to slug from until ``synth_identity`` runs (M3), so we
    refuse rather than guess a name the user can't predict.

    Args:
        config: Run configuration.

    Returns:
        Absolute-or-relative resolved workspace path.

    Raises:
        ValueError: Multi-seed run with neither ``name`` nor ``out_dir``.
    """
    if config.out_dir is not None:
        return config.out_dir

    name = config.name
    if name is None:
        if len(config.seeds) == 1:
            name = config.seeds[0].name
        else:
            raise ValueError(
                "auto-naming a multi-seed run requires `name` or `out_dir` "
                "(identity.descriptor synthesis lands in M3)",
            )
    return _DEFAULT_OUT_ROOT / name


def _result_for(out_dir: Path) -> ShopGenResult:
    """Build the :class:`ShopGenResult` for the canonical artifact layout.

    The paths are forward declarations: callers can ``Path.exists()``
    each one to see which artifacts the current step set actually
    produced. Mirrors spec §4.1.
    """
    return ShopGenResult(
        out_dir=out_dir,
        manual_dir=out_dir / "manual",
        identity_path=out_dir / "identity.json",
        data_dir=out_dir / "data",
        hydrogen_dir=out_dir / "hydrogen",
        data_validation_path=out_dir / "data_validation.json",
        final_eval_path=out_dir / "final_eval.json",
        build_run_dir=out_dir / "runs" / "build",
    )


__all__ = [
    "PHASES",
    "StatusReport",
    "StepStatusEntry",
    "list_steps",
    "run",
    "status",
]
