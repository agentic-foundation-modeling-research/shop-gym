"""Command-line entrypoint for ShopProbe (T1.8 — spec §4, §5.3, §5.6, §5.8).

The v1 ``shop-probe`` CLI exposes the ``run`` subcommand:

.. code-block:: bash

    shop-probe run <base_url> \\
        --label sandbox/run123 \\
        --rubric v1 \\
        --axes A \\
        --kind sandbox --pair-id pair_hardware \\
        --out report.json

For ``--axes A`` the command:

1. Loads the requested rubric (``v1`` resolves to the YAML packaged inside
   ``shop_probe.rubric``; an arbitrary path is also accepted).
2. Discovers a sample collection URL and a sample product URL from the
   homepage so the ``collection.*`` / ``product.*`` / ``cart.line_item.*``
   probes have something to navigate to.
3. Drives every rubric leaf through :class:`ProbeRunner` in dotted-name
   order, capturing structured evidence under ``--evidence-dir``.
4. Aggregates ``ProbeResult`` rows into per-category coverage plus the
   four headline ``coverage_core/modern/advanced/weighted`` numbers
   (spec §5.3).
5. Embeds the rubric version + content hash, runner version, and the
   pinned Playwright/Chromium runtime metadata into a closed
   :class:`ProbeReport` (spec §5.6 + §5.8) and writes it to ``--out``.

Axes B and C are wired in later milestones (spec §7 M2 / M4); requesting
them today returns a usage error.

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import platform
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Final
from urllib.parse import urljoin

from playwright.async_api import Page
from pydantic import ValidationError

from shop_probe import __version__
from shop_probe.probes._runner import (
    PINNED_USER_AGENT,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    ProbeContext,
    ProbeFn,
    ProbeOutcome,
    ProbeRunner,
)
from shop_probe.report import (
    BrowserMeta,
    CategoryScore,
    ProbeReport,
    ProbeResult,
)
from shop_probe.rubric import Rubric, load_rubric
from shop_probe.targets import Target

EXIT_OK: Final[int] = 0
"""Successful run."""

EXIT_USAGE: Final[int] = 2
"""Usage error (matches argparse + ``shop_explore.cli`` convention)."""

_PROBE_DOTTED_PREFIX: Final[str] = "probes."
"""Prefix every rubric ``probe`` reference uses (spec §5.3 example)."""

_MIN_PROBE_DOTS: Final[int] = 2
"""Minimum dots in a valid ``probes.<module>.<fn>`` reference."""

_PACKAGE_RUBRIC_DIR: Final[Path] = Path(__file__).resolve().parent / "rubric"
"""Directory holding rubric YAML shipped with the package."""

_DISCOVERY_PROBE_ID: Final[str] = "_discover"
"""Internal probe-id used by sample-URL discovery; never lands in the report."""


def main(argv: list[str] | None = None) -> int:
    """Run the ShopProbe CLI.

    Args:
        argv: Optional argument vector. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. ``0`` on success, ``2`` on usage / validation
        errors.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    parser.print_help()
    return EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    description = (__doc__ or "").split("\n", 1)[0]
    parser = argparse.ArgumentParser(prog="shop-probe", description=description)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser(
        "run",
        help="Run the probe rubric against a storefront and emit a ProbeReport.",
    )
    run.add_argument("base_url", help="Storefront base URL.")
    run.add_argument(
        "--label",
        required=True,
        help="Human-readable target label (e.g. 'sandbox/hardware_run123').",
    )
    run.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Path to write the ProbeReport JSON document.",
    )
    run.add_argument(
        "--rubric",
        default="v1",
        help="Rubric name (resolved against packaged rubrics) or YAML path.",
    )
    run.add_argument(
        "--axes",
        default="A",
        help="Comma-separated axes to run. Today only 'A' is implemented.",
    )
    run.add_argument(
        "--kind",
        choices=("sandbox", "source", "real_unpaired"),
        default="sandbox",
        help="Target kind (spec §5.2).",
    )
    run.add_argument(
        "--pair-id",
        default=None,
        help="Pair identifier (required when --kind is sandbox or source).",
    )
    run.add_argument(
        "--notes",
        default=None,
        help="Optional free-form operator notes recorded on the Target.",
    )
    run.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="Directory for probe evidence. Defaults to '<out_dir>/evidence'.",
    )
    run.add_argument(
        "--rerun-index",
        type=int,
        default=1,
        help="1-indexed run number within the N=3 rerun group (spec §5.8).",
    )
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    """Handler for ``shop-probe run``."""
    axes = _parse_axes(args.axes)
    if axes != ("A",):
        print(
            f"shop-probe: --axes={args.axes!r} not supported yet "
            "(only 'A' is wired in M1; 'B' lands in M2, 'C' in M4).",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        rubric_path = _resolve_rubric_arg(args.rubric)
    except FileNotFoundError as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    rubric = load_rubric(rubric_path)

    try:
        target = Target(
            label=args.label,
            base_url=args.base_url,
            kind=args.kind,
            pair_id=args.pair_id,
            notes=args.notes,
        )
    except ValidationError as err:
        print(f"shop-probe: invalid target: {err}", file=sys.stderr)
        return EXIT_USAGE

    out_path: Path = args.out
    evidence_root: Path = (
        args.evidence_dir if args.evidence_dir is not None else (out_path.parent / "evidence")
    )

    report = asyncio.run(
        _run_axis_a(
            target=target,
            rubric=rubric,
            evidence_root=evidence_root,
            rerun_index=args.rerun_index,
        )
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"shop-probe: wrote {out_path} "
        f"(coverage_core={report.coverage_core:.3f}, "
        f"coverage_weighted={report.coverage_weighted:.3f})"
    )
    return EXIT_OK


def _parse_axes(raw: str) -> tuple[str, ...]:
    """Parse ``--axes`` value into a sorted, deduplicated tuple."""
    return tuple(sorted({a.strip() for a in raw.split(",") if a.strip()}))


def _resolve_rubric_arg(name_or_path: str) -> Path:
    """Resolve ``--rubric`` to a YAML file path.

    A bare name like ``v1`` looks up ``shop_probe/rubric/v1.yaml``; any
    other value is treated as a filesystem path.
    """
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate
    packaged = _PACKAGE_RUBRIC_DIR / f"{name_or_path}.yaml"
    if packaged.is_file():
        return packaged
    msg = (
        f"could not resolve --rubric={name_or_path!r}: "
        f"no such file and no packaged rubric named {name_or_path!r}"
    )
    raise FileNotFoundError(msg)


def _resolve_probe(dotted: str) -> ProbeFn:
    """Resolve a rubric ``probe`` reference to a Python callable.

    Args:
        dotted: Reference of the form ``probes.<module>.<fn>`` (the
            shape enforced by ``test_v1_probe_callables_use_dotted_module_form``).

    Returns:
        The callable matching :data:`shop_probe.probes._runner.ProbeFn`.

    Raises:
        ValueError: ``dotted`` does not start with ``probes.`` or is too
            short to address ``module.fn``.
        ModuleNotFoundError / AttributeError: The module/function does
            not exist (propagated unchanged).
    """
    if not dotted.startswith(_PROBE_DOTTED_PREFIX) or dotted.count(".") < _MIN_PROBE_DOTS:
        msg = f"invalid probe reference {dotted!r}: expected '{_PROBE_DOTTED_PREFIX}<module>.<fn>'"
        raise ValueError(msg)
    parts = dotted.split(".")
    module_path = "shop_probe." + ".".join(parts[:-1])
    fn_name = parts[-1]
    module = importlib.import_module(module_path)
    return getattr(module, fn_name)  # type: ignore[no-any-return]


async def _discover_sample_urls(
    runner: ProbeRunner, base_url: str
) -> tuple[str | None, str | None]:
    """Walk the homepage to find sample collection + product URLs.

    Returns ``(sample_collection_url, sample_product_url)``; either
    component may be ``None`` if discovery fails — those probes then
    return ``passed=None`` ("not_applicable") at runtime.
    """
    discovered: dict[str, str | None] = {"collection": None, "product": None}

    async def _discover(page: Page, ctx: ProbeContext) -> ProbeOutcome:
        await page.goto(ctx.base_url, wait_until="domcontentloaded")
        coll_link = page.locator('a[href*="/collections/"]').first
        if await coll_link.count() > 0:
            href = await coll_link.get_attribute("href")
            if href:
                discovered["collection"] = urljoin(ctx.base_url, href)
        if discovered["collection"] is not None:
            await page.goto(discovered["collection"], wait_until="domcontentloaded")
            prod_link = page.locator('a[href*="/products/"]').first
            if await prod_link.count() > 0:
                href = await prod_link.get_attribute("href")
                if href:
                    discovered["product"] = urljoin(ctx.base_url, href)
        return ProbeOutcome(passed=True)

    await runner.run(_discover, base_url=base_url, probe_id=_DISCOVERY_PROBE_ID)
    return discovered["collection"], discovered["product"]


async def _run_axis_a(
    *,
    target: Target,
    rubric: Rubric,
    evidence_root: Path,
    rerun_index: int,
) -> ProbeReport:
    """Run every rubric leaf and assemble the closed :class:`ProbeReport`."""
    started = datetime.now(UTC)
    results: list[ProbeResult] = []
    chromium_version: str
    async with ProbeRunner(evidence_root=evidence_root) as runner:
        chromium_version = runner.chromium_version
        sample_collection_url, sample_product_url = await _discover_sample_urls(
            runner, target.base_url
        )
        for entry in rubric.entries:
            probe = _resolve_probe(entry.probe)
            outcome = await runner.run(
                probe,
                base_url=target.base_url,
                probe_id=entry.id,
                sample_product_url=sample_product_url,
                sample_collection_url=sample_collection_url,
            )
            results.append(
                ProbeResult(
                    id=entry.id,
                    passed=outcome.passed,
                    evidence=outcome.evidence,
                    notes=outcome.notes,
                    duration_ms=outcome.duration_ms,
                )
            )

    categories, c_core, c_modern, c_advanced, c_weighted = _aggregate_coverage(rubric, results)
    runtime = BrowserMeta(
        python_version=platform.python_version(),
        playwright_version=_safe_pkg_version("playwright"),
        chromium_version=chromium_version,
        user_agent=PINNED_USER_AGENT,
        viewport=(VIEWPORT_WIDTH, VIEWPORT_HEIGHT),
        headless=True,
    )
    return ProbeReport(
        target=target,
        rubric_version=rubric.version,
        rubric_hash=rubric.content_hash,
        runner_version=__version__,
        runtime=runtime,
        timestamp=started,
        probe_results=tuple(results),
        categories=categories,
        coverage_core=c_core,
        coverage_modern=c_modern,
        coverage_advanced=c_advanced,
        coverage_weighted=c_weighted,
        rerun_index=rerun_index,
    )


def _aggregate_coverage(
    rubric: Rubric, results: list[ProbeResult]
) -> tuple[tuple[CategoryScore, ...], float, float, float, float]:
    """Compute per-category + per-level + weighted coverage (spec §5.3).

    ``passed=None`` rows are treated as "not_applicable" and excluded
    from both numerator and denominator.
    """
    by_id = {r.id: r for r in results}
    by_category: dict[str, list[float]] = {}
    by_level: dict[str, list[float]] = {
        "core": [0.0, 0.0],
        "modern": [0.0, 0.0],
        "advanced": [0.0, 0.0],
    }
    total_passed = 0.0
    total_weight = 0.0
    for entry in rubric.entries:
        result = by_id[entry.id]
        if result.passed is None:
            continue
        weight = float(entry.weight)
        passed = weight if result.passed else 0.0
        cat = by_category.setdefault(entry.category, [0.0, 0.0])
        cat[0] += passed
        cat[1] += weight
        lv = by_level[entry.level]
        lv[0] += passed
        lv[1] += weight
        total_passed += passed
        total_weight += weight

    categories = tuple(
        CategoryScore(
            category=cat,
            weight_passed=p,
            weight_total=t,
            coverage=_coverage(p, t),
        )
        for cat, (p, t) in sorted(by_category.items())
    )
    return (
        categories,
        _coverage(*by_level["core"]),
        _coverage(*by_level["modern"]),
        _coverage(*by_level["advanced"]),
        _coverage(total_passed, total_weight),
    )


def _coverage(weight_passed: float, weight_total: float) -> float:
    """Per-spec §5.3 coverage formula. ``weight_total == 0`` → 0.0."""
    if weight_total <= 0.0:
        return 0.0
    return weight_passed / weight_total


def _safe_pkg_version(name: str) -> str:
    """Return the installed version of ``name``, or ``'unknown'`` if absent."""
    try:
        return _pkg_version(name)
    except PackageNotFoundError:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
