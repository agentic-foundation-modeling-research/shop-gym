"""Pipeline orchestrator for ``shop_arena.gen`` runs.

Implements the public entry points described in
``docs/specs/shop_arena/shop_arena.gen.md`` §5.7-§5.8 and the impl plan task
T1.6 (``docs/impl/shop_gen_implementation.md``):

* :func:`run` — resolve the run workspace, build the config-aware step
  registry, and drive :func:`shop_arena.gen.steps.runner.run_pipeline` against
  it. Returns a :class:`~shop_arena.gen.config.ShopGenResult` whose paths
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

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from harness.runtimes import LLMCompleter, get_runtime
from shop_arena.explore.pipeline import resolve_playwright_skill_dir
from shop_arena.gen.build import (
    CloneTemplateStep,
    RunBuildHarnessLoopStep,
    StartSidecarStep,
    WriteEnvFileStep,
)
from shop_arena.gen.build.verifiers._task_routes import BucketCaps
from shop_arena.gen.config import ShopGenConfig, ShopGenResult
from shop_arena.gen.data_synth import (
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
from shop_arena.gen.data_validation import ValidateHostingStep, ValidateSchemaStep
from shop_arena.gen.final_eval import FinalEvalStep
from shop_arena.gen.manual_merge import (
    ComputeMergeStatsStep,
    CopySeedManualStep,
    MergeCapabilitiesStep,
    MergeManualProseStep,
    SplitManualPartsStep,
    WriteMergeManifestStep,
)
from shop_arena.gen.steps.base import Step, StepContext, StepStatus
from shop_arena.gen.steps.runner import (
    MissingDependencyError,
    Registry,
    RunResult,
    run_pipeline,
    select_ancestors_inclusive,
)
from shop_arena.gen.steps.state import read_state, state_path
from shop_arena.gen.template_registry import get_template

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

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


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
    stop_at: str | None = None,
    runtime: LLMCompleter | None = None,
) -> ShopGenResult:
    """Execute the ``shop_arena.gen`` pipeline for ``config``.

    Resolves the run workspace, builds the config-aware step registry
    (phase-aware: spec §5.2 + §5.7.2), and drives every stale step in
    topological order via :func:`shop_arena.gen.steps.runner.run_pipeline`.
    Returns a :class:`~shop_arena.gen.config.ShopGenResult` whose paths point
    at the *expected* published artifacts under ``<out_dir>/``;
    callers can inspect each path on disk to see which artifacts the
    current step set actually produced.

    Args:
        config: Validated run configuration.
        force_ids: Step ids to force-run regardless of their stored
            fingerprint. Plumbing for the CLI's ``--from`` / ``--only``
            flags (spec §5.7.4); downstream descendants cascade to
            stale via :func:`shop_arena.gen.steps.runner.compute_staleness`.
        stop_at: Optional step id at which to halt the run. When set,
            the registry is sliced to ``stop_at`` and every transitive
            ancestor via :func:`shop_arena.gen.steps.runner.select_ancestors_inclusive`
            — every step strictly downstream is dropped before
            execution. Plumbing for the CLI's ``--to`` flag.
        runtime: Optional :class:`LLMCompleter` to wire into
            :class:`StepContext.runtime`. When ``None`` (the CLI default)
            a runtime is resolved from ``config`` via
            :func:`harness.runtimes.get_runtime` so Phase 2 synth steps
            and the Phase 5 judge can issue their one-shot completions.
            Library callers pass an explicit completer to bypass the
            real runtime (tests, custom providers).

    Returns:
        A :class:`~shop_arena.gen.config.ShopGenResult` anchored at the
        resolved ``out_dir``.

    Raises:
        ValueError: ``config.out_dir`` is ``None`` and a default cannot
            be derived (multi-seed without an explicit ``name``); or
            ``stop_at`` is not a registered step id; or a member of
            ``force_ids`` is not in the upstream cone of ``stop_at``.
        TypeError: The runtime resolved from ``config.runtime`` does
            not implement :class:`LLMCompleter` (registered runtimes
            ``pi`` and ``claude_code`` both do).
        shop_arena.gen.steps.runner.CycleError: ``depends_on`` contains a
            cycle.
        shop_arena.gen.steps.runner.MissingDependencyError: A registered
            step references an unregistered upstream id.
        Exception: Any exception raised by a registered ``Step.run`` is
            re-raised after the runner persists ``StepStatus.FAILED``.
    """
    out_dir = resolve_out_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)

    registry = _build_registry(config)
    steps: list[Step] = registry.all()
    if stop_at is not None:
        try:
            steps = select_ancestors_inclusive(steps, stop_at)
        except MissingDependencyError as exc:
            raise ValueError(str(exc)) from exc
        kept_ids = {step.id for step in steps}
        outside = sorted(force_ids - kept_ids)
        if outside:
            raise ValueError(
                f"force_ids {outside!r} are not in the upstream cone of --to {stop_at!r}",
            )
    if runtime is None:
        runtime = _resolve_runtime(config)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=runtime)

    _LOGGER.info(
        "start run — out_dir=%s seeds=%d runtime=%s model=%s%s%s",
        out_dir,
        len(config.seeds),
        config.runtime,
        config.model or "<runtime default>",
        f" stop_at={stop_at}" if stop_at is not None else "",
        f" force_ids={sorted(force_ids)}" if force_ids else "",
    )
    start = time.monotonic()
    result: RunResult = run_pipeline(steps, ctx, force_ids=force_ids)
    elapsed = time.monotonic() - start
    _LOGGER.info(
        "end run   — ran=%d skipped=%d total=%s",
        len(result.ran),
        len(result.skipped),
        _format_elapsed(elapsed),
    )

    return _result_for(out_dir, config=config)


_SECONDS_PER_MINUTE: Final[int] = 60
_MINUTES_PER_HOUR: Final[int] = 60


def _format_elapsed(seconds: float) -> str:
    """Format a wall-clock duration as ``MmSS.SSs`` or ``Ss.SSs``.

    Picks a human-friendly granularity for run summaries: bare seconds
    when the run is sub-minute, ``MmSSs`` for minute-scale runs,
    ``HhMMm`` for the rare hour-scale run.
    """
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds:.2f}s"
    minutes, secs = divmod(seconds, _SECONDS_PER_MINUTE)
    if minutes < _MINUTES_PER_HOUR:
        return f"{int(minutes)}m{secs:04.1f}s"
    hours, minutes = divmod(int(minutes), _MINUTES_PER_HOUR)
    return f"{hours}h{minutes:02d}m"


def _resolve_runtime(config: ShopGenConfig) -> LLMCompleter:
    """Resolve a runtime instance for the run via :func:`harness.runtimes.get_runtime`.

    Mirrors the build-loop's runtime factory: ``model=None`` is dropped
    from the kwargs so the runtime adapter sees no ``model`` keyword on
    opt-out (spec §5.8 ``--model ""`` semantics). For ``pi`` runs, the
    workspace-pinned ``pi-playwright`` skill is passed explicitly so
    final-eval visual-sweep iterations can use browser tools while
    ambient skill discovery remains disabled. The runtime is
    narrowed to :class:`LLMCompleter` because Phase 2 synth steps and
    the Phase 5 judge invoke ``ctx.runtime.complete``; both registered
    runtimes (``pi`` and ``claude_code``) implement the sub-protocol.

    Args:
        config: Run configuration. ``config.runtime`` keys the registry
            lookup; ``config.model`` (when not ``None``) is forwarded as
            ``--model``. ``pi`` runtimes also receive the resolved
            playwright skill path when it is available.

    Returns:
        A runtime instance narrowed to :class:`LLMCompleter`.

    Raises:
        TypeError: The resolved runtime does not implement
            :class:`LLMCompleter`. Cannot occur with the v0.1
            registry; defensive check for future runtime additions.
    """
    kwargs: dict[str, object] = {}
    if config.model is not None:
        kwargs["model"] = config.model
    if config.runtime == "pi":
        skill_dir = resolve_playwright_skill_dir()
        if skill_dir is None:
            _LOGGER.warning(
                "pi-playwright skill not found for shop-gen runtime; final-eval "
                "visual browser iterations may fail unless the runtime can "
                "resolve browser tooling itself.",
            )
        else:
            kwargs["skill_paths"] = [skill_dir]
            _LOGGER.info("using pi-playwright skill for shop-gen runtime: %s", skill_dir)
    runtime = get_runtime(config.runtime, **kwargs)
    if not isinstance(runtime, LLMCompleter):
        raise TypeError(
            f"runtime {config.runtime!r} does not implement LLMCompleter; "
            "Phase 2 data-synth steps require completer support",
        )
    return runtime


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
        manual_step_ids: tuple[str, ...] = (
            "merge_capabilities",
            "merge_manual_prose",
            "split_manual_parts",
        )
        stats_aware_manual_step_ids: tuple[str, ...] = (
            "merge_capabilities",
            "merge_manual_prose",
            "split_manual_parts",
            "compute_merge_stats",
        )
    else:
        _register_single_seed_manual(registry, config=config)
        manual_step_ids = ("copy_seed_manual", "split_manual_parts")
        stats_aware_manual_step_ids = manual_step_ids
    _register_data_synth(
        registry,
        manual_step_ids=manual_step_ids,
        stats_aware_manual_step_ids=stats_aware_manual_step_ids,
    )
    _register_data_validation(registry)
    _register_build(registry, config=config)
    _register_final_eval(registry, config=config)
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
    registry.register(SplitManualPartsStep(upstream_step_id="merge_manual_prose"))
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
    registry.register(SplitManualPartsStep(upstream_step_id="copy_seed_manual"))


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
            :func:`shop_arena.gen.pipeline.list_steps`.
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

    Registers ``validate_schema`` (T4.1) and ``validate_hosting``
    (T4.2) — the in-memory closed-schema check feeding the
    boot-and-query hosting check that publishes ``data_validation.json``.
    """
    registry.register(ValidateSchemaStep())
    registry.register(ValidateHostingStep())


