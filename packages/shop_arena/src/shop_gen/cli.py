"""Command-line entrypoint for ``shop_gen``.

Implements the §5.8 CLI surface of
``docs/specs/shop_arena/shop_gen.md`` and impl plan task T1.5
(``docs/impl/shop_gen_implementation.md``):

* Default invocation runs every stale step (idempotent re-run).
* ``--from <step>`` re-runs ``<step>`` and every downstream descendant
  (force-stale + cascade via the runner's ``force_ids`` plumbing).
* ``--only <step>`` re-runs *just* ``<step>`` — currently routed through
  the same ``force_ids`` plumbing as ``--from``; the no-cascade-execute
  semantic from spec §5.7.4 is a runner enhancement tracked separately
  and lands when concrete steps require it.
* ``--status`` reads ``<out_dir>/.shop_gen/state.json`` and prints the
  per-step status table. Workspaces that have never been touched print
  ``"no run yet"``.
* ``--list-steps`` prints every registered step id grouped by phase.

The module is import-safe: it performs no I/O at import time; argument
parsing and dispatch happen only inside :func:`main`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from harness.plan import TaskStatus, parse
from harness.plan.parser import InvalidPlanError
from shop_gen.build.redo import RedoError, append_redo_task
from shop_gen.config import (
    DEFAULT_IMAGE_BACKEND,
    DEFAULT_MAX_ITERS,
    DEFAULT_MODEL_BY_RUNTIME,
    DEFAULT_RUNTIME,
    DEFAULT_VISUAL_RETRY_BUDGET,
    CatalogConfig,
    ImageBackend,
    RuntimeName,
    ShopGenConfig,
    default_model_for,
)
from shop_gen.pipeline import (
    PHASES,
    StatusReport,
    list_steps,
    resolve_out_dir,
    run,
    status,
)
from shop_gen.steps.runner import CycleError, MissingDependencyError

EXIT_OK = 0
"""Successful run."""

EXIT_USAGE = 2
"""Argparse usage errors and missing-required-argument failures."""

EXIT_CONFIG = 3
"""Invalid ``ShopGenConfig`` (pydantic ``ValidationError``) or unresolvable run workspace."""

EXIT_RUNTIME = 4
"""Step-level failure raised by :func:`shop_gen.pipeline.run`."""


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the matching pipeline entry point.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. ``0`` on success; ``2`` on argparse usage
        errors or a missing seed in the default run path; ``3`` for
        config-construction failures (invalid catalog scale, unknown
        ``--image-backend``, multi-seed default without ``--name``);
        ``4`` for runner failures (cycle / missing dep / step exception).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s shop-gen %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    if args.list_steps:
        return _run_list_steps()

    if args.status:
        return _run_status(args, parser)

    return _run_default(args, parser)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser described in spec §5.8."""
    parser = argparse.ArgumentParser(
        prog="shop-gen",
        description=("Generate a SandboxShop from one or more ``shop_explore`` seed manuals."),
    )
    parser.add_argument(
        "seeds",
        nargs="*",
        type=Path,
        metavar="SEED",
        help=(
            "One or more shop_manuals/<domain>/<run_id>/ seed directories. "
            "Required for the default run; unused with --status / --list-steps."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Run workspace directory. Defaults to outputs/shops/<name>/ where "
            "<name> is --name (if given), the seed directory name (single-seed), "
            "or the synthesised identity descriptor (multi-seed; requires --name "
            "until M3 lands synth_identity)."
        ),
    )
    parser.add_argument(
        "--name",
        default=None,
        metavar="SLUG",
        help="Slug for the SandboxShop. Defaults: see --out-dir.",
    )
    parser.add_argument(
        "--runtime",
        choices=("pi", "claude_code"),
        default=DEFAULT_RUNTIME,
        help=f"Agent runtime for the build-loop plan/exec phase. Default: {DEFAULT_RUNTIME!r}.",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help=(
            "Model identifier forwarded to the runtime as --model. Defaults are"
            " per-runtime: "
            f"{DEFAULT_MODEL_BY_RUNTIME['pi']!r} for runtime=pi, "
            f"{DEFAULT_MODEL_BY_RUNTIME['claude_code']!r} for runtime=claude_code."
            " Pass the empty string to skip the flag entirely and let the"
            " runtime use its own default."
        ),
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=DEFAULT_MAX_ITERS,
        metavar="N",
        help=f"Executor iteration budget for the build loop. Default: {DEFAULT_MAX_ITERS}.",
    )
    parser.add_argument(
        "--collections",
        type=int,
        default=None,
        metavar="N",
        help="Number of collections to synthesise (Phase 2). Default: catalog config default.",
    )
    parser.add_argument(
        "--products-per-collection",
        type=int,
        default=None,
        metavar="N",
        help="Products synthesised per collection (Phase 2).",
    )
    parser.add_argument(
        "--images-per-product",
        type=int,
        default=None,
        metavar="N",
        help="Image / alt-text pairs synthesised per product (Phase 2).",
    )
    parser.add_argument(
        "--image-backend",
        choices=("placeholder", "ai"),
        default=DEFAULT_IMAGE_BACKEND,
        help=(
            f"Image-generation backend. Default: {DEFAULT_IMAGE_BACKEND!r}. "
            "'ai' is stubbed in v0.1 (lands in M8)."
        ),
    )
    parser.add_argument(
        "--visual-retry-budget",
        type=int,
        default=DEFAULT_VISUAL_RETRY_BUDGET,
        metavar="N",
        help=(
            "Per-task cap on consecutive ``visual_judge`` FAILs before the verifier "
            "downgrades to ADVISORY (spec \u00a75.4). ``0`` disables the budget. "
            f"Default: {DEFAULT_VISUAL_RETRY_BUDGET}."
        ),
    )

    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--from",
        dest="from_step",
        default=None,
        metavar="STEP",
        help=(
            "Force-rerun <step> and every downstream descendant. Equivalent to "
            "marking <step> stale on disk and running the pipeline."
        ),
    )
    target.add_argument(
        "--only",
        dest="only_step",
        default=None,
        metavar="STEP",
        help=(
            "Re-run <step>. v0.1 plumbing routes this through the same force_ids "
            "path as --from; the spec §5.7.4 'no-cascade-execute' refinement "
            "lands when concrete steps require it."
        ),
    )
    parser.add_argument(
        "--to",
        dest="to_step",
        default=None,
        metavar="STEP",
        help=(
            "Stop the run at <step>: drops every step strictly downstream "
            "of <step> from the registry before execution, so only <step> "
            "and its transitive ancestors run. Composes with --from / --only."
        ),
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--status",
        action="store_true",
        help="Print the step status table for --out-dir and exit.",
    )
    mode.add_argument(
        "--list-steps",
        dest="list_steps",
        action="store_true",
        help="Print every registered step id grouped by phase and exit.",
    )

    return parser


