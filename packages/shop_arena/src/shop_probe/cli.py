"""Command-line entrypoint for ShopProbe.

T1.8 + T6.5 + T7.4 — spec §4, §5.3, §5.6, §5.8, §5.9, §7 M6+M7.

Every subcommand takes a single ``--out`` argument pointing at a *run
root directory* (default ``outputs/shop_probe``). The run root has a
fixed subdirectory layout:

* ``<out>/reports/``  — one :class:`ProbeReport` JSON per (target, rerun).
  Raw reruns are named ``<safe(label)>__rerun<N>.json``;
  :func:`aggregate-reruns` writes the consolidated form as
  ``<safe(label)>.json`` (no rerun suffix). ``/`` in labels is rewritten
  to ``__`` for filename safety.
* ``<out>/evidence/`` — per-run evidence subdirectory
  ``<safe(label)>__rerun<N>/`` populated by :class:`ProbeRunner`.
* ``<out>/figures/``  — :func:`shop-probe report` artifacts.

The v1 ``shop-probe`` CLI exposes three subcommands:

.. code-block:: bash

    shop-probe run <base_url> \\
        --label sandbox/run123 \\
        --rubric v1 \\
        --axes A \\
        --kind sandbox --pair-id pair_1 \\
        --rerun-index 1
        # writes <out>/reports/sandbox__run123__rerun1.json
        # writes <out>/evidence/sandbox__run123__rerun1/...

    shop-probe aggregate-reruns \\
        --runs <out>/reports/sandbox__run123__rerun{1,2,3}.json
        # writes <out>/reports/sandbox__run123.json (consolidated)

    shop-probe report --cohort cohort.yaml
        # reads <out>/reports/, prefers the consolidated <label>.json
        # per target, falling back to the max-N raw rerun
        # writes <out>/figures/{fidelity_table.md,radar.svg,...}

For ``--axes A`` the ``run`` command:

1. Loads the requested rubric (``v1`` resolves to the YAML packaged inside
   ``shop_probe.rubric``; an arbitrary path is also accepted).
2. Discovers a sample collection URL and a sample product URL from the
   homepage so the ``collection.*`` / ``product.*`` / ``cart.line_item.*``
   probes have something to navigate to.
3. Drives every rubric leaf through :class:`ProbeRunner` in dotted-name
   order, capturing structured evidence under
   ``<out>/evidence/<safe(label)>__rerun<N>/``.
4. Aggregates ``ProbeResult`` rows into per-category coverage plus the
   four headline ``coverage_core/modern/advanced/weighted`` numbers
   (spec §5.3).
5. Embeds the rubric version + content hash, runner version, and the
   pinned Playwright/Chromium runtime metadata into a closed
   :class:`ProbeReport` (spec §5.6 + §5.8) and writes it under
   ``<out>/reports/``.

``--include-auth`` (T7.4 — spec §5.9 / M7) toggles the v1.1 auth + checkout
slice. By default rubric entries flagged ``authenticated=true`` or
``transactional=true`` are skipped before any probe runs; with the flag they
are included. v1 has no such entries, so the gate is a no-op for v1 rubrics.
When ``--axes`` includes ``B`` the command additionally drives a
:class:`SurfaceCrawler` against the same target and embeds the resulting
:class:`SurfaceMetrics` in ``report.surface``. Axis C is wired in M4;
requesting it today returns a usage error.

``shop-probe report`` (T6.5 — spec §7 M6) wires the four paper figures:

1. Loads ``--cohort`` and reads one :class:`ProbeReport` per
   :class:`Target` from ``<out>/reports/``. Prefers the consolidated
   ``<safe(label)>.json`` written by :func:`aggregate-reruns`; falls
   back to the max-N raw ``<safe(label)>__rerun<N>.json`` if no
   consolidated report is present.
2. Aggregates per-pair fidelity over the (sandbox, source) pairs and
   the 6-real-shop reference population (sources + ``real_unpaired``)
   into a closed :class:`CohortFidelity` (spec §5.7).
3. Renders four artifacts under ``<out>/figures/``:

   * ``fidelity_table.md``  — per-pair fidelity table (T6.1).
   * ``radar.svg``           — per-category coverage radar (T6.2).
   * ``surface.svg``         — per-metric surface bar chart (T6.3).
   * ``turing.svg``          — pairwise-judge Turing chart (T6.4),
     emitted only when axis-C judge calls are present (sandbox
     reports carry experimental calls; ``real_unpaired`` reports
     carry control calls).

All four outputs render from versioned reports without manual editing
(spec §7 M6 gate).

When ``--baselines-dir`` is supplied (T7.5 — spec §5.9 / M7) the
command additionally emits ``supplement_table.md``: a prior-work
environment table (Mock Shop, WebShop, WebArena-Shopping) rendered
alongside the primary outputs. The per-pair claims are not altered —
baseline reports never enter the cohort fidelity computation.

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

from playwright.async_api import Page
from pydantic import ValidationError

from shop_probe import __version__
from shop_probe.cohort import load_cohort
from shop_probe.fidelity import (
    CohortFidelity,
    PairFidelity,
    compute_cohort_fidelity,
    compute_pair_fidelity,
)
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
    JudgeCall,
    ProbeReport,
    ProbeResult,
)
from shop_probe.report_writer import (
    PairTuringData,
    render_pair_fidelity_table,
    render_prior_work_supplement_table,
    render_radar_chart_svg,
    render_surface_bar_chart_svg,
    render_turing_chart_svg,
)
from shop_probe.rubric import Rubric, RubricEntry, load_rubric
from shop_probe.stability import (
    FLAKE_RATE_GATE,
    RerunGroupError,
    consolidate_rerun_group,
    exceeds_flake_gate,
)
from shop_probe.surface import SurfaceMetrics
from shop_probe.surface.crawler import SurfaceCrawler
from shop_probe.targets import Cohort, Target

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

_LABEL_PATH_SEP: Final[str] = "__"
"""Filename-safe replacement for ``/`` in :attr:`Target.label`."""

_RERUN_SUFFIX_PREFIX: Final[str] = "__rerun"
"""Suffix prefix for raw rerun JSON files: ``<safe(label)>__rerun<N>.json``."""

_DEFAULT_OUT_ROOT: Final[Path] = Path("outputs/shop_probe")
"""Default ``--out`` run-root directory."""

_REPORTS_SUBDIR: Final[str] = "reports"
_EVIDENCE_SUBDIR: Final[str] = "evidence"
_FIGURES_SUBDIR: Final[str] = "figures"
"""Fixed subdirectory layout under the run-root ``--out`` directory."""

_FIDELITY_TABLE_FILENAME: Final[str] = "fidelity_table.md"
_RADAR_CHART_FILENAME: Final[str] = "radar.svg"
_SURFACE_CHART_FILENAME: Final[str] = "surface.svg"
_TURING_CHART_FILENAME: Final[str] = "turing.svg"
_SUPPLEMENT_TABLE_FILENAME: Final[str] = "supplement_table.md"
"""Filename for the T7.5 prior-work environment supplement table."""


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
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "aggregate-reruns":
        return _cmd_aggregate_reruns(args)
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
        help="Human-readable target label (e.g. 'sandbox/1_run123').",
    )
    run.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT_ROOT,
        help=(
            "Run-root directory. The ProbeReport JSON is written under "
            "'<out>/reports/<safe(label)>__rerun<N>.json' and probe evidence "
            "under '<out>/evidence/<safe(label)>__rerun<N>/'. "
            f"Defaults to '{_DEFAULT_OUT_ROOT}'."
        ),
    )
    run.add_argument(
        "--rubric",
        default="v1",
        help="Rubric name (resolved against packaged rubrics) or YAML path.",
    )
    run.add_argument(
        "--axes",
        default="A",
        help="Comma-separated axes to run. Supported: 'A' (M1), 'A,B' (M2).",
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
        "--rerun-index",
        type=int,
        default=1,
        help="1-indexed run number within the N=3 rerun group (spec §5.8).",
    )
    run.add_argument(
        "--include-auth",
        action="store_true",
        default=False,
        help=(
            "Include rubric entries flagged authenticated=true or transactional=true "
            "(v1.1 auth + checkout slice; spec §5.9 / T7.4). Default: skip them."
        ),
    )
    run.add_argument(
        "--record-har",
        action="store_true",
        default=False,
        help=(
            "Record a HAR capture per probe context under "
            "'<out>/evidence/<safe(label)>__rerun<N>/<probe_id>/network.har' "
            '(spec §5.8 — "Save HAR captures of every crawl"; T5.2 cohort run). Default: off.'
        ),
    )

    report = sub.add_parser(
        "report",
        help="Aggregate cohort reports into the four paper figures (spec §7 M6).",
    )
    report.add_argument(
        "--cohort",
        required=True,
        type=Path,
        help="Path to a cohort YAML (spec §8.2).",
    )
    report.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT_ROOT,
        help=(
            "Run-root directory. ProbeReports are read from "
            "'<out>/reports/' (the consolidated '<safe(label)>.json' is "
            "preferred; the max-N raw '<safe(label)>__rerun<N>.json' is "
            "used as a fallback). Figures are written under "
            f"'<out>/figures/'. Defaults to '{_DEFAULT_OUT_ROOT}'."
        ),
    )
    report.add_argument(
        "--epsilon",
        type=float,
        default=0.1,
        help="Half-width of the Turing chart's |experimental - control| band (spec §5.7).",
    )
    report.add_argument(
        "--bootstrap-iters",
        type=int,
        default=1000,
        help="Bootstrap resample count for Turing chart 95%% CIs (spec §8.4 row 4).",
    )
    report.add_argument(
        "--bootstrap-seed",
        type=int,
        default=0,
        help="Seed for the Turing chart bootstrap resampler.",
    )
    report.add_argument(
        "--baselines-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory of baseline ProbeReport JSONs (one per file). "
            "When provided, a prior-work supplement table is written alongside "
            "the primary outputs without altering per-pair claims (T7.5 \u2014 spec \u00a75.9)."
        ),
    )

    aggregate = sub.add_parser(
        "aggregate-reruns",
        help=(
            "Aggregate N=3 rerun reports for one target into a canonical "
            "ProbeReport with flake_rate_per_probe populated (spec §5.8; T5.2)."
        ),
    )
    aggregate.add_argument(
        "--runs",
        required=True,
        nargs="+",
        type=Path,
        help="Two or more ProbeReport JSON files for the same target.",
    )
    aggregate.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT_ROOT,
        help=(
            "Run-root directory. The consolidated ProbeReport is written "
            "to '<out>/reports/<safe(label)>.json' (no rerun suffix). "
            f"Defaults to '{_DEFAULT_OUT_ROOT}'."
        ),
    )
    aggregate.add_argument(
        "--gate",
        type=float,
        default=None,
        help=(
            "Per-probe flake-rate gate. When set, the command exits with "
            f"code {EXIT_USAGE} if any probe's flake rate is >= the gate "
            "(spec §5.8 paper-claim threshold defaults to 1%%)."
        ),
    )
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    """Handler for ``shop-probe run``."""
    axes = _parse_axes(args.axes)
    if axes not in {("A",), ("A", "B")}:
        print(
            f"shop-probe: --axes={args.axes!r} not supported yet "
            "(supported today: 'A' and 'A,B'; axis C lands in M4).",
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

    out_root: Path = args.out
    rerun_stem = f"{_safe_label_stem(target.label)}{_RERUN_SUFFIX_PREFIX}{args.rerun_index}"
    out_path: Path = out_root / _REPORTS_SUBDIR / f"{rerun_stem}.json"
    evidence_root: Path = out_root / _EVIDENCE_SUBDIR / rerun_stem

    report = asyncio.run(
        _run(
            target=target,
            rubric=rubric,
            evidence_root=evidence_root,
            rerun_index=args.rerun_index,
            run_axis_a="A" in axes,
            run_axis_b="B" in axes,
            include_auth=args.include_auth,
            record_har=args.record_har,
        )
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"shop-probe: wrote {out_path} "
        f"(coverage_core={report.coverage_core:.3f}, "
        f"coverage_weighted={report.coverage_weighted:.3f}"
        + (
            f", surface.distinct_templates={report.surface.distinct_templates}"
            if report.surface is not None
            else ""
        )
        + ")"
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


async def _run(
    *,
    target: Target,
    rubric: Rubric,
    evidence_root: Path,
    rerun_index: int,
    run_axis_a: bool,
    run_axis_b: bool,
    include_auth: bool = False,
    record_har: bool = False,
) -> ProbeReport:
    """Run the requested axes and assemble the closed :class:`ProbeReport`."""
    started = datetime.now(UTC)
    results: list[ProbeResult] = []
    categories: tuple[CategoryScore, ...] = ()
    c_core = c_modern = c_advanced = c_weighted = 0.0
    chromium_version = "unknown"
    selected_entries = _select_rubric_entries(rubric, include_auth=include_auth)

    if run_axis_a:
        async with ProbeRunner(evidence_root=evidence_root, record_har=record_har) as runner:
            chromium_version = runner.chromium_version
            sample_collection_url, sample_product_url = await _discover_sample_urls(
                runner, target.base_url
            )
            for entry in selected_entries:
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
        rerun_index=rerun_index,
    )


def _select_rubric_entries(rubric: Rubric, *, include_auth: bool) -> tuple[RubricEntry, ...]:
    """Filter rubric entries by the ``--include-auth`` gate (T7.4 — spec §5.9).

    With ``include_auth=False`` (default), entries flagged ``authenticated=true``
    or ``transactional=true`` are dropped before any probe runs. With
    ``include_auth=True`` the full rubric is returned. v1 has no auth or
    transactional entries, so the gate is a no-op for the v1 rubric.
    """
    if include_auth:
        return rubric.entries
    return tuple(e for e in rubric.entries if not (e.authenticated or e.transactional))


def _aggregate_coverage(
    entries: tuple[RubricEntry, ...], results: list[ProbeResult]
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
    for entry in entries:
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


# --------------------------------------------------------------------------- #
# ``shop-probe report`` (T6.5 — spec §7 M6).
# --------------------------------------------------------------------------- #


def _cmd_report(args: argparse.Namespace) -> int:
    """Handler for ``shop-probe report``."""
    cohort_path: Path = args.cohort
    out_root: Path = args.out
    reports_dir: Path = out_root / _REPORTS_SUBDIR
    out_dir: Path = out_root / _FIGURES_SUBDIR
    epsilon: float = args.epsilon
    bootstrap_iters: int = args.bootstrap_iters
    bootstrap_seed: int = args.bootstrap_seed
    baselines_dir: Path | None = args.baselines_dir

    try:
        cohort = load_cohort(cohort_path)
    except FileNotFoundError as err:
        print(f"shop-probe: cohort not found: {err}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    try:
        sandbox_reports, source_reports, real_unpaired_reports = _load_cohort_reports(
            cohort, reports_dir
        )
    except (FileNotFoundError, ValidationError, ValueError) as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    real_reports = (*source_reports, *real_unpaired_reports)
    real_population = tuple(r.surface for r in real_reports if r.surface is not None)

    cohort_fidelity = _build_cohort_fidelity(
        cohort=cohort,
        sandbox_reports=sandbox_reports,
        source_reports=source_reports,
        real_unpaired_reports=real_unpaired_reports,
        real_population=real_population,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    table_path = out_dir / _FIDELITY_TABLE_FILENAME
    table_path.write_text(render_pair_fidelity_table(cohort_fidelity), encoding="utf-8")
    written.append(table_path)

    radar_path = out_dir / _RADAR_CHART_FILENAME
    radar_path.write_text(
        render_radar_chart_svg(
            real_reports=real_reports,
            sandbox_reports=sandbox_reports,
        ),
        encoding="utf-8",
    )
    written.append(radar_path)

    if not real_population:
        print(
            "shop-probe: surface chart skipped (no real-shop surface metrics; "
            "re-run cohort with --axes A,B).",
            file=sys.stderr,
        )
    else:
        surface_path = out_dir / _SURFACE_CHART_FILENAME
        surface_path.write_text(
            render_surface_bar_chart_svg(
                real_reports=real_reports,
                sandbox_reports=sandbox_reports,
                source_reports=source_reports,
            ),
            encoding="utf-8",
        )
        written.append(surface_path)

    pairs_with_calls = tuple(
        PairTuringData(pair_id=r.target.pair_id or "", judge_calls=r.judge_calls)
        for r in sandbox_reports
        if r.judge_calls
    )
    control_calls: tuple[JudgeCall, ...] = tuple(
        call for r in real_unpaired_reports for call in r.judge_calls
    )
    if pairs_with_calls and control_calls and len(pairs_with_calls) == len(sandbox_reports):
        turing_path = out_dir / _TURING_CHART_FILENAME
        turing_path.write_text(
            render_turing_chart_svg(
                pairs=pairs_with_calls,
                control_calls=control_calls,
                epsilon=epsilon,
                bootstrap_iters=bootstrap_iters,
                bootstrap_seed=bootstrap_seed,
            ),
            encoding="utf-8",
        )
        written.append(turing_path)
    else:
        print(
            "shop-probe: turing chart skipped (axis-C judge calls not yet "
            "present on every sandbox + real_unpaired report; spec §7 M4/M5).",
            file=sys.stderr,
        )

    if baselines_dir is not None:
        result = _write_supplement_table(out_dir, baselines_dir)
        if isinstance(result, int):
            return result
        written.append(result)

    print("shop-probe: wrote " + ", ".join(str(p) for p in written))
    return EXIT_OK


def _write_supplement_table(out_dir: Path, baselines_dir: Path) -> Path | int:
    """Render the prior-work supplement table (T7.5 — spec §5.9).

    Returns the on-disk path on success, or :data:`EXIT_USAGE` when
    ``baselines_dir`` is missing or contains an invalid report. Pulled
    out of :func:`_cmd_report` to keep that function under the per-handler
    statement budget.
    """
    try:
        baseline_reports = _load_baseline_reports(baselines_dir)
    except (FileNotFoundError, ValidationError, ValueError) as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE
    supplement_path = out_dir / _SUPPLEMENT_TABLE_FILENAME
    supplement_path.write_text(
        render_prior_work_supplement_table(baseline_reports),
        encoding="utf-8",
    )
    return supplement_path


def _safe_label_stem(label: str) -> str:
    """Map a :attr:`Target.label` to its filename-safe stem (no extension)."""
    return label.replace("/", _LABEL_PATH_SEP)


def _resolve_report_path(reports_dir: Path, label: str) -> Path:
    """Pick the on-disk :class:`ProbeReport` JSON for ``label``.

    Precedence (spec §5.8 + T5.2):

    1. The consolidated ``<safe(label)>.json`` written by
       ``shop-probe aggregate-reruns``.
    2. The raw ``<safe(label)>__rerun<N>.json`` with the largest ``N``.

    Args:
        reports_dir: Directory to search.
        label: Target label (``/`` will be rewritten to ``__``).

    Returns:
        Path to the chosen JSON file.

    Raises:
        FileNotFoundError: No matching report exists in ``reports_dir``.
    """
    stem = _safe_label_stem(label)
    consolidated = reports_dir / f"{stem}.json"
    if consolidated.is_file():
        return consolidated
    candidates: list[tuple[int, Path]] = []
    for path in reports_dir.glob(f"{stem}{_RERUN_SUFFIX_PREFIX}*.json"):
        suffix = path.stem.removeprefix(f"{stem}{_RERUN_SUFFIX_PREFIX}")
        try:
            candidates.append((int(suffix), path))
        except ValueError:
            continue
    if not candidates:
        msg = (
            f"missing report for target {label!r}: expected "
            f"'{stem}.json' or '{stem}{_RERUN_SUFFIX_PREFIX}<N>.json' in {reports_dir}"
        )
        raise FileNotFoundError(msg)
    candidates.sort()
    return candidates[-1][1]


def _load_report(reports_dir: Path, target: Target) -> ProbeReport:
    """Load and validate one :class:`ProbeReport` for ``target``."""
    path = _resolve_report_path(reports_dir, target.label)
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    if report.target.label != target.label:
        msg = (
            f"report at {path} has target.label={report.target.label!r}, expected {target.label!r}"
        )
        raise ValueError(msg)
    return report


def _load_cohort_reports(
    cohort: Cohort, reports_dir: Path
) -> tuple[tuple[ProbeReport, ...], tuple[ProbeReport, ...], tuple[ProbeReport, ...]]:
    """Load every cohort target's :class:`ProbeReport` from disk."""
    if not reports_dir.is_dir():
        msg = f"reports directory does not exist: {reports_dir}"
        raise FileNotFoundError(msg)
    sandbox_reports = tuple(_load_report(reports_dir, p.sandbox) for p in cohort.pairs)
    source_reports = tuple(_load_report(reports_dir, p.source) for p in cohort.pairs)
    real_unpaired_reports = tuple(_load_report(reports_dir, t) for t in cohort.real_unpaired)
    return sandbox_reports, source_reports, real_unpaired_reports


