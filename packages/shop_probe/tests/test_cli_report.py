"""End-to-end test for ``shop-probe report`` (T6.5 — spec §7 M6 gate).

Drives the CLI against synthetic, on-disk :class:`ProbeReport` fixtures
and asserts every paper figure renders without manual editing:

* the per-pair fidelity table (T6.1);
* the per-category coverage radar (T6.2);
* the per-metric surface bar chart (T6.3);
* the pairwise-judge Turing chart (T6.4) when axis-C calls are present.

This is the spec §7 M6 gate: figures 1-4 reproduce from versioned
``cohort/`` reports without manual editing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shop_probe.cli import EXIT_OK, EXIT_USAGE, main
from shop_probe.report import (
    BrowserMeta,
    CategoryScore,
    JudgeCall,
    JudgeModelPin,
    ProbeReport,
)
from shop_probe.surface import SurfaceMetrics
from shop_probe.targets import Target

# --------------------------------------------------------------------------- #
# Fixture builders.
# --------------------------------------------------------------------------- #

_RUBRIC_HASH: str = "a" * 64
_PROMPT_HASH: str = "b" * 64
_TIMESTAMP: datetime = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
_CATEGORY_NAMES: tuple[str, ...] = ("cart", "product", "site_shell")


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.1 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _judge_model() -> JudgeModelPin:
    return JudgeModelPin(
        provider="openai",
        model="gpt-5",
        model_version="gpt-5-2025-09-01",
        temperature=0.0,
    )


def _surface(**overrides: float) -> SurfaceMetrics:
    base: dict[str, float] = {
        "distinct_templates": 5,
        "routes_crawled": 50,
        "interactables_per_template_median": 30.0,
        "interactables_per_template_p95": 90.0,
        "forms_total": 4,
        "form_fields_total": 20,
        "catalog_products": 100,
        "catalog_collections": 12,
        "catalog_variants": 250,
        "filter_x_sort_state_space": 64,
        "median_dom_kb_gz": 80.0,
        "accessibility_nodes_per_template_median": 400.0,
    }
    base.update(overrides)
    return SurfaceMetrics.model_validate(base)


def _categories(coverages: dict[str, float]) -> tuple[CategoryScore, ...]:
    return tuple(
        CategoryScore(
            category=name,
            weight_passed=cov * 10.0,
            weight_total=10.0,
            coverage=cov,
        )
        for name, cov in coverages.items()
    )


def _report(
    *,
    label: str,
    kind: str,
    pair_id: str | None,
    coverages: dict[str, float],
    surface: SurfaceMetrics,
    judge_calls: tuple[JudgeCall, ...] = (),
) -> ProbeReport:
    target = Target(
        label=label,
        base_url="http://localhost:4000",
        kind=kind,  # type: ignore[arg-type]
        pair_id=pair_id,
    )
    weighted = sum(coverages.values()) / max(len(coverages), 1)
    return ProbeReport(
        target=target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=_TIMESTAMP,
        probe_results=(),
        categories=_categories(coverages),
        coverage_core=weighted,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=weighted,
        surface=surface,
        judge_calls=judge_calls,
        judge_model=_judge_model() if judge_calls else None,
        rerun_index=1,
        flake_rate_per_probe={},
    )


def _judge_call(*, pick: str, truth: str) -> JudgeCall:
    return JudgeCall(
        task_id="task_01",
        pair_label=("A_traj", "B_traj"),
        judge_pick=pick,  # type: ignore[arg-type]
        truth=truth,  # type: ignore[arg-type]
        swap_consistent=True,
        evidence_cited=True,
        confidence=0.9,
        prompt_hash=_PROMPT_HASH,
        response_text="ok",
    )


def _judge_calls(*, n_correct: int, n_wrong: int) -> tuple[JudgeCall, ...]:
    return (
        *(_judge_call(pick="A", truth="A") for _ in range(n_correct)),
        *(_judge_call(pick="A", truth="B") for _ in range(n_wrong)),
    )


def _label_to_path(reports_dir: Path, label: str) -> Path:
    return reports_dir / f"{label.replace('/', '__')}.json"


def _write_report(reports_dir: Path, report: ProbeReport) -> Path:
    path = _label_to_path(reports_dir, report.target.label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def _write_minimal_cohort(
    cohort_path: Path,
    *,
    pair_ids: tuple[str, ...] = ("pair_hardware", "pair_hexclad"),
    real_labels: tuple[str, ...] = ("real/r1", "real/r2"),
) -> None:
    """Write a small but spec-shaped cohort YAML the CLI can load."""
    pair_blocks: list[str] = []
    for pid in pair_ids:
        pair_blocks.append(
            f"  - id: {pid}\n"
            f"    source:\n"
            f"      label: source/{pid}\n"
            f"      base_url: https://{pid}.example\n"
            f"      kind: source\n"
            f"      pair_id: {pid}\n"
            f"    sandbox:\n"
            f"      label: sandbox/{pid}\n"
            f"      base_url: https://sandbox-{pid}.example\n"
            f"      kind: sandbox\n"
            f"      pair_id: {pid}\n"
        )
    real_blocks: list[str] = []
    for label in real_labels:
        real_blocks.append(
            f"  - label: {label}\n"
            f"    base_url: https://{label.replace('/', '-')}.example\n"
            f"    kind: real_unpaired\n"
        )
    cohort_path.write_text(
        'version: "0.1"\n'
        "pairs:\n" + "".join(pair_blocks) + "real_unpaired:\n" + "".join(real_blocks),
        encoding="utf-8",
    )


def _seed_axis_a_b_cohort(reports_dir: Path) -> None:
    """Write one ProbeReport per cohort target (axis A + B, no axis C)."""
    coverages_high = {"cart": 0.9, "product": 0.85, "site_shell": 0.95}
    coverages_low = {"cart": 0.7, "product": 0.65, "site_shell": 0.8}
    coverages_real_a = {"cart": 0.95, "product": 0.9, "site_shell": 0.98}
    coverages_real_b = {"cart": 0.85, "product": 0.8, "site_shell": 0.9}

    _write_report(
        reports_dir,
        _report(
            label="source/pair_hardware",
            kind="source",
            pair_id="pair_hardware",
            coverages=coverages_high,
            surface=_surface(distinct_templates=8, catalog_products=200),
        ),
    )
    _write_report(
        reports_dir,
        _report(
            label="sandbox/pair_hardware",
            kind="sandbox",
            pair_id="pair_hardware",
            coverages=coverages_low,
            surface=_surface(distinct_templates=4, catalog_products=80),
        ),
    )
    _write_report(
        reports_dir,
        _report(
            label="source/pair_hexclad",
            kind="source",
            pair_id="pair_hexclad",
            coverages=coverages_high,
            surface=_surface(distinct_templates=7, catalog_products=180),
        ),
    )
    _write_report(
        reports_dir,
        _report(
            label="sandbox/pair_hexclad",
            kind="sandbox",
            pair_id="pair_hexclad",
            coverages=coverages_low,
            surface=_surface(distinct_templates=5, catalog_products=90),
        ),
    )
    _write_report(
        reports_dir,
        _report(
            label="real/r1",
            kind="real_unpaired",
            pair_id=None,
            coverages=coverages_real_a,
            surface=_surface(distinct_templates=9, catalog_products=300),
        ),
    )
    _write_report(
        reports_dir,
        _report(
            label="real/r2",
            kind="real_unpaired",
            pair_id=None,
            coverages=coverages_real_b,
            surface=_surface(distinct_templates=6, catalog_products=150),
        ),
    )


# --------------------------------------------------------------------------- #
# Happy paths.
# --------------------------------------------------------------------------- #


def test_report_renders_axis_a_and_b_figures_without_manual_editing(tmp_path: Path) -> None:
    """Spec §7 M6 gate: figures 1-3 (A + B) emit from versioned reports."""
    cohort_path = tmp_path / "cohort.yaml"
    _write_minimal_cohort(cohort_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    _seed_axis_a_b_cohort(reports_dir)
    out_dir = tmp_path / "figures"

    rc = main(
        [
            "report",
            "--cohort",
            str(cohort_path),
            "--reports-dir",
            str(reports_dir),
            "--out",
            str(out_dir),
        ]
    )
    assert rc == EXIT_OK

    # T6.1 — fidelity table.
    table = (out_dir / "fidelity_table.md").read_text(encoding="utf-8")
    assert "| Pair |" in table
    assert "pair_hardware" in table
    assert "pair_hexclad" in table
    assert "intra-real control" in table

    # T6.2 — radar SVG.
    radar = (out_dir / "radar.svg").read_text(encoding="utf-8")
    assert radar.startswith("<svg ")
    assert radar.endswith("</svg>\n")
    # Sandboxes overlay; one polygon per sandbox plus the legend swatch.
    assert radar.count('class="sandbox"') >= 2  # noqa: PLR2004

    # T6.3 — surface SVG.
    surface = (out_dir / "surface.svg").read_text(encoding="utf-8")
    assert surface.startswith("<svg ")
    assert surface.endswith("</svg>\n")
    # One row per SurfaceMetrics field.
    assert surface.count('class="row"') == len(SurfaceMetrics.model_fields)

    # Axis-C (T6.4) skipped when judge_calls absent.
    assert not (out_dir / "turing.svg").exists()


def test_report_renders_turing_chart_when_judge_calls_present(tmp_path: Path) -> None:
    """T6.4 wired: axis-C judge calls on every sandbox + real_unpaired report
    populate the Turing chart."""
    cohort_path = tmp_path / "cohort.yaml"
    _write_minimal_cohort(cohort_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    _seed_axis_a_b_cohort(reports_dir)

    # Layer judge calls onto every sandbox + real_unpaired report.
    sandbox_calls = _judge_calls(n_correct=8, n_wrong=2)
    control_calls = _judge_calls(n_correct=5, n_wrong=5)
    for label in (
        "sandbox/pair_hardware",
        "sandbox/pair_hexclad",
    ):
        path = _label_to_path(reports_dir, label)
        report = ProbeReport.model_validate_json(path.read_text(encoding="utf-8"))
        _write_report(
            reports_dir,
            report.model_copy(
                update={
                    "judge_calls": sandbox_calls,
                    "judge_model": _judge_model(),
                }
            ),
        )
    for label in ("real/r1", "real/r2"):
        path = _label_to_path(reports_dir, label)
        report = ProbeReport.model_validate_json(path.read_text(encoding="utf-8"))
        _write_report(
            reports_dir,
            report.model_copy(
                update={
                    "judge_calls": control_calls,
                    "judge_model": _judge_model(),
                }
            ),
        )

    out_dir = tmp_path / "figures"
    rc = main(
        [
            "report",
            "--cohort",
            str(cohort_path),
            "--reports-dir",
            str(reports_dir),
            "--out",
            str(out_dir),
            "--bootstrap-iters",
            "100",
        ]
    )
    assert rc == EXIT_OK
    turing = (out_dir / "turing.svg").read_text(encoding="utf-8")
    assert turing.startswith("<svg ")
    assert turing.endswith("</svg>\n")
    # Two pair rows + one cohort-level intra-real control row.
    assert turing.count('class="row"') == 3  # noqa: PLR2004
    assert "intra-real control" in turing


def test_report_output_is_deterministic_across_runs(tmp_path: Path) -> None:
    """The four artifacts are byte-stable across repeated runs (T6.1-T6.4)."""
    cohort_path = tmp_path / "cohort.yaml"
    _write_minimal_cohort(cohort_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    _seed_axis_a_b_cohort(reports_dir)

    out_a = tmp_path / "figures_a"
    out_b = tmp_path / "figures_b"
    for out in (out_a, out_b):
        rc = main(
            [
                "report",
                "--cohort",
                str(cohort_path),
                "--reports-dir",
                str(reports_dir),
                "--out",
                str(out),
            ]
        )
        assert rc == EXIT_OK

    for filename in ("fidelity_table.md", "radar.svg", "surface.svg"):
        assert (out_a / filename).read_bytes() == (out_b / filename).read_bytes()


# --------------------------------------------------------------------------- #
# Failure paths.
# --------------------------------------------------------------------------- #


def test_report_rejects_missing_cohort_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "report",
            "--cohort",
            str(tmp_path / "no_such.yaml"),
            "--reports-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "figures"),
        ]
    )
    assert rc == EXIT_USAGE
    assert "cohort" in capsys.readouterr().err.lower()


def test_report_rejects_missing_report_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A cohort target without a matching JSON file fails with a clear error."""
    cohort_path = tmp_path / "cohort.yaml"
    _write_minimal_cohort(cohort_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    # Seed only one of the six expected reports.
    _write_report(
        reports_dir,
        _report(
            label="source/pair_hardware",
            kind="source",
            pair_id="pair_hardware",
            coverages={"cart": 0.9, "product": 0.85, "site_shell": 0.95},
            surface=_surface(),
        ),
    )

    rc = main(
        [
            "report",
            "--cohort",
            str(cohort_path),
            "--reports-dir",
            str(reports_dir),
            "--out",
            str(tmp_path / "figures"),
        ]
    )
    assert rc == EXIT_USAGE
    assert "missing report for target" in capsys.readouterr().err
