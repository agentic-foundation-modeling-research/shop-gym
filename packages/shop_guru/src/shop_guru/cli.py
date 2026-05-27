"""Command-line entry points.

Installed as ``shop-guru`` via ``pyproject.toml``. Also runnable as
``python -m shop_guru``.

Two subcommands:

- ``shop-guru build`` — synthesize benchmark JSONs from extracted shop
  data. Writes one file per shop into
  ``<repo>/outputs/shop_guru/<slug>/benchmarks/`` (sibling to per-shop
  eval study dirs). Shop data is read from ``<repo>/<shop.data_dir>/data/``,
  which is where ``shop_arena`` emits extracted storefronts (typically
  ``outputs/shops/<domain>``).
- ``shop-guru eval`` — drive a browsing agent against the generated
  benchmarks and emit per-task + aggregate result JSONs. Forwards to
  :mod:`shop_guru.eval.run_all`.

Examples::

    # Emit per-shop benchmarks for every shop in configs/default.yaml:
    shop-guru build

    # Only one shop:
    shop-guru build --shop mock_shop

    # Also emit a flat mirror (per-shop + merged):
    shop-guru build --flat-out outputs/benchmarks

    # Run evaluation against a generated shop:
    shop-guru eval --shop mock_shop
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shop_guru.pipeline import build_all
from shop_guru.validate import has_errors


def _search_paths(filename: str) -> list[Path]:
    """Return candidate paths to probe for a bundled file.

    Order:
    1. ``<cwd>/<filename>`` — run from inside the package dir.
    2. ``<cwd>/packages/shop_guru/<filename>`` — run from shop-arena root.
    3. ``<file>/../../../<filename>`` — editable install alongside the source.
    """
    cwd = Path.cwd()
    here = Path(__file__).resolve()
    return [
        cwd / filename,
        cwd / "packages" / "shop_guru" / filename,
        here.parents[2] / filename,
    ]


def _default_config() -> Path:
    """Locate the bundled default config by searching a few sensible paths."""
    target = "configs/default.yaml"
    for candidate in _search_paths(target):
        if candidate.exists():
            return candidate
    # Fall through to a path that will fail validation with a clear error.
    return Path(target)


def _default_data_sources() -> Path:
    target = "data_sources"
    for candidate in _search_paths(target):
        if candidate.exists():
            return candidate
    return Path(target)


_USAGE = (
    "shop-guru <command> [options]\n\n"
    "commands:\n"
    "  build    Generate benchmark JSONs from extracted shop data\n"
    "  eval     Run an agent against generated benchmarks (forwards to\n"
    "           shop_guru.eval.run_all)\n\n"
    "Run `shop-guru <command> --help` for command-specific options."
)


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the requested subcommand."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0 if argv else 2

    command, rest = argv[0], argv[1:]
    if command == "build":
        return _build_main(rest)
    if command == "eval":
        # Imported lazily so `shop-guru build` doesn't pay the AgentLab/BrowserGym
        # import cost (and so `build` works in environments without those deps).
        from shop_guru.eval.run_all import main as run_all_main
        return run_all_main(rest, prog="shop-guru eval")

    print(f"shop-guru: unknown command {command!r}\n\n{_USAGE}", file=sys.stderr)
    return 2


def _build_main(argv: list[str]) -> int:
    """Parse args and invoke :func:`shop_guru.pipeline.build_all`."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path = args.config.resolve()
    if not config_path.exists():
        parser.error(f"config file not found: {config_path}")

    if args.no_per_shop and args.flat_out is None:
        parser.error("--no-per-shop requires --flat-out to be set")

    flat_out = args.flat_out.resolve() if args.flat_out else None

    issues = build_all(
        config=config_path,
        flat_out=flat_out,
        skip_per_shop=args.no_per_shop,
        shop_filter=args.shop,
        skip_auto=args.only_manual,
        skip_manual=args.only_auto,
        data_sources_dir=args.data_sources_dir.resolve() if args.data_sources_dir else None,
        validate=not args.no_validate,
    )
    if has_errors(issues):
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shop-guru build",
        description=(
            "Generate ShopGuru benchmark tasks for SandboxShop environments. "
            "Reads extracted shop-arena data and emits ShopGuru-format JSON "
            "benchmarks either per-shop (default) or as a flat mirror."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config(),
        help="Path to the shops YAML config (default: configs/default.yaml)",
    )
    parser.add_argument(
        "--flat-out",
        type=Path,
        default=None,
        help=(
            "Optional. Also emit a single flat mirror with all shops merged "
            "into one file per skill at this path."
        ),
    )
    parser.add_argument(
        "--no-per-shop",
        action="store_true",
        help="Skip per-shop writes (requires --flat-out)",
    )
    parser.add_argument(
        "--data-sources-dir",
        type=Path,
        default=_default_data_sources(),
        help="Directory with hand-authored source JSON (default: data_sources/)",
    )
    parser.add_argument(
        "--shop",
        default=None,
        help="Only build the shop with this slug (default: build all)",
    )
    parser.add_argument(
        "--only-auto",
        action="store_true",
        help="Skip hand-authored data sources",
    )
    parser.add_argument(
        "--only-manual",
        action="store_true",
        help="Skip automated generators",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help=(
            "Skip the post-generation consistency validator. By default the "
            "CLI runs `shop_guru.validate` over every emitted benchmark file "
            "and exits non-zero on any error-severity finding."
        ),
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
