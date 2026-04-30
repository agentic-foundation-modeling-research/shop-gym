"""Command-line entrypoint for ShopProbe.

One subcommand, ``shop-probe eval``: takes a benchmark YAML, runs every
target end-to-end (deterministic probes + capture-judge + surface
metrics), writes one report per shop, then renders a comparative figure
pair under ``<out>/figures/``.

Resume is per-shop. A target with an existing
``<out>/reports/<label>__<name>.json`` whose embedded ``rubric_hash``
matches the current rubric is skipped — adding a new shop to the YAML
extends the existing report dir without reprocessing the others. Pass
``--force`` to re-run everything regardless.

The module is import-safe: it performs no I/O at import time.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import platform
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Final
from urllib.parse import urljoin

from anthropic import AnthropicError
from playwright.async_api import Page
from pydantic import ValidationError

from shop_probe import __version__
from shop_probe.agent.judge import run_capture_judge
from shop_probe.bench import BenchLoadError, load_bench
from shop_probe.capture import PageBundle, capture_bundle
from shop_probe.fidelity import BenchComparison, compute_bench_comparison
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
    EvidenceRef,
    ProbeReport,
    ProbeResult,
)
from shop_probe.report_writer import (
    render_group_comparison_table,
    render_per_shop_table,
)
from shop_probe.rubric import Rubric, RubricEntry, load_rubric
from shop_probe.surface import SurfaceMetrics
from shop_probe.surface.crawler import SurfaceCrawler
from shop_probe.targets import Bench, Target

EXIT_OK: Final[int] = 0
EXIT_USAGE: Final[int] = 2

_PROBE_DOTTED_PREFIX: Final[str] = "probes."
_MIN_PROBE_DOTS: Final[int] = 2

_PACKAGE_RUBRIC_DIR: Final[Path] = Path(__file__).resolve().parent / "rubric"
_RUBRIC_PATH: Final[Path] = _PACKAGE_RUBRIC_DIR / "v2.yaml"
"""The single rubric we ship. Pinned for reproducibility."""

_DISCOVERY_PROBE_ID: Final[str] = "_discover"
_BUNDLE_SUBDIR: Final[str] = "_bundle"

_DEFAULT_CAPTURE_JUDGE_MODEL: Final[str] = "claude-haiku-4-5"
"""Default Anthropic model for the capture-judge tier."""

_DEFAULT_OUT_ROOT: Final[Path] = Path("outputs/shop_probe")

_REPORTS_SUBDIR: Final[str] = "reports"
_EVIDENCE_SUBDIR: Final[str] = "evidence"
_FIGURES_SUBDIR: Final[str] = "figures"

_GROUP_COMPARISON_FILENAME: Final[str] = "group_comparison.md"
_PER_SHOP_TABLE_FILENAME: Final[str] = "per_shop_table.md"


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
    if args.command == "eval":
        return _cmd_eval(args)
    parser.print_help()
    return EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shop-probe",
        description="Run the shop-probe rubric over a benchmark of storefronts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    eval_parser = sub.add_parser(
        "eval",
        help="Run rubric end-to-end against every target in a benchmark YAML.",
    )
    eval_parser.add_argument(
        "--benchmark",
        required=True,
        type=Path,
        help="Path to a benchmark YAML.",
    )
    eval_parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT_ROOT,
        help=(
            "Run-root directory. Reports land under '<out>/reports/' and figures "
            f"under '<out>/figures/'. Defaults to '{_DEFAULT_OUT_ROOT}'."
        ),
    )
    eval_parser.add_argument(
        "--axes",
        default="A,B",
        help=(
            "Comma-separated axes to run. 'A' = capability coverage, "
            "'A,B' = coverage + crawl-derived surface metrics. Default: 'A,B'."
        ),
    )
    eval_parser.add_argument(
        "--include-auth",
        action="store_true",
        default=False,
        help="Include rubric entries flagged authenticated/transactional.",
    )
    eval_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Recompute every target's report instead of using the per-shop cache.",
    )
    eval_parser.add_argument(
        "--capture-judge-model",
        default=_DEFAULT_CAPTURE_JUDGE_MODEL,
        help=(
            "Anthropic model id for the capture-judge tier "
            f"(default: {_DEFAULT_CAPTURE_JUDGE_MODEL})."
        ),
    )
    return parser


# --------------------------------------------------------------------------- #
# Per-shop probe execution.
# --------------------------------------------------------------------------- #


def _parse_axes(raw: str) -> tuple[str, ...]:
    """Parse ``--axes`` value into a sorted, deduplicated tuple."""
    return tuple(sorted({a.strip() for a in raw.split(",") if a.strip()}))


def _resolve_probe(dotted: str) -> ProbeFn:
    """Resolve a rubric ``probe`` reference to a Python callable."""
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
    """Walk the homepage to find sample collection + product URLs."""
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


async def _run_capture_judge_entry(
    entry: RubricEntry,
    *,
    bundle: PageBundle,
    bundle_root: Path,
    model: str,
) -> ProbeOutcome:
    """Dispatch one ``level: capture_judge`` rubric entry against the bundle."""
    assert entry.capture_judge is not None, (
        f"rubric entry {entry.id!r}: capture_judge level requires inline block"
    )
    requested = entry.capture_judge.pages
    captures = tuple(c for p in requested if (c := bundle.get(p)) is not None)
    applicable = tuple(c for c in captures if c.applicable)
    evidence: list[EvidenceRef] = []
    for capture in applicable:
        if capture.screenshot_rel is not None:
            evidence.append(
                EvidenceRef(
                    kind="screenshot",
                    path=f"{_BUNDLE_SUBDIR}/{capture.screenshot_rel}",
                )
            )
        if capture.accessibility_rel is not None:
            evidence.append(
                EvidenceRef(
                    kind="a11y_snapshot",
                    path=f"{_BUNDLE_SUBDIR}/{capture.accessibility_rel}",
                )
            )

    if not applicable:
        return ProbeOutcome(
            passed=None,
            evidence=tuple(evidence),
            notes="bundle pages unavailable",
        )

    try:
        verdict = await run_capture_judge(
            captures,
            bundle_root,
            entry.capture_judge.judge_prompt,
            model=model,
        )
    except AnthropicError as exc:
        # ``run_capture_judge`` already retries 429 / 5xx / transport errors;
        # if we still bubble out, the proxy quota is genuinely exhausted.
        return ProbeOutcome(
            passed=None,
            evidence=tuple(evidence),
            notes=f"judge unavailable after retries: {type(exc).__name__}",
            extra={"judge_model": model},
        )
    return ProbeOutcome(
        passed=verdict.passed,
        evidence=tuple(evidence),
        notes=verdict.reasoning,
        extra={
            "judge_cost_usd": verdict.cost_usd,
            "judge_model": verdict.model_id,
        },
    )


async def _run(
    *,
    target: Target,
    rubric: Rubric,
    evidence_root: Path,
    run_axis_a: bool,
    run_axis_b: bool,
    include_auth: bool,
    capture_judge_model: str,
) -> ProbeReport:
    """Run the requested axes and assemble the closed :class:`ProbeReport`."""
    started = datetime.now(UTC)
    results: list[ProbeResult] = []
    categories: tuple[CategoryScore, ...] = ()
    c_core = c_modern = c_advanced = c_weighted = 0.0
    chromium_version = "unknown"
    selected_entries = _select_rubric_entries(rubric, include_auth=include_auth)

    if run_axis_a:
        async with ProbeRunner(evidence_root=evidence_root) as runner:
            chromium_version = runner.chromium_version
            sample_collection_url, sample_product_url = await _discover_sample_urls(
                runner, target.base_url
            )
            bundle: PageBundle | None = None
            bundle_root = evidence_root / _BUNDLE_SUBDIR
            if any(e.level == "capture_judge" for e in selected_entries):
                bundle = await capture_bundle(
                    runner,
                    base_url=target.base_url,
                    sample_collection_url=sample_collection_url,
                    sample_product_url=sample_product_url,
                    bundle_root=bundle_root,
                )
            for entry in selected_entries:
                if entry.level == "capture_judge":
                    assert bundle is not None, (
                        "capture_judge entry present but bundle was never captured"
                    )
                    outcome = await _run_capture_judge_entry(
                        entry,
                        bundle=bundle,
                        bundle_root=bundle_root,
                        model=capture_judge_model,
                    )
                else:
                    assert entry.probe is not None, (
                        f"rubric entry {entry.id!r} has level={entry.level!r} "
                        f"but no probe; schema validator should have caught this"
                    )
                    probe = _resolve_probe(entry.probe)
                    outcome = await runner.run(
                        probe,
                        base_url=target.base_url,
                        probe_id=entry.id,
                        sample_product_url=sample_product_url,
                        sample_collection_url=sample_collection_url,
                    )
                results.append(_build_probe_result(entry.id, outcome))
        categories, c_core, c_modern, c_advanced, c_weighted = _aggregate_coverage(
            selected_entries, results
        )

    surface: SurfaceMetrics | None = None
    if run_axis_b:
        async with SurfaceCrawler() as crawler:
            surface = await crawler.crawl(target.base_url)

    runtime = BrowserMeta(
        python_version=platform.python_version(),
        playwright_version=_safe_pkg_version("playwright"),
        chromium_version=chromium_version,
        user_agent=PINNED_USER_AGENT,
        viewport=(VIEWPORT_WIDTH, VIEWPORT_HEIGHT),
        headless=True,
    )
    total_judge_cost_usd = _aggregate_judge_cost(results)
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
        surface=surface,
        total_judge_cost_usd=total_judge_cost_usd,
    )


def _select_rubric_entries(rubric: Rubric, *, include_auth: bool) -> tuple[RubricEntry, ...]:
    """Filter rubric entries by the ``--include-auth`` gate."""
    if include_auth:
        return rubric.entries
    return tuple(e for e in rubric.entries if not (e.authenticated or e.transactional))


def _build_probe_result(probe_id: str, outcome: ProbeOutcome) -> ProbeResult:
    """Project a :class:`ProbeOutcome` into the closed :class:`ProbeResult`."""
    return ProbeResult(
        id=probe_id,
        passed=outcome.passed,
        evidence=outcome.evidence,
        notes=outcome.notes,
        duration_ms=outcome.duration_ms,
        judge_cost_usd=_extra_float(outcome.extra, "judge_cost_usd"),
        judge_model=_extra_str(outcome.extra, "judge_model"),
    )


def _extra_float(extra: object, key: str) -> float | None:
    """Return ``extra[key]`` coerced to ``float`` when present, else ``None``."""
    if not isinstance(extra, dict):
        return None
    value = extra.get(key)
    if value is None:
        return None
    if isinstance(value, bool):  # bool is a subclass of int; reject explicitly.
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _extra_str(extra: object, key: str) -> str | None:
    """Return ``extra[key]`` when it is a non-empty string, else ``None``."""
    if not isinstance(extra, dict):
        return None
    value = extra.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _aggregate_judge_cost(results: list[ProbeResult]) -> float | None:
    """Sum per-probe ``judge_cost_usd`` across the report.

    Returns ``None`` when no probe issued a capture-judge call (preserves
    the distinction between "no judge calls" and "all judge calls free").
    """
    judge_costs = [r.judge_cost_usd for r in results if r.judge_cost_usd is not None]
    return sum(judge_costs) if judge_costs else None


def _aggregate_coverage(
    entries: tuple[RubricEntry, ...], results: list[ProbeResult]
) -> tuple[tuple[CategoryScore, ...], float, float, float, float]:
    """Compute per-category + per-level + weighted coverage."""
    by_id = {r.id: r for r in results}
    by_category: dict[str, list[float]] = {}
    by_level: dict[str, list[float]] = {
        "core": [0.0, 0.0],
        "modern": [0.0, 0.0],
        "advanced": [0.0, 0.0],
    }
    total_passed = 0.0
    total_weight = 0.0
    for entry in entries:
        result = by_id[entry.id]
        if result.passed is None:
            continue
        weight = float(entry.weight)
        passed = weight if result.passed else 0.0
        cat = by_category.setdefault(entry.category, [0.0, 0.0])
        cat[0] += passed
        cat[1] += weight
        # ``capture_judge`` entries roll up into ``coverage_advanced``
        # alongside deterministic-advanced probes.
        level_bucket = "advanced" if entry.level == "capture_judge" else entry.level
        lv = by_level[level_bucket]
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
    """Weighted coverage formula. ``weight_total == 0`` → 0.0."""
    if weight_total <= 0.0:
        return 0.0
    return weight_passed / weight_total


def _safe_pkg_version(name: str) -> str:
    """Return the installed version of ``name``, or ``'unknown'`` if absent."""
    try:
        return _pkg_version(name)
    except PackageNotFoundError:
        return "unknown"


# --------------------------------------------------------------------------- #
# ``shop-probe eval`` — single end-to-end driver.
# --------------------------------------------------------------------------- #


def _target_stem(target: Target) -> str:
    """Filename stem for a target: ``<label>__<name>``."""
    return f"{target.label}__{target.name}"


def _load_cached_report(report_path: Path, *, expected_hash: str) -> ProbeReport | None:
    """Return a cached report iff its rubric hash matches ``expected_hash``.

    A cached report whose rubric has changed is treated as stale — we
    return ``None`` so the caller recomputes. A malformed JSON file is
    also treated as a miss; on recompute we'll overwrite it.
    """
    if not report_path.is_file():
        return None
    try:
        cached = ProbeReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError):
        return None
    if cached.rubric_hash != expected_hash:
        return None
    return cached


def _cmd_eval(args: argparse.Namespace) -> int:
    """Handler for ``shop-probe eval``."""
    benchmark_path: Path = args.benchmark
    out_root: Path = args.out
    force: bool = args.force

    axes = _parse_axes(args.axes)
    if axes not in {("A",), ("A", "B")}:
        print(
            f"shop-probe: --axes={args.axes!r} not supported; "
            "use 'A' or 'A,B'.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        bench = load_bench(benchmark_path)
    except FileNotFoundError as err:
        print(f"shop-probe: benchmark not found: {err}", file=sys.stderr)
        return EXIT_USAGE
    except BenchLoadError as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    rubric = load_rubric(_RUBRIC_PATH)

    targets: tuple[Target, ...] = (*bench.sandboxes, *bench.reals)
    print(
        f"shop-probe eval: benchmark={benchmark_path} targets={len(targets)} "
        f"rubric={rubric.version} axes={','.join(axes)}"
    )

    reports_dir = out_root / _REPORTS_SUBDIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    sandbox_reports: list[ProbeReport] = []
    real_reports: list[ProbeReport] = []

    for target in targets:
        stem = _target_stem(target)
        report_path = reports_dir / f"{stem}.json"
        report: ProbeReport | None = None
        if not force:
            report = _load_cached_report(report_path, expected_hash=rubric.content_hash)
            if report is not None:
                print(f"shop-probe eval: cache hit {stem}")
        if report is None:
            evidence_root = out_root / _EVIDENCE_SUBDIR / stem
            try:
                report = asyncio.run(
                    _run(
                        target=target,
                        rubric=rubric,
                        evidence_root=evidence_root,
                        run_axis_a="A" in axes,
                        run_axis_b="B" in axes,
                        include_auth=args.include_auth,
                        capture_judge_model=args.capture_judge_model,
                    )
                )
            except ValidationError as err:
                print(
                    f"shop-probe eval: {target.name!r} report failed validation: {err}",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            print(
                f"shop-probe eval: wrote {report_path} "
                f"(coverage_weighted={report.coverage_weighted:.3f})"
            )
        if target.label == "sandbox":
            sandbox_reports.append(report)
        else:
            real_reports.append(report)

    return _render_figures(out_root, bench, sandbox_reports, real_reports)


def _render_figures(
    out_root: Path,
    bench: Bench,
    sandbox_reports: list[ProbeReport],
    real_reports: list[ProbeReport],
) -> int:
    """Render the two cohort figures from the per-shop reports."""
    if not sandbox_reports or not real_reports:
        print(
            "shop-probe eval: figures skipped — bench has no sandboxes or no reals "
            f"(sandboxes={len(bench.sandboxes)}, reals={len(bench.reals)}).",
            file=sys.stderr,
        )
        return EXIT_OK

    try:
        comparison = compute_bench_comparison(sandbox_reports, real_reports)
    except ValueError as err:
        print(f"shop-probe eval: {err}", file=sys.stderr)
        return EXIT_USAGE

    figures_dir = out_root / _FIGURES_SUBDIR
    figures_dir.mkdir(parents=True, exist_ok=True)
    group_path = figures_dir / _GROUP_COMPARISON_FILENAME
    per_shop_path = figures_dir / _PER_SHOP_TABLE_FILENAME
    group_path.write_text(render_group_comparison_table(comparison), encoding="utf-8")
    per_shop_path.write_text(
        render_per_shop_table(sandbox_reports, real_reports, comparison),
        encoding="utf-8",
    )
    print(f"shop-probe eval: wrote {group_path}, {per_shop_path}")
    return EXIT_OK


def _build_bench_comparison(
    *,
    sandbox_reports: tuple[ProbeReport, ...],
    real_reports: tuple[ProbeReport, ...],
) -> BenchComparison:
    """Aggregate sandbox + real reports into a :class:`BenchComparison`.

    Convenience wrapper retained for tests; production callers go through
    :func:`compute_bench_comparison` directly.
    """
    return compute_bench_comparison(sandbox_reports, real_reports)


def _load_report(reports_dir: Path, target: Target) -> ProbeReport:
    """Load and validate one :class:`ProbeReport` from the reports directory."""
    path = reports_dir / f"{_target_stem(target)}.json"
    if not path.is_file():
        msg = f"missing report for target {target.name!r}: {path}"
        raise FileNotFoundError(msg)
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    if report.target.name != target.name or report.target.label != target.label:
        msg = (
            f"report at {path} has target=({report.target.label}, "
            f"{report.target.name}), expected ({target.label}, {target.name})"
        )
        raise ValueError(msg)
    return report


if __name__ == "__main__":
    raise SystemExit(main())
