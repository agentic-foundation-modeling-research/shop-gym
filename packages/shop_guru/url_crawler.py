"""Command-line runner for the BrowserGym accessibility-tree URL crawler."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from shop_guru.bgym_task import AxCrawlerConfig, crawl_ax_links

PROG = "python -m shop_guru.url_crawler"
DEFAULT_OUTPUT_ROOT = Path("outputs") / "shop_guru" / "url_crawls"
_VIEWPORT_PARTS = 2


def main(argv: list[str] | None = None) -> int:
    """Run the accessibility-tree crawler from command-line arguments.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. ``0`` on success.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = AxCrawlerConfig(
        start_url=args.url,
        out_dir=args.out or _default_out_dir(args.url),
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        same_origin_only=not args.allow_external,
        wait_ms=args.wait_ms,
        timeout_ms=args.timeout_ms,
        delay_seconds=args.delay_seconds,
        viewport=args.viewport,
        store_axtree_json=args.axtree_json,
        store_axtree_text=args.axtree_text,
        headless=not args.show_browser,
        traversal=args.traversal,
        crawl_query_urls=args.crawl_query_urls,
    )

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = crawl_ax_links(config)
    print(f"Crawled pages: {len(result.pages)}")
    print(f"Failed URLs: {len(result.failed_urls)}")
    print(f"Discovered URLs: {len(result.discovered_urls)}")
    print(f"Output: {result.out_dir}")
    print(f"Manifest: {result.out_dir / 'manifest.json'}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Crawl only URLs exposed as links in BrowserGym's merged "
            "accessibility tree and optionally store those axtrees."
        ),
    )
    parser.add_argument("url", help="Absolute http(s) URL to crawl from.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=("Output directory. Defaults to outputs/shop_guru/url_crawls/<host>/<timestamp>/."),
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="Maximum BFS depth. The start URL is depth 0. Default: 3.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=500,
        help="Maximum number of pages to visit. Default: 500.",
    )
    parser.add_argument(
        "--traversal",
        choices=("bfs", "dfs"),
        default="bfs",
        help="Frontier traversal mode. Default: bfs.",
    )
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=1_000,
        help="Fixed wait after navigation before axtree extraction. Default: 1000.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Playwright operation timeout. Default: 30000.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Optional delay between page visits. Default: 0.",
    )
    parser.add_argument(
        "--viewport",
        type=_parse_viewport,
        default=(1280, 720),
        metavar="WIDTHxHEIGHT",
        help="Browser viewport. Default: 1280x720.",
    )
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Allow enqueueing links outside the start URL origin.",
    )
    parser.add_argument(
        "--crawl-query-urls",
        action="store_true",
        help="Allow URLs with query strings to enter the crawl frontier.",
    )
    parser.add_argument(
        "--axtree-json",
        action="store_true",
        help="Write raw *.axtree.json artifacts. By default no axtree files are saved.",
    )
    parser.add_argument(
        "--axtree-text",
        action="store_true",
        help="Write rendered *.axtree.txt artifacts. By default no axtree files are saved.",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Run Chromium headed instead of headless.",
    )
    return parser


def _parse_viewport(value: str) -> tuple[int, int]:
    """Parse ``WIDTHxHEIGHT`` into a viewport tuple."""
    parts = value.lower().split("x", maxsplit=1)
    if len(parts) != _VIEWPORT_PARTS:
        raise argparse.ArgumentTypeError("viewport must be WIDTHxHEIGHT")
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("viewport dimensions must be integers") from exc
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError("viewport dimensions must be positive")
    return width, height


def _default_out_dir(url: str) -> Path:
    """Return a timestamped default output directory for ``url``."""
    parsed = urlparse(url)
    host = parsed.netloc.replace(":", "_") or "unknown-host"
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_ROOT / host / run_id


if __name__ == "__main__":
    sys.exit(main())
