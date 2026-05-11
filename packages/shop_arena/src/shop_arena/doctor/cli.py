"""Command-line entrypoint for ``shop-doctor``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from shop_arena.doctor.checks import CheckResult, run_checks

EXIT_OK = 0
"""Successful run."""

EXIT_CHECK_FAILED = 1
"""One or more doctor checks failed."""

EXIT_USAGE = 2
"""Reserved by argparse for usage errors."""

PROG = "shop-doctor"
"""Console script name used in argparse help."""


def main(argv: list[str] | None = None) -> int:
    """Run ShopGym environment diagnostics.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` when every check passes, ``1`` when any check fails, and
        ``2`` for argparse usage errors.
    """
    _build_parser().parse_args(argv)
    results = run_checks()
    _print_report(results)
    if all(result.passed for result in results):
        return EXIT_OK
    return EXIT_CHECK_FAILED


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``shop-doctor`` argument parser."""
    return argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Validate local ShopGym browser tooling, including Python "
            "Playwright, Chromium, and the pi-playwright skill."
        ),
    )


def _print_report(results: Sequence[CheckResult]) -> None:
    """Print a human-readable doctor report."""
    print("ShopGym doctor")
    for result in results:
        status = "OK" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")
        if not result.passed and result.remedy is not None:
            print(f"       fix: {result.remedy}")

    if all(result.passed for result in results):
        print("All checks passed.")
    else:
        print("One or more checks failed.")
