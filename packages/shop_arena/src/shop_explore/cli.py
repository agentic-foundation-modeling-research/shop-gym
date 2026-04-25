"""Command-line entrypoint for ``shop_explore``.

Implements the §5.11 CLI surface of
``docs/specs/shop_arena/shop_explore.md``. v0.1 wires the
``--prefetch-only`` debug path that runs §5.9 and exits; the full
pipeline (default invocation and ``--synthesize-only``) is wired in
later milestones (M2/M3) once :mod:`shop_explore.pipeline` exists.

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from shop_explore.config import DEFAULT_MAX_ITERS, DEFAULT_TIMEOUT_SECONDS
from shop_explore.prefetch import ShopUnreachableError
from shop_explore.prefetch import run as run_prefetch

EXIT_OK = 0
"""Successful run."""

EXIT_USAGE = 2
"""Reserved by argparse for usage errors; also used for storefront errors."""


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the matching handler.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. ``0`` on success; ``2`` if the storefront is
        unreachable (bot-block, robots.txt deny, network error) or if
        the requested mode is not yet wired.
    """
    args = _build_parser().parse_args(argv)

    if args.prefetch_only:
        return _run_prefetch_only(args)

    print(
        "shop-explore: the full pipeline is not yet wired in this build; "
        "pass --prefetch-only to seed prefetch artifacts.",
        file=sys.stderr,
    )
    return EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser described in spec §5.11."""
    parser = argparse.ArgumentParser(
        prog="shop-explore",
        description=(
            "Explore a public storefront and emit a Shop Manual under "
            "outputs/shop_manuals/<domain>/<run_id>/."
        ),
    )
    parser.add_argument(
        "url",
        help="Public storefront base URL (http:// or https://).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help=("Run workspace directory. Defaults to outputs/shop_manuals/<domain>/<run_id>/."),
    )
    parser.add_argument(
        "--runtime",
        choices=("pi", "claude_code"),
        default="pi",
        help="Agent runtime for the plan/exec loop (used by full pipeline).",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=DEFAULT_MAX_ITERS,
        metavar="N",
        help="Executor iteration budget (used by full pipeline).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="Per-iteration timeout in seconds (used by full pipeline).",
    )
    parser.add_argument(
        "--prefetch-only",
        action="store_true",
        help="Run the §5.9 prefetch step and exit; useful for debugging.",
    )
    return parser


def _run_prefetch_only(args: argparse.Namespace) -> int:
    """Execute the ``--prefetch-only`` path: §5.9 prefetch then exit."""
    out_dir = args.out if args.out is not None else _default_run_dir(args.url)
    dest_dir = out_dir / "artifact" / "prefetch"
    try:
        result = run_prefetch(args.url, dest_dir=dest_dir)
    except ShopUnreachableError as exc:
        print(f"shop-explore: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"shop-explore: wrote {len(result.entries)} prefetch entries to {dest_dir}",
    )
    return EXIT_OK


def _default_run_dir(url: str) -> Path:
    """Compute ``outputs/shop_manuals/<domain>/<run_id>/`` for ``url``.

    ``run_id`` is a UTC timestamp plus an 8-char random suffix; this is
    enough for human-readable run isolation without coordinating with
    other processes.
    """
    domain = urlsplit(url).hostname or "unknown"
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    return Path("outputs") / "shop_manuals" / domain / run_id


if __name__ == "__main__":
    raise SystemExit(main())
