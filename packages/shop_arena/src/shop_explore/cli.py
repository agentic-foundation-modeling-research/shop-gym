"""Command-line entrypoint for ``shop_explore``.

Implements the §5.11 CLI surface of
``docs/specs/shop_arena/shop_explore.md``. v0.1 wires two debug paths:

* ``--prefetch-only`` runs §5.9 against the supplied URL and exits.
* ``--synthesize-only PATH`` re-runs §5.10 against an existing
  ``run_dir`` (the M3 mirror of the legacy ``--merge-only`` flag).

Default invocation (no flag) drives the full pipeline through
:mod:`shop_explore.pipeline`. The synthesis step inside that pipeline
uses a no-op LLM client today and falls back to deterministic
concatenation of ``parts/*.md`` (§5.10 fallback path); a real LLM
client is wired in a later milestone.

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from shop_explore.config import DEFAULT_MAX_ITERS, DEFAULT_TIMEOUT_SECONDS, ExploreConfig
from shop_explore.pipeline import explore
from shop_explore.prefetch import ShopUnreachableError
from shop_explore.prefetch import run as run_prefetch
from shop_explore.synthesize import (
    SynthesisError,
)
from shop_explore.synthesize import (
    synthesize as run_synthesize,
)

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
        unreachable (bot-block, robots.txt deny, network error), if the
        ``--synthesize-only`` ``run_dir`` is missing or its layout is
        invalid, or on argparse usage errors.
    """
    args = _build_parser().parse_args(argv)

    if args.prefetch_only:
        return _run_prefetch_only(args)

    if args.synthesize_only is not None:
        return _run_synthesize_only(args)

    return _run_explore(args)


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
    parser.add_argument(
        "--synthesize-only",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Re-run §5.10 synthesis against an existing run_dir; mirrors "
            "the legacy --merge-only flag. Skips prefetch and the harness loop."
        ),
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


def _run_synthesize_only(args: argparse.Namespace) -> int:
    """Execute the ``--synthesize-only PATH`` path: §5.10 against ``PATH``."""
    run_dir: Path = args.synthesize_only
    if not run_dir.is_dir():
        print(
            f"shop-explore: --synthesize-only PATH must be an existing directory: {run_dir}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    manual_prompt = _load_manual_prompt()
    try:
        result = run_synthesize(run_dir, llm=_NoOpLLMClient(), manual_prompt=manual_prompt)
    except SynthesisError as exc:
        print(f"shop-explore: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"shop-explore: synthesized {result.manual_path} "
        f"(manual_fallback={str(result.manual_fallback).lower()})",
    )
    return EXIT_OK


def _run_explore(args: argparse.Namespace) -> int:
    """Execute the default invocation: full pipeline via :func:`shop_explore.pipeline.explore`."""
    config = ExploreConfig(
        url=args.url,
        out_dir=args.out,
        runtime=args.runtime,
        max_iters=args.max_iters,
        timeout=args.timeout,
    )
    try:
        result = explore(config)
    except ShopUnreachableError as exc:
        print(f"shop-explore: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except SynthesisError as exc:
        print(f"shop-explore: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"shop-explore: wrote manual to {result.manual_path} "
        f"(harness final_status={result.final_status.value})",
    )
    return EXIT_OK


def _load_manual_prompt() -> str:
    """Read the bundled ``synthesize_manual.md`` prompt resource."""
    prompts_dir = Path(__file__).resolve().parent / "prompts"
    return (prompts_dir / "synthesize_manual.md").read_text(encoding="utf-8")


class _NoOpLLMClient:
    """LLM client that always returns ``""`` (forces §5.10 fallback).

    The CLI v0.1 does not wire a real LLM yet; ``--synthesize-only``
    therefore always emits a fallback ``manual.md`` rendered as the
    deterministic concatenation of ``parts/*.md``. A future milestone
    will plug in an :class:`~shop_explore.synthesize.LLMClient`
    selectable via ``--runtime``.
    """

    def complete(self, prompt: str) -> str:
        """Return ``""`` to force the synthesis fallback path."""
        return ""


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
