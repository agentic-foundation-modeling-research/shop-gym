"""Command-line runner for ShopGuru task exploration over crawled URLs."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import TypedDict

from shop_guru.explorer import Explorer

PROG = "python packages/shop_guru/explore.py"
REPO_ROOT = Path(__file__).parent.parent.parent.expanduser().resolve()
DEFAULT_EXPLORE_PER_DEPTH = (1, 0, 10)
DEFAULT_IGNORE_PATHS = ("/search", "/cart")


class CrawlUrl(TypedDict):
    """URL record emitted by the URL crawler."""

    final_url: str
    depth: int


def main(argv: list[str] | None = None) -> int:
    """Run task exploration from command-line arguments.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. ``0`` on success.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    url_file = args.url_file or args.crawl_dir / "urls.jsonl"
    rng = random.Random(args.seed)
    candidate_urls = load_crawl_urls(url_file)
    filtered_urls = filter_urls(candidate_urls, args.ignore_path)
    urls_by_depth = select_urls_by_depth(
        filtered_urls,
        explore_per_depth=args.explore_per_depth,
        must_explore=args.must_explore,
        rng=rng,
    )
    explore_urls_by_depth(
        urls_by_depth,
        exp_dir=args.exp_dir,
        website_url=args.website_url,
        website_nickname=args.website_nickname,
        cwd=args.cwd,
        timeout_seconds=args.timeout_seconds,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Sample crawled storefront URLs by graph depth and run the ShopGuru "
            "task explorer on each selected page."
        ),
    )
    parser.add_argument(
        "--crawl-dir",
        type=Path,
        required=True,
        help="Directory containing urls.jsonl.",
    )
    parser.add_argument(
        "--url-file",
        type=Path,
        default=None,
        help="Explicit crawler JSONL file. Defaults to <crawl-dir>/urls.jsonl.",
    )
    parser.add_argument(
        "--exp-dir",
        type=Path,
        required=True,
        help="Directory for prompts, progress logs, and task configs.",
    )
    parser.add_argument(
        "--website-url",
        required=True,
        help="Hosted storefront origin to explore.",
    )
    parser.add_argument(
        "--website-nickname",
        required=True,
        help="Stable nickname used inside task verifiers.",
    )
    parser.add_argument(
        "--explore-per-depth",
        type=parse_depth_counts,
        default=DEFAULT_EXPLORE_PER_DEPTH,
        metavar="N[,N...]",
        help="Comma-separated non-must-explore sample count per graph depth. Default: 1,0,10.",
    )
    parser.add_argument(
        "--must-explore",
        action="append",
        default=[],
        metavar="PATH",
        help="URL suffix to always explore when present. May be passed multiple times.",
    )
    parser.add_argument(
        "--ignore-path",
        action="append",
        default=list(DEFAULT_IGNORE_PATHS),
        metavar="PATH",
        help="URL suffix to exclude. Defaults include /search and /cart.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Optional random seed for reproducible URL sampling.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=REPO_ROOT,
        help=f"Working directory for the agent process. Default: {REPO_ROOT}.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=20 * 60,
        help="Per-page agent timeout in seconds. Default: 300.",
    )
    return parser


def parse_depth_counts(value: str) -> tuple[int, ...]:
    """Parse comma-separated per-depth sample counts."""
    try:
        counts = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("explore-per-depth values must be integers") from exc
    if not counts:
        raise argparse.ArgumentTypeError("explore-per-depth must contain at least one value")
    if any(count < 0 for count in counts):
        raise argparse.ArgumentTypeError("explore-per-depth values must be non-negative")
    return counts


def load_crawl_urls(url_file: Path) -> list[CrawlUrl]:
    """Load URL records from a crawler JSONL file."""
    urls: list[CrawlUrl] = []
    with url_file.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            urls.append(parse_crawl_url(json.loads(stripped), line_number=line_number))
    return urls