def _register_build(registry: Registry, *, config: ShopGenConfig | None = None) -> None:
    """Register Phase 4 build-harness-loop steps.

    Registers the env-setup pair from impl plan T5.1, the
    ``start_sidecar`` step from T5.2, and the ``run_build_harness_loop``
    driver from T5.6:

    * ``clone_template`` copies the vendored Hydrogen template into
      ``<out_dir>/hydrogen/``.
    * ``write_env_file`` picks a free port and writes
      ``hydrogen/.env`` with the resolved sidecar URL (spec §5.5.1).
    * ``start_sidecar`` boots ``shop-backend`` against the assembled
      ``data/`` tree on that port to validate the spawn sequence and
      records the verdict in ``sidecar.json``.
    * ``run_build_harness_loop`` wires
      :class:`harness.PlanExecLoopConfig` against the prompts +
      verifier set, spawns the long-lived sidecar, and invokes
      :func:`harness.run_plan_exec_loop` (spec §5.5).
    """
    template_id = config.template if config is not None else "hydrogen"
    registry.register(CloneTemplateStep(template_id=template_id))
    registry.register(WriteEnvFileStep(template_id=template_id))
    registry.register(StartSidecarStep(template_id=template_id))
    registry.register(RunBuildHarnessLoopStep(template_id=template_id))