def _load_baseline_reports(baselines_dir: Path) -> tuple[ProbeReport, ...]:
    """Load every ``*.json`` :class:`ProbeReport` from a baseline directory.

    Used by ``shop-probe report --baselines-dir`` (T7.5 — spec §5.9). The
    directory holds one :class:`ProbeReport` per prior-work environment
    (Mock Shop, WebShop, WebArena-Shopping). Files are loaded by sorted
    filename so the in-memory tuple is deterministic; the supplement
    renderer re-sorts by :attr:`Target.label` for the final byte-stable
    output.

    Raises:
        FileNotFoundError: ``baselines_dir`` does not exist or is not a
            directory.
        pydantic.ValidationError: a JSON file does not validate as a
            :class:`ProbeReport` (propagated unchanged).
    """
    if not baselines_dir.is_dir():
        msg = f"baselines directory does not exist: {baselines_dir}"
        raise FileNotFoundError(msg)
    paths = sorted(baselines_dir.glob("*.json"))
    reports: list[ProbeReport] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        reports.append(ProbeReport.model_validate(payload))
    return tuple(reports)


def _build_cohort_fidelity(
    *,
    cohort: Cohort,
    sandbox_reports: tuple[ProbeReport, ...],
    source_reports: tuple[ProbeReport, ...],
    real_unpaired_reports: tuple[ProbeReport, ...],
    real_population: tuple[SurfaceMetrics, ...],
) -> CohortFidelity:
    """Aggregate per-pair fidelity rows into a :class:`CohortFidelity`.

    Per-pair experimental judge calls live on the sandbox
    :class:`ProbeReport`; cohort-level control judge calls are aggregated
    across the ``real_unpaired`` reports (spec §5.5 step 4 + step 7).
    Pairs / cohorts whose reports carry no axis-C calls leave the
    judge fields ``None`` (M3 pilot scenario).
    """
    pairs: list[PairFidelity] = []
    for pair, sandbox_report, source_report in zip(
        cohort.pairs, sandbox_reports, source_reports, strict=True
    ):
        experimental_calls: tuple[JudgeCall, ...] | None = (
            sandbox_report.judge_calls if sandbox_report.judge_calls else None
        )
        pairs.append(
            compute_pair_fidelity(
                pair_id=pair.id,
                sandbox_report=sandbox_report,
                source_report=source_report,
                real_population=real_population,
                experimental_judge_calls=experimental_calls,
            )
        )
    control_calls: tuple[JudgeCall, ...] = tuple(
        call for r in real_unpaired_reports for call in r.judge_calls
    )
    return compute_cohort_fidelity(
        pairs=pairs,
        real_population=real_population,
        control_judge_calls=control_calls if control_calls else None,
    )


