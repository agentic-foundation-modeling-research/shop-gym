"""Command-line entrypoint for ShopProbe.

Three-stage pipeline per ``docs/specs/shop_arena/web_probe_patch.md``:

* ``shop-probe run <base_url> --name … --label {sandbox,real} --out OUT/``
  produces one ``ProbeReport`` per ``(target, rerun)`` under
  ``OUT/reports/<label>__<name>__rerun<N>.json``.
* ``shop-probe aggregate-reruns --runs …`` consolidates an N-rerun group
  into a single ``<label>__<name>.json``.
* ``shop-probe report --benchmark benchmark.yaml --out OUT/`` aggregates the
  per-shop reports into a group-vs-group :class:`BenchComparison` plus
  paper figures under ``OUT/figures/``.
* ``shop-probe eval --benchmark benchmark.yaml --out OUT/`` runs all of the
  above end-to-end for every target in the benchmark.
* ``shop-probe compare`` is reserved for stage-3 cherry-pick inspection;
  the dispatch entry exists with a ``NotImplementedError`` stub.

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
from typing import Final, get_args
from urllib.parse import urljoin

from playwright.async_api import Page
from pydantic import ValidationError

from shop_probe import __version__
from shop_probe.agent.config import AgentRuntimeConfig
from shop_probe.bench import load_bench
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
    ProbeReport,
    ProbeResult,
)
from shop_probe.report_writer import (
    render_group_comparison_table,
    render_per_shop_table,
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
from shop_probe.targets import Bench, Target, TargetLabel

EXIT_OK: Final[int] = 0
EXIT_USAGE: Final[int] = 2

_PROBE_DOTTED_PREFIX: Final[str] = "probes."
_MIN_PROBE_DOTS: Final[int] = 2

_PACKAGE_RUBRIC_DIR: Final[Path] = Path(__file__).resolve().parent / "rubric"
_DISCOVERY_PROBE_ID: Final[str] = "_discover"

_RERUN_SUFFIX_PREFIX: Final[str] = "__rerun"
"""Suffix prefix for raw rerun JSON files: ``<label>__<name>__rerun<N>.json``."""

_DEFAULT_OUT_ROOT: Final[Path] = Path("outputs/shop_probe")

_REPORTS_SUBDIR: Final[str] = "reports"
_EVIDENCE_SUBDIR: Final[str] = "evidence"
_FIGURES_SUBDIR: Final[str] = "figures"

_GROUP_COMPARISON_FILENAME: Final[str] = "group_comparison.md"
_PER_SHOP_TABLE_FILENAME: Final[str] = "per_shop_table.md"
_RADAR_CHART_FILENAME: Final[str] = "radar.svg"
_SURFACE_CHART_FILENAME: Final[str] = "surface.svg"
_TURING_CHART_FILENAME: Final[str] = "turing.svg"
_SUPPLEMENT_TABLE_FILENAME: Final[str] = "supplement_table.md"

_TARGET_LABELS: Final[tuple[str, ...]] = get_args(TargetLabel)

_DEFAULT_AGENT_CONFIG: Final[AgentRuntimeConfig] = AgentRuntimeConfig()
"""Source of truth for ``--agent-*`` flag defaults (impl plan T6.1)."""

_AGENT_RUNTIME_CHOICES: Final[tuple[str, ...]] = ("claude_code", "pi")


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
    if args.command == "eval":
        return _cmd_eval(args)
    if args.command == "compare":
        return _cmd_compare(args)
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
        "--name",
        required=True,
        help="Filename-friendly identifier for the target (e.g. 'shop_alpha').",
    )
    run.add_argument(
        "--label",
        required=True,
        choices=_TARGET_LABELS,
        help="Population this target belongs to.",
    )
    run.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT_ROOT,
        help=(
            "Run-root directory. The ProbeReport JSON is written under "
            "'<out>/reports/<label>__<name>__rerun<N>.json' and probe evidence "
            "under '<out>/evidence/<label>__<name>__rerun<N>/'. "
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
        "--notes",
        default=None,
        help="Optional free-form operator notes recorded on the Target.",
    )
    run.add_argument(
        "--rerun-index",
        type=int,
        default=1,
        help="1-indexed run number within the rerun group (spec §5.8).",
    )
    run.add_argument(
        "--include-auth",
        action="store_true",
        default=False,
        help=(
            "Include rubric entries flagged authenticated=true or transactional=true "
            "(v1.1 auth + checkout slice; spec §5.9). Default: skip them."
        ),
    )
    run.add_argument(
        "--record-har",
        action="store_true",
        default=False,
        help=(
            "Record a HAR capture per probe context under "
            "'<out>/evidence/<label>__<name>__rerun<N>/<probe_id>/network.har' "
            "(spec §5.8). Default: off."
        ),
    )
    _add_agent_flags(run)

    report = sub.add_parser(
        "report",
        help="Aggregate benchmark reports into the group comparison + paper figures.",
    )
    report.add_argument(
        "--benchmark",
        required=True,
        type=Path,
        help="Path to a benchmark YAML (web_probe_patch.md).",
    )
    report.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT_ROOT,
        help=(
            "Run-root directory. ProbeReports are read from "
            "'<out>/reports/' (the consolidated '<label>__<name>.json' is "
            "preferred; the max-N raw '<label>__<name>__rerun<N>.json' is "
            "used as a fallback). Figures are written under "
            f"'<out>/figures/'. Defaults to '{_DEFAULT_OUT_ROOT}'."
        ),
    )
    report.add_argument(
        "--baselines-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory of baseline ProbeReport JSONs (one per file). "
            "When provided, a prior-work supplement table is written alongside "
            "the primary outputs without altering bench-level claims."
        ),
    )

    aggregate = sub.add_parser(
        "aggregate-reruns",
        help=(
            "Aggregate N rerun reports for one target into a canonical "
            "ProbeReport with flake_rate_per_probe populated (spec §5.8)."
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
            "to '<out>/reports/<label>__<name>.json' (no rerun suffix). "
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

    compare = sub.add_parser(
        "compare",
        help="Stage-3 cherry-pick inspection (reserved; not yet implemented).",
    )
    compare.add_argument(
        "--benchmark",
        required=True,
        type=Path,
        help="Path to a benchmark YAML.",
    )
    compare.add_argument(
        "--shop",
        required=True,
        help="Name of the shop to inspect.",
    )
    compare.add_argument(
        "--against",
        default=None,
        help="Comma-separated names of shops to compare against.",
    )

    eval_parser = sub.add_parser(
        "eval",
        help=(
            "Run the full pipeline (probe each target -> consolidate reruns -> "
            "render bench figures) for every target in a benchmark YAML."
        ),
    )
    eval_parser.add_argument(
        "--benchmark",
        required=True,
        type=Path,
        help="Path to a benchmark YAML (web_probe_patch.md).",
    )
    eval_parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT_ROOT,
        help=(
            "Run-root directory. Reports are written under '<out>/reports/' "
            "and figures under '<out>/figures/'. "
            f"Defaults to '{_DEFAULT_OUT_ROOT}'."
        ),
    )
    eval_parser.add_argument(
        "--reruns",
        type=int,
        default=1,
        help=(
            "Number of probe reruns per target (>=1). When >=2, an "
            "aggregate-reruns pass consolidates the rerun group into "
            "'<out>/reports/<label>__<name>.json' before rendering."
        ),
    )
    eval_parser.add_argument(
        "--rubric",
        default="v1",
        help="Rubric name (resolved against packaged rubrics) or YAML path.",
    )
    eval_parser.add_argument(
        "--axes",
        default="A",
        help="Comma-separated axes to run. Supported: 'A', 'A,B'.",
    )
    eval_parser.add_argument(
        "--include-auth",
        action="store_true",
        default=False,
        help="Include authenticated/transactional rubric entries (v1.1 slice).",
    )
    eval_parser.add_argument(
        "--record-har",
        action="store_true",
        default=False,
        help="Record HAR captures per probe under '<out>/evidence/.../network.har'.",
    )
    eval_parser.add_argument(
        "--gate",
        type=float,
        default=None,
        help=(
            "Per-probe flake-rate gate forwarded to aggregate-reruns. Only "
            "applied when --reruns >= 2."
        ),
    )
    eval_parser.add_argument(
        "--baselines-dir",
        type=Path,
        default=None,
        help="Optional baselines directory forwarded to the report stage.",
    )
    _add_agent_flags(eval_parser)
    return parser


def _add_agent_flags(subparser: argparse.ArgumentParser) -> None:
    """Add the v1.3 ``--agent-*`` flags to a subcommand (impl plan T6.1).

    Defaults are sourced from :data:`_DEFAULT_AGENT_CONFIG` so the dataclass
    remains the single source of truth. Flags are silently inert when the
    selected rubric has no ``level: agent_driven`` entries (e.g. ``v1.1``):
    no Anthropic calls are issued because ``run_agent_task`` is never
    invoked.
    """
    subparser.add_argument(
        "--agent-runtime",
        choices=_AGENT_RUNTIME_CHOICES,
        default=_DEFAULT_AGENT_CONFIG.runtime,
        help=(
            "Harness runtime back-end for v1.3 agent-driven probes "
            f"(default: {_DEFAULT_AGENT_CONFIG.runtime})."
        ),
    )
    subparser.add_argument(
        "--agent-model",
        default=_DEFAULT_AGENT_CONFIG.model,
        help=(
            "Model id passed to the agent runtime for plan/exec turns "
            f"(default: {_DEFAULT_AGENT_CONFIG.model})."
        ),
    )
    subparser.add_argument(
        "--agent-step-budget",
        type=int,
        default=_DEFAULT_AGENT_CONFIG.step_budget,
        help=(
            "Default max iterations for the harness plan/exec loop; per-task "
            "`AgentTaskInline.step_budget` overrides take precedence "
            f"(default: {_DEFAULT_AGENT_CONFIG.step_budget})."
        ),
    )
    subparser.add_argument(
        "--agent-timeout-s",
        type=int,
        default=_DEFAULT_AGENT_CONFIG.timeout_s,
        help=(
            "Default wall-clock budget (seconds) for one agent task run; "
            "per-task `AgentTaskInline.timeout_s` overrides take precedence "
            f"(default: {_DEFAULT_AGENT_CONFIG.timeout_s})."
        ),
    )
    subparser.add_argument(
        "--agent-judge-model",
        default=_DEFAULT_AGENT_CONFIG.judge_model,
        help=(
            "Model id used for the vision completion judge "
            f"(default: {_DEFAULT_AGENT_CONFIG.judge_model})."
        ),
    )


def _build_agent_config(args: argparse.Namespace) -> AgentRuntimeConfig:
    """Materialise an :class:`AgentRuntimeConfig` from parsed CLI flags."""
    return AgentRuntimeConfig(
        runtime=args.agent_runtime,
        model=args.agent_model,
        step_budget=args.agent_step_budget,
        timeout_s=args.agent_timeout_s,
        judge_model=args.agent_judge_model,
    )


# --------------------------------------------------------------------------- #
# ``shop-probe run`` (stage 1).
# --------------------------------------------------------------------------- #


def _cmd_run(args: argparse.Namespace) -> int:
    """Handler for ``shop-probe run``."""
    axes = _parse_axes(args.axes)
    if axes not in {("A",), ("A", "B")}:
        print(
            f"shop-probe: --axes={args.axes!r} not supported yet "
            "(supported today: 'A' and 'A,B'; axis C lands in a follow-on patch).",
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
            name=args.name,
            base_url=args.base_url,
            label=args.label,
            notes=args.notes,
        )
    except ValidationError as err:
        print(f"shop-probe: invalid target: {err}", file=sys.stderr)
        return EXIT_USAGE

    out_root: Path = args.out
    rerun_stem = f"{_target_stem(target)}{_RERUN_SUFFIX_PREFIX}{args.rerun_index}"
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
            agent_config=_build_agent_config(args),
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
    """Resolve ``--rubric`` to a YAML file path."""
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
    agent_config: AgentRuntimeConfig | None = None,
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
                if entry.level == "agent_driven":
                    # v1.3 agent-driven dispatch (impl plan T4.1). Inline
                    # ``agent_task`` block drives the runner-owned closure
                    # around ``run_agent_task``; outer wait gets the
                    # task budget + buffer.
                    outcome = await runner.run_agent_entry(
                        entry,
                        base_url=target.base_url,
                        sample_product_url=sample_product_url,
                        sample_collection_url=sample_collection_url,
                        agent_config=agent_config,
                    )
                else:
                    # Deterministic entries always carry a ``probe`` ref;
                    # the schema validator enforces this for non
                    # ``agent_driven`` levels.
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
    total_judge_cost_usd, total_agent_cost_usd = _aggregate_cost_totals(results)
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
        total_judge_cost_usd=total_judge_cost_usd,
        total_agent_cost_usd=total_agent_cost_usd,
    )


def _select_rubric_entries(rubric: Rubric, *, include_auth: bool) -> tuple[RubricEntry, ...]:
    """Filter rubric entries by the ``--include-auth`` gate."""
    if include_auth:
        return rubric.entries
    return tuple(e for e in rubric.entries if not (e.authenticated or e.transactional))


def _build_probe_result(probe_id: str, outcome: ProbeOutcome) -> ProbeResult:
    """Project a :class:`ProbeOutcome` into the closed :class:`ProbeResult`.

    Forwards optional v1.3 cost / model side-channel values from
    :attr:`ProbeOutcome.extra` (``judge_cost_usd``, ``judge_model``,
    ``agent_cost_usd``, ``agent_model``) onto the report row so the
    aggregator can roll cohort cost totals up to :class:`ProbeReport`.
    Deterministic probes leave ``extra`` empty and the four cost fields
    stay ``None``.
    """
    return ProbeResult(
        id=probe_id,
        passed=outcome.passed,
        evidence=outcome.evidence,
        notes=outcome.notes,
        duration_ms=outcome.duration_ms,
        judge_cost_usd=_extra_float(outcome.extra, "judge_cost_usd"),
        judge_model=_extra_str(outcome.extra, "judge_model"),
        agent_cost_usd=_extra_float(outcome.extra, "agent_cost_usd"),
        agent_model=_extra_str(outcome.extra, "agent_model"),
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


def _aggregate_cost_totals(
    results: list[ProbeResult],
) -> tuple[float | None, float | None]:
    """Sum per-probe v1.3 cost fields into cohort-level rollups.

    Returns ``(total_judge_cost_usd, total_agent_cost_usd)``. Either
    rollup is ``None`` when no probe in the report carried that field
    — distinguishing "v1.1 cohort, never priced" from "v1.3 cohort, all
    judge calls free" (which would surface as ``0.0``).
    """
    judge_costs = [r.judge_cost_usd for r in results if r.judge_cost_usd is not None]
    agent_costs = [r.agent_cost_usd for r in results if r.agent_cost_usd is not None]
    total_judge = sum(judge_costs) if judge_costs else None
    total_agent = sum(agent_costs) if agent_costs else None
    return total_judge, total_agent


def _aggregate_coverage(
    entries: tuple[RubricEntry, ...], results: list[ProbeResult]
) -> tuple[tuple[CategoryScore, ...], float, float, float, float]:
    """Compute per-category + per-level + weighted coverage (spec §5.3)."""
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
        # v1.3 ``agent_driven`` entries replace the v1.2 deterministic
        # ``advanced`` tier and roll up into ``coverage_advanced`` so the
        # M7 success criterion (sandbox vs. real ``coverage_advanced`` gap)
        # is measured on the same axis as v1.2.
        level_bucket = "advanced" if entry.level == "agent_driven" else entry.level
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
# ``shop-probe report`` (stage 2).
# --------------------------------------------------------------------------- #


def _cmd_report(args: argparse.Namespace) -> int:  # noqa: PLR0915
    """Handler for ``shop-probe report``."""
    bench_path: Path = args.benchmark
    out_root: Path = args.out
    reports_dir: Path = out_root / _REPORTS_SUBDIR
    out_dir: Path = out_root / _FIGURES_SUBDIR
    baselines_dir: Path | None = args.baselines_dir

    try:
        bench = load_bench(bench_path)
    except FileNotFoundError as err:
        print(f"shop-probe: benchmark not found: {err}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    try:
        sandbox_reports, real_reports = _load_bench_reports(bench, reports_dir)
    except (FileNotFoundError, ValidationError, ValueError) as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    try:
        comparison = _build_bench_comparison(
            sandbox_reports=sandbox_reports,
            real_reports=real_reports,
        )
    except ValueError as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    table_path = out_dir / _GROUP_COMPARISON_FILENAME
    table_path.write_text(render_group_comparison_table(comparison), encoding="utf-8")
    written.append(table_path)

    per_shop_path = out_dir / _PER_SHOP_TABLE_FILENAME
    per_shop_path.write_text(
        render_per_shop_table(sandbox_reports, real_reports, comparison),
        encoding="utf-8",
    )
    written.append(per_shop_path)

    radar_path = out_dir / _RADAR_CHART_FILENAME
    radar_path.write_text(
        render_radar_chart_svg(
            real_reports=real_reports,
            sandbox_reports=sandbox_reports,
        ),
        encoding="utf-8",
    )
    written.append(radar_path)

    real_with_surface = tuple(r for r in real_reports if r.surface is not None)
    sandbox_with_surface = tuple(r for r in sandbox_reports if r.surface is not None)
    if not real_with_surface:
        print(
            "shop-probe: surface chart skipped (no real-shop surface metrics; "
            "re-run bench with --axes A,B).",
            file=sys.stderr,
        )
    else:
        surface_path = out_dir / _SURFACE_CHART_FILENAME
        surface_path.write_text(
            render_surface_bar_chart_svg(
                real_reports=real_with_surface,
                sandbox_reports=sandbox_with_surface,
            ),
            encoding="utf-8",
        )
        written.append(surface_path)

    if comparison.sandbox.judge_calls_total > 0 and comparison.real.judge_calls_total > 0:
        turing_path = out_dir / _TURING_CHART_FILENAME
        turing_path.write_text(render_turing_chart_svg(comparison), encoding="utf-8")
        written.append(turing_path)
    else:
        print(
            "shop-probe: turing chart skipped (axis-C judge calls not yet present on both groups).",
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
    """Render the prior-work supplement table.

    Returns the on-disk path on success, or :data:`EXIT_USAGE` when
    ``baselines_dir`` is missing or contains an invalid report.
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