def _register_final_eval(registry: Registry, *, config: ShopGenConfig | None = None) -> None:
    """Register Phase 5 final-eval steps.

    Registers the advisory ``final_eval`` step from impl plan T6.3:
    drives the playwright smoke flow + LLM judge against the post-build
    hydrogen tree and writes ``<out_dir>/final_eval.json``. The step is
    advisory per spec §5.5.5 — verdict failures and transport errors
    are recorded into the verdict file rather than re-raised.
    """
    if config is not None:
        caps = BucketCaps(
            max_collections=config.final_eval_max_collections,
            products_per_collection=config.final_eval_products_per_collection,
            max_pages=config.final_eval_max_pages,
        )
        registry.register(
            FinalEvalStep(
                visual_caps=caps,
                visual_timeout_s=config.final_eval_visual_timeout_s,
                visual_max_concurrency=config.final_eval_visual_max_concurrency,
                visual_pass_threshold=config.visual_judge_pass_threshold,
            ),
        )
    else:
        registry.register(FinalEvalStep())


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def resolve_out_dir(config: ShopGenConfig) -> Path:
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


def _result_for(out_dir: Path, *, config: ShopGenConfig) -> ShopGenResult:
    """Build the :class:`ShopGenResult` for the canonical artifact layout.

    The paths are forward declarations: callers can ``Path.exists()``
    each one to see which artifacts the current step set actually
    produced. Mirrors spec §4.1.
    """
    template = get_template(config.template)
    return ShopGenResult(
        out_dir=out_dir,
        manual_dir=out_dir / "manual",
        identity_path=out_dir / "identity.json",
        data_dir=out_dir / "data",
        hydrogen_dir=out_dir / "hydrogen",
        storefront_dir=out_dir / template.app_dir,
        template_metadata_path=out_dir / ".shop_gen" / "template.json",
        data_validation_path=out_dir / "data_validation.json",
        final_eval_path=out_dir / "final_eval.json",
        build_run_dir=out_dir / "runs" / "build",
    )


__all__ = [
    "PHASES",
    "StatusReport",
    "StepStatusEntry",
    "list_steps",
    "resolve_out_dir",
    "run",
    "status",
]
