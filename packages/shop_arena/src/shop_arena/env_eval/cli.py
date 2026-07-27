"""Command-line entrypoint for ``shop-env-eval``.

Implements the §5.9 CLI surface of ``docs/specs/shop_arena/env_eval.md``.

The CLI wires three subcommands:

* ``shop-env-eval run <url>`` evaluates a single shop URL via
  :func:`shop_arena.env_eval.pipeline.evaluate` and prints the resulting
  ``metrics.json`` path on stdout (success criterion SC1).
* ``shop-env-eval visualize <run_dir>`` renders the run's transition
  graph as an interactive HTML page via
  :func:`shop_arena.env_eval.visualize.render_graph_html` and prints the
  written path on stdout.
* ``shop-env-eval compare <url> <url> [...]`` evaluates a URL cohort and
  writes deterministic structural snapshots plus ``variance.json``.

Argparse rejects unknown subcommands with a usage error.

The module is import-safe: it performs no I/O at import time; argument
parsing and dispatch happen only inside :func:`main`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from shop_arena.env_eval.config import (
    DEFAULT_MAX_HOPS,
    DEFAULT_PAGES_CLASSIFIER_MODEL,
    DEFAULT_RUBRIC_MODEL,
    DEFAULT_VIEWPORT,
    EvalConfig,
)
from shop_arena.env_eval.errors import EnvEvalError
from shop_arena.env_eval.pipeline import evaluate
from shop_arena.env_eval.structure.compare import CompareConfig, compare_urls
from shop_arena.env_eval.visualize import render_graph_html
from shop_arena.util._dotenv import load_project_env
from shop_arena.util._llm import LLMConfigError

EXIT_OK = 0
"""Successful run."""

EXIT_USAGE = 2
"""Reserved by argparse for usage errors; also used for env-eval failures."""

PROG = "shop-env-eval"
"""Console script name used in error prefixes (matches ``[project.scripts]``)."""


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the matching subcommand handler.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. ``0`` on success; ``2`` on argparse usage
        errors, invalid configuration, or any
        :class:`shop_arena.env_eval.errors.EnvEvalError` raised by the
        pipeline.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        # Surface provider credentials before the optional rubric client reads
        # the environment. Structural comparison is deliberately LLM-free and
        # does not load project credentials.
        load_project_env()
        return _run(args)
    if args.command == "visualize":
        return _visualize(args)
    if args.command == "compare":
        return _compare(args)
    # argparse with ``required=True`` rejects missing/unknown subcommands
    # before reaching this branch; the fallback exists so future
    # subcommands cannot silently no-op.
    parser.error(f"unknown command: {args.command!r}")
    return EXIT_USAGE  # pragma: no cover — parser.error raises SystemExit


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser described in spec §5.9."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Evaluate hosted SandboxShops and optionally compare their "
            "website structure. Per-shop artifacts are written under "
            "outputs/shop_env_evals/."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = sub.add_parser(
        "run",
        help="Evaluate a single shop URL.",
        description=(
            "Discover sample pages, capture observation/action/transition "
            "artifacts, and write a closed-schema metrics.json. Prints the "
            "metrics.json path on stdout."
        ),
    )
    run.add_argument(
        "url",
        help="Public storefront base URL (http:// or https://).",
    )
    run.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Run workspace directory. Defaults to "
            "outputs/shop_env_evals/<shop_name>/<run_id>/. An existing "
            "directory triggers resume mode (spec §5.7)."
        ),
    )
    run.add_argument(
        "--viewport",
        type=_parse_viewport,
        default=None,
        metavar="WIDTHxHEIGHT",
        help=(
            "Desktop viewport. Defaults to "
            f"{DEFAULT_VIEWPORT[0]}x{DEFAULT_VIEWPORT[1]}; v0.1 only "
            "supports a single viewport."
        ),
    )
    run.add_argument(
        "--max-hops",
        type=int,
        default=None,
        metavar="N",
        help=(
            "BFS depth for the transition graph. Defaults to "
            f"{DEFAULT_MAX_HOPS}; pass 0 to disable the BFS pass."
        ),
    )
    run.add_argument(
        "--rubric-model",
        default=None,
        metavar="MODEL",
        help=(
            "Model id for the screenshot rubric (provider routed by "
            f"prefix). Defaults to {DEFAULT_RUBRIC_MODEL!r}."
        ),
    )
    run.add_argument(
        "--pages-classifier-model",
        default=None,
        metavar="MODEL",
        help=(
            "Model id for the /pages/<slug> classifier (provider routed "
            f"by prefix). Defaults to {DEFAULT_PAGES_CLASSIFIER_MODEL!r}. "
            "Honoured only when --no-rubric is not set; otherwise the "
            "classifier stubs out alongside the rubric."
        ),
    )
    run.add_argument(
        "--no-rubric",
        action="store_true",
        help=(
            "Skip the LLM rubric and write a stub *.rubric.json so "
            "metrics.json stays schema-valid (spec §5.3). Also stubs the "
            "/pages/<slug> classifier so no LLM calls are issued."
        ),
    )
    run.add_argument(
        "--rediscover",
        action="store_true",
        help=("Ignore an existing pages.json and re-run page selection (spec §5.2 / §5.7)."),
    )
    run.add_argument(
        "--shop-name",
        default=None,
        metavar="NAME",
        help=(
            "Override the <shop_name> directory segment. Defaults to the "
            "URL hostname (impl-plan M0 decision)."
        ),
    )

    visualize = sub.add_parser(
        "visualize",
        help="Render an EnvEval run's transition graph as an interactive HTML page.",
        description=(
            "Read <run_dir>/transition/graph.json and write a self-contained "
            "HTML file (vis-network from CDN) with seeds, discovered URL "
            "nodes, and stateful state nodes color-coded. Prints the written "
            "HTML path on stdout."
        ),
    )
    visualize.add_argument(
        "run_dir",
        type=Path,
        metavar="RUN_DIR",
        help="EnvEval run directory containing transition/graph.json.",
    )
    visualize.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help=("Output HTML path. Defaults to <run_dir>/transition/graph.html."),
    )

    compare = sub.add_parser(
        "compare",
        help="Measure structural variance across hosted shop URLs.",
        description=(
            "Evaluate at least two hosted shops, derive content-independent "
            "navigation and accessibility-role profiles without LLM calls, "
            "and write variance.json. Prints the report path on stdout."
        ),
    )
    compare.add_argument(
        "urls",
        nargs="+",
        metavar="URL",
        help="Hosted storefront URLs. At least two are required.",
    )
    compare.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Comparison directory. Defaults to "
            "outputs/shop_env_evals/comparisons/<run_id>/. Existing child "
            "run directories use normal EnvEval resume behavior."
        ),
    )
    compare.add_argument(
        "--viewport",
        type=_parse_viewport,
        default=None,
        metavar="WIDTHxHEIGHT",
        help=f"Desktop viewport. Defaults to {DEFAULT_VIEWPORT[0]}x{DEFAULT_VIEWPORT[1]}.",
    )
    compare.add_argument(
        "--max-hops",
        type=int,
        default=None,
        metavar="N",
        help=f"BFS depth for each transition graph. Defaults to {DEFAULT_MAX_HOPS}.",
    )
    compare.add_argument(
        "--rediscover",
        action="store_true",
        help="Re-run page selection in every child EnvEval run.",
    )

    return parser


def _parse_viewport(value: str) -> tuple[int, int]:
    """Parse ``WIDTHxHEIGHT`` (case-insensitive) into a ``(width, height)`` tuple.

    Raises :class:`argparse.ArgumentTypeError` on malformed input so
    argparse surfaces a clear ``--viewport`` usage error.
    """
    width_str, _, height_str = value.lower().partition("x")
    if not width_str or not height_str or "x" in height_str:
        raise argparse.ArgumentTypeError(
            f"viewport must be 'WIDTHxHEIGHT' (got {value!r})",
        )
    try:
        width, height = int(width_str), int(height_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"viewport must be 'WIDTHxHEIGHT' with integer dims (got {value!r})",
        ) from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(
            f"viewport dims must be positive (got {value!r})",
        )
    return (width, height)


def _run(args: argparse.Namespace) -> int:
    """Build an :class:`EvalConfig` from ``args`` and invoke ``evaluate``."""
    kwargs: dict[str, Any] = {"url": args.url}
    if args.out is not None:
        kwargs["out_dir"] = args.out
    if args.viewport is not None:
        kwargs["viewport"] = args.viewport
    if args.max_hops is not None:
        kwargs["max_hops"] = args.max_hops
    if args.rubric_model is not None:
        kwargs["rubric_model"] = args.rubric_model
    if args.pages_classifier_model is not None:
        kwargs["pages_classifier_model"] = args.pages_classifier_model
    if args.no_rubric:
        kwargs["no_rubric"] = True
    if args.rediscover:
        kwargs["rediscover"] = True
    if args.shop_name is not None:
        kwargs["shop_name"] = args.shop_name

    try:
        config = EvalConfig(**kwargs)
    except ValidationError as exc:
        print(f"{PROG}: invalid configuration: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        result = evaluate(config)
    except (EnvEvalError, LLMConfigError) as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(str(result.metrics_path))
    return EXIT_OK


def _visualize(args: argparse.Namespace) -> int:
    """Render the run's transition graph and print the output HTML path."""
    try:
        out_path = render_graph_html(args.run_dir, out_path=args.out)
    except EnvEvalError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(str(out_path))
    return EXIT_OK


def _compare(args: argparse.Namespace) -> int:
    """Build a :class:`CompareConfig`, evaluate its URLs, and print the report."""
    kwargs: dict[str, Any] = {"urls": tuple(args.urls)}
    if args.out is not None:
        kwargs["out_dir"] = args.out
    if args.viewport is not None:
        kwargs["viewport"] = args.viewport
    if args.max_hops is not None:
        kwargs["max_hops"] = args.max_hops
    if args.rediscover:
        kwargs["rediscover"] = True

    try:
        config = CompareConfig(**kwargs)
    except ValidationError as exc:
        print(f"{PROG}: invalid comparison configuration: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        result = compare_urls(config)
    except EnvEvalError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(str(result.report_path))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