def _target_stem(target: Target) -> str:
    """Filename stem for a target: ``<label>__<name>``."""
    return f"{target.label}__{target.name}"


def _resolve_report_path(reports_dir: Path, target: Target) -> Path:
    """Pick the on-disk :class:`ProbeReport` JSON for ``target``.

    Precedence:

    1. The consolidated ``<label>__<name>.json`` written by
       ``shop-probe aggregate-reruns``.
    2. The raw ``<label>__<name>__rerun<N>.json`` with the largest ``N``.
    """
    stem = _target_stem(target)
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
            f"missing report for target {target.name!r}: expected "
            f"'{stem}.json' or '{stem}{_RERUN_SUFFIX_PREFIX}<N>.json' in {reports_dir}"
        )
        raise FileNotFoundError(msg)
    candidates.sort()
    return candidates[-1][1]


def _load_report(reports_dir: Path, target: Target) -> ProbeReport:
    """Load and validate one :class:`ProbeReport` for ``target``."""
    path = _resolve_report_path(reports_dir, target)
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    if report.target.name != target.name or report.target.label != target.label:
        msg = (
            f"report at {path} has target=({report.target.label}, "
            f"{report.target.name}), expected ({target.label}, {target.name})"
        )
        raise ValueError(msg)
    return report


def _load_bench_reports(
    bench: Bench, reports_dir: Path
) -> tuple[tuple[ProbeReport, ...], tuple[ProbeReport, ...]]:
    """Load every bench target's :class:`ProbeReport` from disk."""
    if not reports_dir.is_dir():
        msg = f"reports directory does not exist: {reports_dir}"
        raise FileNotFoundError(msg)
    sandbox_reports = tuple(_load_report(reports_dir, t) for t in bench.sandboxes)
    real_reports = tuple(_load_report(reports_dir, t) for t in bench.reals)
    return sandbox_reports, real_reports


