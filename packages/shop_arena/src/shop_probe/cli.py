"""``shop-probe`` CLI driver — single ``eval`` subcommand.

Walks a bench YAML, captures a 5-page bundle per target, runs the v1.0
rubric (mechanical metrics + LLM judge slots + scripted transitions),
emits a per-target ``ProbeReport``, and rolls the cohort up into the
four ``*_fidelity.md`` markdown artifacts.

Layout produced under ``--out``::

    <out>/
    ├── reports/<target_name>.json   # one ProbeReport per target
    ├── bundles/<target_name>/       # per-target capture artifacts
    └── figures/                     # cohort rollup
        ├── observation_fidelity.md
        ├── action_fidelity.md
        ├── transition_fidelity.md
        └── summary.md

Reports cache by ``(rubric_hash, target.name)``: re-running with the
same rubric on the same target reuses the on-disk JSON unless
``--force`` is passed.
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Final

from playwright.async_api import async_playwright

from shop_probe import __version__
from shop_probe.action.control_slots import judge_control_slots
from shop_probe.action.space import compute_action_space
from shop_probe.bench import load_bench
from shop_probe.capture.bundle import capture_bundle, discover_sample_urls
from shop_probe.fidelity import compare_cohorts
from shop_probe.judge.client import open_judge_client
from shop_probe.observation.info_slots import judge_info_slots
from shop_probe.observation.shape import compute_shape
from shop_probe.playwright_runner import PlaywrightRunner
from shop_probe.report import (
    ActionBlock,
    BrowserMeta,
    ObservationBlock,
    ProbeReport,
    SlotVerdict,
    TransitionResult,
)
from shop_probe.report_writer import write_figures
from shop_probe.rubric import Rubric, load_rubric
from shop_probe.rubric.schema import Modality, PageType
from shop_probe.targets import Target
from shop_probe.transition.runner import run_transitions

_DEFAULT_RUBRIC: Final[Path] = (
    Path(__file__).resolve().parent / "rubric" / "rubric.yaml"
)
"""Shipped rubric path (``shop_probe/rubric/rubric.yaml``)."""

_PROMPTS_ROOT: Final[Path] = Path(__file__).resolve().parent / "judge"
"""Resolves rubric ``prompt: prompts/...`` paths."""


def main(argv: list[str] | None = None) -> int:
    """Entry point dispatched from ``project.scripts.shop-probe``."""
    parser = argparse.ArgumentParser(
        prog="shop-probe", description="ShopProbe v1.0 cohort fidelity instrument"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    eval_parser = sub.add_parser("eval", help="Capture, judge, and roll up a bench.")
    eval_parser.add_argument(
        "--benchmark",
        type=Path,
        required=True,
        help="Path to a bench YAML (sandboxes + reals).",
    )
    eval_parser.add_argument(
        "--out", type=Path, required=True, help="Output directory."
    )
    eval_parser.add_argument(
        "--rubric",
        type=Path,
        default=_DEFAULT_RUBRIC,
        help="Rubric YAML path (default: shipped rubric).",
    )
    eval_parser.add_argument(
        "--judge-model",
        default="anthropic:claude-haiku-4-5",
        help="Provider-prefixed judge model id (default: anthropic:claude-haiku-4-5).",
    )
    eval_parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the per-target report cache and re-run.",
    )
    eval_parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip LLM judge slots (mechanical + transitions only).",
    )
    eval_parser.add_argument(
        "--no-transitions",
        action="store_true",
        help="Skip scripted transitions.",
    )

    args = parser.parse_args(argv)
    if args.command == "eval":
        return asyncio.run(_run_eval(args))
    parser.error(f"unknown command {args.command!r}")
    return 2


async def _run_eval(args: argparse.Namespace) -> int:
    rubric = load_rubric(args.rubric)
    bench = load_bench(args.benchmark)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    reports_dir = out / "reports"
    bundles_dir = out / "bundles"
    figures_dir = out / "figures"
    reports_dir.mkdir(parents=True, exist_ok=True)
    bundles_dir.mkdir(parents=True, exist_ok=True)

    targets: tuple[Target, ...] = (*bench.sandboxes, *bench.reals)
    if not targets:
        print("bench is empty; nothing to do", file=sys.stderr)
        return 1

    runtime = await _resolve_runtime()
    sandbox_reports: list[ProbeReport] = []
    real_reports: list[ProbeReport] = []

    async with PlaywrightRunner() as runner:
        for target in targets:
            cached = _load_cached_report(reports_dir, target, rubric, force=args.force)
            if cached is not None:
                print(f"  ↻ {target.name}: reusing cached report")
            else:
                print(f"  → {target.name}: probing")
                cached = await _probe_target(
                    target,
                    rubric=rubric,
                    runner=runner,
                    bundles_dir=bundles_dir,
                    runtime=runtime,
                    judge_model=args.judge_model,
                    skip_judge=args.no_judge,
                    skip_transitions=args.no_transitions,
                )
                _write_report(reports_dir, cached)
            (sandbox_reports if target.label == "sandbox" else real_reports).append(cached)

    if not sandbox_reports and not real_reports:
        print("no reports produced", file=sys.stderr)
        return 1

    comparison = compare_cohorts(sandbox=sandbox_reports, real=real_reports)
    written = write_figures(comparison, out_dir=figures_dir)
    print(f"wrote {len(written)} figures under {figures_dir}")
    return 0


# ---------- Per-target probe ---------------------------------------------


async def _probe_target(
    target: Target,
    *,
    rubric: Rubric,
    runner: PlaywrightRunner,
    bundles_dir: Path,
    runtime: BrowserMeta,
    judge_model: str,
    skip_judge: bool,
    skip_transitions: bool,
) -> ProbeReport:
    """Run capture + family runners for one target and return a typed report."""
    bundle_root = bundles_dir / target.name
    sample_collection_url, sample_product_url = await discover_sample_urls(
        runner, target.base_url
    )
    bundle = await capture_bundle(
        runner,
        base_url=target.base_url,
        sample_collection_url=sample_collection_url,
        sample_product_url=sample_product_url,
        bundle_root=bundle_root,
    )

    # Mechanical metrics — no LLM, no Playwright re-navigation.
    shape = compute_shape(bundle, bundle_root=bundle_root)
    space = compute_action_space(bundle, bundle_root=bundle_root)

    # Judge slots — gated by --no-judge.
    info_slots: dict[PageType, dict[str, dict[Modality, SlotVerdict]]] = {}
    control_slots: dict[PageType, dict[str, dict[Modality, SlotVerdict]]] = {}
    if not skip_judge:
        async with open_judge_client(judge_model) as client:
            info_slots = await judge_info_slots(
                rubric.entries,
                bundle=bundle,
                bundle_root=bundle_root,
                prompts_root=_PROMPTS_ROOT,
                model=judge_model,
                client=client,
            )
            control_slots = await judge_control_slots(
                rubric.entries,
                bundle=bundle,
                bundle_root=bundle_root,
                prompts_root=_PROMPTS_ROOT,
                model=judge_model,
                client=client,
            )

    # Scripted transitions — gated by --no-transitions.
    transition: dict[PageType, dict[str, TransitionResult]] = {}
    if not skip_transitions:
        transition = await run_transitions(
            rubric.entries,
            runner=runner,
            base_url=target.base_url,
            sample_collection_url=sample_collection_url,
            sample_product_url=sample_product_url,
        )

    modality_consistency = _modality_consistency(info_slots, control_slots)
    total_cost = _sum_cost(info_slots) + _sum_cost(control_slots)

    return ProbeReport(
        target=target,
        rubric_version=rubric.version,
        rubric_hash=rubric.content_hash,
        runner_version=__version__,
        runtime=runtime,
        timestamp=datetime.now(timezone.utc),
        observation=ObservationBlock(shape=shape, info_slots=info_slots),
        action=ActionBlock(space=space, control_slots=control_slots),
        transition=transition,
        modality_consistency=modality_consistency,
        total_judge_cost_usd=total_cost,
    )


# ---------- Modality consistency + cost helpers ---------------------------


def _modality_consistency(
    info_slots: dict[PageType, dict[str, dict[Modality, SlotVerdict]]],
    control_slots: dict[PageType, dict[str, dict[Modality, SlotVerdict]]],
) -> dict[PageType, float]:
    """Per page type, mean over slots of ``verdict_a11y == verdict_screenshot``.

    Skips slots that do not carry both modalities (no signal to compare).
    """
    out: dict[PageType, float] = {}
    for page_type in (*info_slots.keys(), *control_slots.keys()):
        if page_type in out:
            continue
        agreements: list[bool] = []
        for block in (info_slots, control_slots):
            slots = block.get(page_type, {})
            for verdicts in slots.values():
                a11y = verdicts.get("a11y")
                screenshot = verdicts.get("screenshot")
                if a11y is None or screenshot is None:
                    continue
                agreements.append(a11y.present == screenshot.present)
        if agreements:
            out[page_type] = sum(agreements) / len(agreements)
    return out


def _sum_cost(
    block: dict[PageType, dict[str, dict[Modality, SlotVerdict]]],
) -> float:
    total = 0.0
    for slots in block.values():
        for verdicts in slots.values():
            for verdict in verdicts.values():
                total += verdict.judge_cost_usd
    return total


# ---------- Cache layer ---------------------------------------------------


def _report_path(reports_dir: Path, target: Target) -> Path:
    return reports_dir / f"{target.name}.json"


def _load_cached_report(
    reports_dir: Path,
    target: Target,
    rubric: Rubric,
    *,
    force: bool,
) -> ProbeReport | None:
    if force:
        return None
    path = _report_path(reports_dir, target)
    if not path.is_file():
        return None
    try:
        report = ProbeReport.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — invalid cache → re-probe
        return None
    if report.rubric_hash != rubric.content_hash:
        return None
    return report


def _write_report(reports_dir: Path, report: ProbeReport) -> None:
    path = _report_path(reports_dir, report.target)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


# ---------- Runtime metadata ----------------------------------------------


async def _resolve_runtime() -> BrowserMeta:
    """Snap the pinned runtime metadata embedded in every report header."""
    try:
        playwright_version = metadata.version("playwright")
    except metadata.PackageNotFoundError:  # pragma: no cover — playwright is a hard dep
        playwright_version = "unknown"
    chromium_version = await _chromium_version()
    runner = PlaywrightRunner()  # for default UA + viewport constants
    return BrowserMeta(
        python_version=platform.python_version(),
        playwright_version=playwright_version,
        chromium_version=chromium_version,
        user_agent=runner.user_agent,
        viewport=runner.viewport,
        headless=True,
    )


async def _chromium_version() -> str:
    """Probe Chromium's version label via a brief Playwright launch."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            return browser.version
        finally:
            await browser.close()


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
