"""Markdown table renderers for the v1.0 cohort report (spec §5.5).

Four artifacts under ``<out>/figures/``:

* ``observation_fidelity.md`` — shape Mann-Whitney + Cliff's δ table and
  info-slot RBC coverage block.
* ``action_fidelity.md`` — same, on action.space and control_slots.
* ``transition_fidelity.md`` — per-transition per-bit success rates.
* ``summary.md`` — three per-family RBC headlines and a textual strip
  of per-shop RBC.

Renderers are pure: they take a :class:`BenchComparison` and return a
markdown string. The CLI handles I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from shop_probe.fidelity import (
    BenchComparison,
    ContinuousStat,
    SlotFamilyCoverage,
    cliffs_delta_label,
)
from shop_probe.rubric.schema import PageType

_PAGE_ORDER: Final[tuple[PageType, ...]] = (
    "homepage",
    "collection",
    "product",
    "search",
    "cart",
)


def _fmt_float(value: float | None, *, places: int = 3) -> str:
    return "—" if value is None else f"{value:.{places}f}"


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _fmt_int(value: int | None) -> str:
    return "—" if value is None else str(value)


# ---------- Continuous-stat tables ----------------------------------------


def _render_continuous_table(
    title: str,
    rows: Sequence[ContinuousStat],
) -> str:
    """Render a Mann-Whitney + Cliff's δ table for one stat family."""
    if not rows:
        return f"### {title}\n\n_No metrics in this section._\n"

    header = (
        "| page | modality | metric | n_real | n_sbx | mean_real | "
        "Q1_real | Q3_real | median_sbx | U | p | δ | effect |"
    )
    sep = "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    lines = [f"### {title}", "", header, sep]
    for row in sorted(rows, key=lambda r: (_PAGE_ORDER.index(r.page_type), r.modality, r.metric)):
        delta_label = cliffs_delta_label(row.cliffs_delta) if row.cliffs_delta is not None else "—"
        lines.append(
            "| "
            + " | ".join(
                [
                    row.page_type,
                    row.modality,
                    row.metric,
                    _fmt_int(row.n_real),
                    _fmt_int(row.n_sandbox),
                    _fmt_float(row.mean_real),
                    _fmt_float(row.q1_real),
                    _fmt_float(row.q3_real),
                    _fmt_float(row.median_sandbox),
                    _fmt_float(row.u_statistic, places=1),
                    _fmt_float(row.p_value),
                    _fmt_float(row.cliffs_delta),
                    delta_label,
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------- Slot RBC tables -----------------------------------------------


def _render_slot_coverage(coverage: SlotFamilyCoverage) -> str:
    lines: list[str] = [f"### {coverage.family_label} — RBC", ""]
    lines.append(
        f"- n_real = **{coverage.n_real}**, n_sandbox = **{coverage.n_sandbox}**, "
        f"quorum k = **{coverage.quorum_k}**, baseline size = **{coverage.baseline_size}**"
    )
    lines.append(
        f"- mean RBC (sandbox) = **{_fmt_pct(coverage.mean_rbc_sandbox)}**"
    )
    lines.append(
        "- real-cohort leave-one-out RBC ∈ "
        f"[{_fmt_pct(coverage.min_rbc_real_loo)}, {_fmt_pct(coverage.max_rbc_real_loo)}]"
    )
    lines.append("")

    if coverage.rbc_per_sandbox:
        lines.extend(["#### Per-sandbox RBC", "", "| shop | RBC |", "| --- | ---: |"])
        for name, rbc in sorted(coverage.rbc_per_sandbox.items()):
            lines.append(f"| {name} | {_fmt_pct(rbc)} |")
        lines.append("")

    if coverage.rbc_real_loo:
        lines.extend(["#### Real-cohort leave-one-out RBC", "", "| shop | RBC |", "| --- | ---: |"])
        for name, rbc in sorted(coverage.rbc_real_loo.items()):
            lines.append(f"| {name} | {_fmt_pct(rbc)} |")
        lines.append("")

    if coverage.slots:
        lines.extend(
            [
                "#### Slot-level real pass rates",
                "",
                "| page | slot | modality | pass_rate_real | in_baseline |",
                "| --- | --- | --- | ---: | :-: |",
            ]
        )
        for slot in sorted(
            coverage.slots,
            key=lambda s: (_PAGE_ORDER.index(s.page_type), s.slot_id, s.modality),
        ):
            lines.append(
                f"| {slot.page_type} | {slot.slot_id} | {slot.modality} | "
                f"{_fmt_pct(slot.pass_rate_real)} | "
                f"{'✅' if slot.in_baseline else '·'} |"
            )
        lines.append("")
    return "\n".join(lines)


# ---------- Top-level renderers -------------------------------------------


def _header(title: str, comparison: BenchComparison) -> str:
    return (
        f"# {title}\n\n"
        f"- rubric: `{comparison.rubric_version}` "
        f"({comparison.rubric_hash[:12]}…)\n"
        f"- cohorts: {comparison.n_sandbox} sandbox / {comparison.n_real} real\n"
    )


def render_observation_fidelity(comparison: BenchComparison) -> str:
    """Render the ``observation_fidelity.md`` artifact."""
    parts = [_header("observation fidelity", comparison)]
    parts.append(
        _render_continuous_table("observation.shape — Mann-Whitney + Cliff's δ", comparison.shape_stats)
    )
    parts.append(_render_slot_coverage(comparison.info_slots))
    if comparison.mean_modality_consistency_sandbox or comparison.mean_modality_consistency_real:
        parts.append(_render_modality_consistency(comparison))
    return "\n".join(parts).rstrip() + "\n"


def render_action_fidelity(comparison: BenchComparison) -> str:
    """Render the ``action_fidelity.md`` artifact."""
    parts = [_header("action fidelity", comparison)]
    parts.append(
        _render_continuous_table("action.space — Mann-Whitney + Cliff's δ", comparison.space_stats)
    )
    parts.append(_render_slot_coverage(comparison.control_slots))
    return "\n".join(parts).rstrip() + "\n"


def render_transition_fidelity(comparison: BenchComparison) -> str:
    """Render the ``transition_fidelity.md`` artifact."""
    parts: list[str] = [_header("transition fidelity", comparison), ""]
    if not comparison.transitions:
        parts.append("_No transitions recorded._")
        return "\n".join(parts).rstrip() + "\n"

    parts.extend(
        [
            "| page | slot | n_real | n_sbx | bit | real | sandbox |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: |",
        ]
    )
    for row in sorted(
        comparison.transitions,
        key=lambda r: (_PAGE_ORDER.index(r.page_type), r.slot_id),
    ):
        for bit in ("action_found", "action_executed", "state_changed", "state_changed_as_expected"):
            parts.append(
                f"| {row.page_type} | {row.slot_id} | {row.n_real} | {row.n_sandbox} | "
                f"{bit} | {_fmt_pct(row.real_rates.get(bit))} | "
                f"{_fmt_pct(row.sandbox_rates.get(bit))} |"
            )
    parts.append("")
    return "\n".join(parts)


def _render_modality_consistency(comparison: BenchComparison) -> str:
    lines = ["### modality consistency (mean over slots in each cohort)", ""]
    lines.extend(["| page | sandbox | real |", "| --- | ---: | ---: |"])
    pages = sorted(
        set(comparison.mean_modality_consistency_sandbox)
        | set(comparison.mean_modality_consistency_real),
        key=lambda pt: _PAGE_ORDER.index(pt),
    )
    for page_type in pages:
        sbx = comparison.mean_modality_consistency_sandbox.get(page_type)
        real = comparison.mean_modality_consistency_real.get(page_type)
        lines.append(f"| {page_type} | {_fmt_pct(sbx)} | {_fmt_pct(real)} |")
    lines.append("")
    return "\n".join(lines)


def render_summary(comparison: BenchComparison) -> str:
    """Render the ``summary.md`` headline + per-shop strip artifact."""
    parts = [_header("ShopProbe summary", comparison), ""]
    parts.append("## Headline RBC (cohort means)")
    parts.append("")
    parts.extend(
        [
            "| family | sandbox mean RBC | real LOO range |",
            "| --- | ---: | --- |",
            (
                f"| observation.info_slots | "
                f"{_fmt_pct(comparison.info_slots.mean_rbc_sandbox)} | "
                f"[{_fmt_pct(comparison.info_slots.min_rbc_real_loo)}, "
                f"{_fmt_pct(comparison.info_slots.max_rbc_real_loo)}] |"
            ),
            (
                f"| action.control_slots | "
                f"{_fmt_pct(comparison.control_slots.mean_rbc_sandbox)} | "
                f"[{_fmt_pct(comparison.control_slots.min_rbc_real_loo)}, "
                f"{_fmt_pct(comparison.control_slots.max_rbc_real_loo)}] |"
            ),
            "",
        ]
    )
    parts.append("## Transition success (`state_changed_as_expected`)")
    parts.append("")
    if comparison.transitions:
        parts.extend(["| page | slot | real | sandbox |", "| --- | --- | ---: | ---: |"])
        for row in sorted(
            comparison.transitions,
            key=lambda r: (_PAGE_ORDER.index(r.page_type), r.slot_id),
        ):
            parts.append(
                f"| {row.page_type} | {row.slot_id} | "
                f"{_fmt_pct(row.real_rates.get('state_changed_as_expected'))} | "
                f"{_fmt_pct(row.sandbox_rates.get('state_changed_as_expected'))} |"
            )
        parts.append("")
    else:
        parts.append("_No transitions recorded._\n")

    parts.append("## Per-sandbox RBC (info_slots)")
    parts.append("")
    if comparison.info_slots.rbc_per_sandbox:
        parts.append(_strip_plot(comparison.info_slots.rbc_per_sandbox.items()))
    else:
        parts.append("_No sandbox shops._")
    parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _strip_plot(rows: Iterable[tuple[str, float]], *, width: int = 30) -> str:
    """Tiny ASCII strip plot — width-N bar per shop, RBC ∈ [0, 1]."""
    rendered: list[str] = []
    for name, rbc in sorted(rows):
        bar_len = int(round(max(0.0, min(1.0, rbc)) * width))
        bar = "█" * bar_len + " " * (width - bar_len)
        rendered.append(f"  {name:<24}|{bar}| {_fmt_pct(rbc)}")
    return "```\n" + "\n".join(rendered) + "\n```"


# ---------- Disk writer ----------------------------------------------------


def write_figures(comparison: BenchComparison, *, out_dir: Path) -> dict[str, Path]:
    """Write the four ``*_fidelity.md`` / ``summary.md`` artifacts.

    Args:
        comparison: Cohort rollup.
        out_dir: Directory to write the markdown artifacts under. Created
            if it does not exist.

    Returns:
        Mapping of ``stem -> path`` for each artifact written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, tuple[Path, str]] = {
        "observation_fidelity": (
            out_dir / "observation_fidelity.md",
            render_observation_fidelity(comparison),
        ),
        "action_fidelity": (out_dir / "action_fidelity.md", render_action_fidelity(comparison)),
        "transition_fidelity": (
            out_dir / "transition_fidelity.md",
            render_transition_fidelity(comparison),
        ),
        "summary": (out_dir / "summary.md", render_summary(comparison)),
    }
    paths: dict[str, Path] = {}
    for stem, (path, content) in artifacts.items():
        path.write_text(content, encoding="utf-8")
        paths[stem] = path
    return paths
