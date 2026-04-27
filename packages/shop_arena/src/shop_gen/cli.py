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

from shop_gen.config import (
    DEFAULT_IMAGE_BACKEND,
    DEFAULT_MAX_ITERS,
    DEFAULT_MODEL,
    DEFAULT_RUNTIME,
    CatalogConfig,
    ImageBackend,
    RuntimeName,
    ShopGenConfig,
)
from shop_gen.pipeline import (
    PHASES,
    StatusReport,
    list_steps,
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
        format="shop-gen: %(message)s",
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
        default=DEFAULT_MODEL,
        metavar="MODEL",
        help=(
            "Model identifier forwarded to the runtime as --model. Default: "
            f"{DEFAULT_MODEL!r}. Pass the empty string to skip the flag and let "
            "the runtime use its own default."
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

    force_ids = _resolve_force_ids(args)

    try:
        run(config, force_ids=force_ids)
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

    # Empty --model means "skip the flag and let the runtime pick its default".
    model: str | None = args.model if args.model != "" else None

    runtime: RuntimeName = args.runtime
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
    )


def _resolve_force_ids(args: argparse.Namespace) -> frozenset[str]:
    """Map ``--from`` / ``--only`` to the runner's ``force_ids`` plumbing."""
    if args.from_step is not None:
        return frozenset({args.from_step})
    if args.only_step is not None:
        return frozenset({args.only_step})
    return frozenset()


__all__ = [
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_RUNTIME",
    "EXIT_USAGE",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