# --------------------------------------------------------------------------- #
# ``shop-probe aggregate-reruns`` (T5.2 — spec §5.8).
# --------------------------------------------------------------------------- #


def _cmd_aggregate_reruns(args: argparse.Namespace) -> int:
    """Handler for ``shop-probe aggregate-reruns``."""
    run_paths: list[Path] = list(args.runs)
    out_root: Path = args.out
    gate: float | None = args.gate

    if len(run_paths) < 2:  # noqa: PLR2004 — spec §5.8 mandates N ≥ 2 reruns
        print(
            "shop-probe: --runs requires at least two ProbeReport JSON files "
            "(spec §5.8 N=3 reruns; minimum N=2 to compute a flake rate).",
            file=sys.stderr,
        )
        return EXIT_USAGE

    reports: list[ProbeReport] = []
    for path in run_paths:
        if not path.is_file():
            print(f"shop-probe: rerun report not found: {path}", file=sys.stderr)
            return EXIT_USAGE
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            reports.append(ProbeReport.model_validate(payload))
        except (ValidationError, ValueError) as err:
            print(f"shop-probe: invalid rerun report {path}: {err}", file=sys.stderr)
            return EXIT_USAGE

    try:
        consolidated = consolidate_rerun_group(reports)
    except RerunGroupError as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    out_path = out_root / _REPORTS_SUBDIR / f"{_safe_label_stem(consolidated.target.label)}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(consolidated.model_dump_json(indent=2), encoding="utf-8")

    flake = consolidated.flake_rate_per_probe
    flaked = tuple(probe_id for probe_id, rate in flake.items() if rate > 0.0)
    summary = (
        f"shop-probe: wrote {out_path} "
        f"(target={consolidated.target.label!r}, n_runs={len(reports)}, "
        f"flaked_probes={len(flaked)}/{len(flake)})"
    )
    print(summary)

    if gate is not None:
        violations = exceeds_flake_gate(flake, gate=gate)
        if violations:
            print(
                f"shop-probe: {len(violations)} probe(s) exceeded flake gate "
                f"({gate:.0%}): {', '.join(violations)}",
                file=sys.stderr,
            )
            return EXIT_USAGE
        print(
            f"shop-probe: flake gate passed ({gate:.0%}; spec §5.8 default "
            f"is {FLAKE_RATE_GATE:.0%})."
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
