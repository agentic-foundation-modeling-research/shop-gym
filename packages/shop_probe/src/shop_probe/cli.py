"""Command-line entrypoint for ShopProbe."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Run the ShopProbe CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    _ = argv if argv is not None else sys.argv[1:]
    print("shop-probe: not implemented yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