def _run_list_steps() -> int:
    """Print the registered step ids grouped by phase."""
    grouped = list_steps()
    print("shop-gen pipeline steps (by phase):")
    for phase in PHASES:
        ids = grouped.get(phase, ())
        if ids:
            print(f"  {phase}:")
            for step_id in ids:
                print(f"    - {step_id}")
        else:
            print(f"  {phase}: (no steps registered)")
    return EXIT_OK


def _run_status(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Print the persisted step status table for ``--out-dir``."""
    if args.out_dir is None:
        parser.error("--status requires --out-dir")

    out_dir: Path = args.out_dir
    report = status(out_dir)
    _print_status(report)
    return EXIT_OK


def _print_status(report: StatusReport) -> None:
    """Render a :class:`StatusReport` to stdout."""
    if not report.has_run or not report.steps:
        print(f"shop-gen status for {report.out_dir}: no run yet")
        return

    rows = [
        (s.id, s.phase, s.status.value, s.fingerprint or "-", s.ts or "-") for s in report.steps
    ]
    headers = ("id", "phase", "status", "fingerprint", "ts")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(f"shop-gen status for {report.out_dir}:")
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*row))


def _run_default(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Build a :class:`ShopGenConfig` from ``args`` and run the pipeline."""
    if not args.seeds:
        parser.error("at least one SEED is required for the default run")

    try:
        config = _build_config(args)
    except ValidationError as exc:
        print(f"shop-gen: invalid configuration: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        force_ids, redo_message = _maybe_apply_redo(config, args)
    except InvalidPlanError as exc:
        print(f"shop-gen: cannot parse build plan.md: {exc}", file=sys.stderr)
        return EXIT_RUNTIME
    except RedoError as exc:
        print(f"shop-gen: redo failed: {exc}", file=sys.stderr)
        return EXIT_RUNTIME
    if redo_message is not None:
        print(redo_message, file=sys.stderr)

    try:
        run(config, force_ids=force_ids, stop_at=args.to_step)
    except (CycleError, MissingDependencyError) as exc:
        print(f"shop-gen: pipeline DAG error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME
    except ValueError as exc:
        # ``pipeline.run`` raises ValueError for the multi-seed-without-name
        # default-out_dir case. Surface as a config error, not a crash.
        print(f"shop-gen: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    return EXIT_OK


def _build_config(args: argparse.Namespace) -> ShopGenConfig:
    """Translate parsed args into a :class:`ShopGenConfig`.

    Catalog overrides are applied only when the user supplied a value;
    omitted flags fall back to :class:`CatalogConfig` defaults.
    """
    catalog_kwargs: dict[str, int] = {}
    if args.collections is not None:
        catalog_kwargs["collections"] = args.collections
    if args.products_per_collection is not None:
        catalog_kwargs["products_per_collection"] = args.products_per_collection
    if args.images_per_product is not None:
        catalog_kwargs["images_per_product"] = args.images_per_product
    catalog = CatalogConfig(**catalog_kwargs)

    runtime: RuntimeName = args.runtime
    # ``--model`` semantics:
    #   - omitted (None)  → fill the per-runtime application default.
    #   - empty string "" → explicit opt-out; pass None so no --model flag
    #                       is forwarded and the runtime's own default applies.
    #   - any other str   → forward verbatim (subject to grammar validation
    #                       in :class:`ShopGenConfig`).
    if args.model is None:
        model: str | None = default_model_for(runtime)
    elif args.model == "":
        model = None
    else:
        model = args.model

    image_backend: ImageBackend = args.image_backend

    return ShopGenConfig(
        seeds=tuple(args.seeds),
        out_dir=args.out_dir,
        name=args.name,
        runtime=runtime,
        model=model,
        catalog=catalog,
        max_iters=args.max_iters,
        image_backend=image_backend,
        visual_retry_budget=args.visual_retry_budget,
    )


_BUILD_LOOP_STEP_ID = "run_build_harness_loop"
"""Step id forced stale by an append-redo invocation (T5.7)."""

_BUILD_PLAN_REL = Path("runs") / "build" / "plan.md"
"""Run-relative path of the build harness loop's ``plan.md`` snapshot."""


def _resolve_force_ids(args: argparse.Namespace) -> frozenset[str]:
    """Map ``--from`` / ``--only`` to the runner's ``force_ids`` plumbing."""
    if args.from_step is not None:
        return frozenset({args.from_step})
    if args.only_step is not None:
        return frozenset({args.only_step})
    return frozenset()


def _maybe_apply_redo(
    config: ShopGenConfig,
    args: argparse.Namespace,
) -> tuple[frozenset[str], str | None]:
    """Run T5.7's append-redo when ``--only`` targets a DONE build-loop task.

    Spec §5.7.3 maps ``--only gen_<task>`` against a completed build dir to:

    1. Append a fresh ``<task>_redo_<N>`` PENDING bullet to
       ``runs/build/plan.md``.
    2. Force-rerun ``run_build_harness_loop`` so the harness re-enters
       resume mode (``force=True`` in v0.1) and selects the new task.

    The ``--only`` flag still routes through the runner's ``force_ids``
    plumbing for *Python* steps; this helper only intercepts when the
    flag's argument matches a ``[x]`` task id in the build-loop
    ``plan.md``. Any other case (no ``--only``, no out_dir on disk, no
    ``plan.md``, or the id refers to a Python step / unknown id) falls
    through to the regular force-ids path.

    Returns:
        Tuple of (force_ids, redo_message). ``redo_message`` is ``None``
        when no redo was triggered; otherwise it carries the human-
        readable summary the CLI prints to stderr before invoking
        :func:`shop_gen.pipeline.run`.

    Raises:
        harness.plan.parser.InvalidPlanError: ``plan.md`` is structurally
            invalid. The CLI maps this to :data:`EXIT_RUNTIME`.
        shop_gen.build.redo.RedoError: The append-redo request itself
            failed (target id unknown or non-DONE). Mapped to
            :data:`EXIT_RUNTIME` by the CLI.
    """
    force_ids = _resolve_force_ids(args)
    if args.only_step is None:
        return force_ids, None

    try:
        out_dir = resolve_out_dir(config)
    except ValueError:
        # Multi-seed without --name. The downstream ``run()`` call
        # raises the same error so the existing handler in
        # :func:`_run_default` reports it as a config error.
        return force_ids, None
    plan_path = out_dir / _BUILD_PLAN_REL
    if not plan_path.is_file():
        return force_ids, None

    plan = parse(plan_path.read_text(encoding="utf-8"))

    target = plan.by_id(args.only_step)
    if target is None or target.status is not TaskStatus.DONE:
        return force_ids, None

    new_id = append_redo_task(plan_path, args.only_step)

    message = f"shop-gen: appended {new_id!r} to {plan_path}; forcing {_BUILD_LOOP_STEP_ID!r}"
    return frozenset({_BUILD_LOOP_STEP_ID}), message


__all__ = [
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_RUNTIME",
    "EXIT_USAGE",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
