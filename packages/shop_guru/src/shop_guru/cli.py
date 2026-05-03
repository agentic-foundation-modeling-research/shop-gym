"""Command-line entry points.

Installed as ``shop_guru-build`` via ``pyproject.toml``. Also runnable as
``python -m shop_guru``.

Default behavior writes one file per shop into
``<repo>/outputs/shop_guru/<slug>/benchmarks/`` — sibling to per-shop
eval study dirs at ``outputs/shop_guru/<slug>/``. Shop data is read
from ``<repo>/<shop.data_dir>/data/``, which is where ``shop_arena``
emits extracted storefronts (typically ``outputs/shops/<domain>``).

Use ``--flat-out PATH`` to also emit a single-file-per-skill mirror
(all shops merged) into ``PATH``, which is the drop-in layout SimGym
expects.

Examples::

    # Emit per-shop benchmarks for every shop in configs/featured_v1.yml:
    shop_guru-build

    # Only one shop:
    shop_guru-build --shop mock_shop

    # Also emit a flat mirror (per-shop + merged):
    shop_guru-build --flat-out outputs/benchmarks

    # Only the flat mirror, no per-shop writes:
    shop_guru-build --flat-out outputs/benchmarks --no-per-shop

    # Custom config:
    shop_guru-build --config /path/to/custom.yml
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
    """Locate the bundled featured_v1 config by searching a few sensible paths."""
    target = "configs/featured_v1.yml"
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


def main(argv: list[str] | None = None) -> int:
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
        prog="shop_guru-build",
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
        help="Path to the shops YAML config (default: configs/featured_v1.yml)",
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