def parse_crawl_url(value: object, *, line_number: int) -> CrawlUrl:
    """Parse and validate one crawler URL record."""
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object on line {line_number}")

    final_url = value.get("final_url")
    depth = value.get("depth")
    if not isinstance(final_url, str):
        raise ValueError(f"Expected string final_url on line {line_number}")
    if isinstance(depth, bool) or not isinstance(depth, int):
        raise ValueError(f"Expected integer depth on line {line_number}")
    return {"final_url": final_url, "depth": depth}


def filter_urls(urls: list[CrawlUrl], ignore_paths: list[str]) -> list[CrawlUrl]:
    """Exclude URLs that are unlikely to produce meaningful tasks."""
    return [
        url for url in urls if not any(url["final_url"].endswith(path) for path in ignore_paths)
    ]


def select_urls_by_depth(
    urls: list[CrawlUrl],
    *,
    explore_per_depth: tuple[int, ...],
    must_explore: list[str],
    rng: random.Random,
) -> list[list[CrawlUrl]]:
    """Return sampled exploration URLs grouped by graph depth."""
    return [
        sample_urls(
            filter_urls_by_depth(urls, depth),
            num_samples=num_samples,
            must_explore=must_explore,
            rng=rng,
        )
        for depth, num_samples in enumerate(explore_per_depth)
    ]


def filter_urls_by_depth(urls: list[CrawlUrl], depth: int) -> list[CrawlUrl]:
    """Return URL records at one graph depth."""
    return [url for url in urls if url["depth"] == depth]


def sample_urls(
    urls: list[CrawlUrl],
    *,
    num_samples: int,
    must_explore: list[str],
    rng: random.Random,
) -> list[CrawlUrl]:
    """Sample URLs while preserving all records matching must-explore suffixes."""
    collected = 0
    shuffled_urls = urls.copy()
    rng.shuffle(shuffled_urls)

    explore_urls: list[CrawlUrl] = []
    for url in shuffled_urls:
        if must_explore_url(url, must_explore):
            explore_urls.append(url)
        elif collected < num_samples:
            explore_urls.append(url)
            collected += 1
    return explore_urls


def must_explore_url(url: CrawlUrl, must_explore: list[str]) -> bool:
    """Return whether a URL matches any required exploration suffix."""
    return any(url["final_url"].endswith(path) for path in must_explore)


def explore_urls_by_depth(
    urls_by_depth: list[list[CrawlUrl]],
    *,
    exp_dir: Path,
    website_url: str,
    website_nickname: str,
    cwd: Path,
    timeout_seconds: int,
) -> None:
    """Run the explorer for each selected URL grouped by crawl depth."""
    for depth, explore_urls in enumerate(urls_by_depth):
        print(f"Exploring {len(explore_urls)} URLs at depth {depth}.")
        for url in explore_urls:
            explore_url(
                url,
                depth=depth,
                exp_dir=exp_dir,
                website_url=website_url,
                website_nickname=website_nickname,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
            )


def explore_url(
    url: CrawlUrl,
    *,
    depth: int,
    exp_dir: Path,
    website_url: str,
    website_nickname: str,
    cwd: Path,
    timeout_seconds: int,
) -> None:
    """Build and run one explorer prompt for a URL."""
    start_url = url["final_url"]
    explorer = Explorer(
        exp_dir,
        website_url=website_url,
        start_url=start_url,
        website_nickname=website_nickname,
    )
    exploration_id = exploration_id_for_url(start_url, website_url=website_url, depth=depth)
    explorer.build_prompt(exploration_id)
    explorer.explore(exploration_id, cwd=cwd, timeout=timeout_seconds)


def exploration_id_for_url(url: str, *, website_url: str, depth: int) -> str:
    """Return a filesystem-friendly ID for one explored URL."""
    path = url.removeprefix(website_url).replace("/", "-").strip("-")
    if not path:
        path = "home"
    return f"{depth}-{path}"


if __name__ == "__main__":
    sys.exit(main())