def _load_baseline_reports(baselines_dir: Path) -> tuple[ProbeReport, ...]:
    """Load every ``*.json`` :class:`ProbeReport` from a baseline directory."""
    if not baselines_dir.is_dir():
        msg = f"baselines directory does not exist: {baselines_dir}"
        raise FileNotFoundError(msg)
    paths = sorted(baselines_dir.glob("*.json"))
    reports: list[ProbeReport] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        reports.append(ProbeReport.model_validate(payload))
    return tuple(reports)


def _build_bench_comparison(
    *,
    sandbox_reports: tuple[ProbeReport, ...],
    real_reports: tuple[ProbeReport, ...],
) -> BenchComparison:
    """Aggregate sandbox + real reports into a :class:`BenchComparison`."""
    return compute_bench_comparison(sandbox_reports, real_reports)


# --------------------------------------------------------------------------- #
# ``shop-probe aggregate-reruns``.
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

    out_path = out_root / _REPORTS_SUBDIR / f"{_target_stem(consolidated.target)}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(consolidated.model_dump_json(indent=2), encoding="utf-8")

    flake = consolidated.flake_rate_per_probe
    flaked = tuple(probe_id for probe_id, rate in flake.items() if rate > 0.0)
    summary = (
        f"shop-probe: wrote {out_path} "
        f"(target={consolidated.target.name!r}, n_runs={len(reports)}, "
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


# --------------------------------------------------------------------------- #
# ``shop-probe compare`` (stage 3 — reserved).
# --------------------------------------------------------------------------- #


def _cmd_compare(args: argparse.Namespace) -> int:
    """Handler for ``shop-probe compare`` (stage 3 — not yet implemented)."""
    del args  # signature preserved for future implementation.
    msg = (
        "shop-probe compare is reserved for stage-3 cherry-pick inspection; "
        "implementation lands in a follow-on patch."
    )
    raise NotImplementedError(msg)


# --------------------------------------------------------------------------- #
# ``shop-probe eval`` — end-to-end pipeline driver.
# --------------------------------------------------------------------------- #


def _cmd_eval(args: argparse.Namespace) -> int:
    """Handler for ``shop-probe eval`` (end-to-end pipeline)."""
    benchmark_path: Path = args.benchmark
    out_root: Path = args.out
    reruns: int = args.reruns

    if reruns < 1:
        print(
            f"shop-probe: --reruns={reruns} must be >= 1.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        bench = load_bench(benchmark_path)
    except FileNotFoundError as err:
        print(f"shop-probe: benchmark not found: {err}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as err:
        print(f"shop-probe: {err}", file=sys.stderr)
        return EXIT_USAGE

    targets: tuple[Target, ...] = (*bench.sandboxes, *bench.reals)
    print(f"shop-probe eval: benchmark={benchmark_path} targets={len(targets)} reruns={reruns}")

    for target in targets:
        for rerun_index in range(1, reruns + 1):
            run_args = argparse.Namespace(
                base_url=target.base_url,
                name=target.name,
                label=target.label,
                notes=target.notes,
                axes=args.axes,
                rubric=args.rubric,
                rerun_index=rerun_index,
                include_auth=args.include_auth,
                record_har=args.record_har,
                out=out_root,
                agent_runtime=args.agent_runtime,
                agent_model=args.agent_model,
                agent_step_budget=args.agent_step_budget,
                agent_timeout_s=args.agent_timeout_s,
                agent_judge_model=args.agent_judge_model,
            )
            rc = _cmd_run(run_args)
            if rc != EXIT_OK:
                print(
                    f"shop-probe eval: aborted on target={target.name!r} rerun={rerun_index}.",
                    file=sys.stderr,
                )
                return rc

        if reruns >= 2:  # noqa: PLR2004 — spec §5.8 mandates N >= 2 to compute flake.
            stem = _target_stem(target)
            run_paths = [
                out_root / _REPORTS_SUBDIR / f"{stem}{_RERUN_SUFFIX_PREFIX}{i}.json"
                for i in range(1, reruns + 1)
            ]
            agg_args = argparse.Namespace(
                runs=run_paths,
                out=out_root,
                gate=args.gate,
            )
            rc = _cmd_aggregate_reruns(agg_args)
            if rc != EXIT_OK:
                print(
                    f"shop-probe eval: aborted on target={target.name!r} during aggregate-reruns.",
                    file=sys.stderr,
                )
                return rc

    report_args = argparse.Namespace(
        benchmark=benchmark_path,
        out=out_root,
        baselines_dir=args.baselines_dir,
    )
    return _cmd_report(report_args)


if __name__ == "__main__":
    raise SystemExit(main())
