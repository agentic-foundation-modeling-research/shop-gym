"""End-to-end tests for ``shop-probe aggregate-reruns`` (T5.2 — spec §5.8).

Drives the CLI over synthetic ``ProbeReport`` JSON files (no Playwright
required) so the rerun aggregation contract is exercised independently
of the live storefront wiring still pending two ``TBD`` sandbox URLs in
``cohort.yaml``. Coverage:

* Clean rerun group → consolidated report has every probe at flake = 0;
* one disagreement across N=3 → flake = 1/3 surfaces in the output;
* ``--gate`` returns :data:`EXIT_USAGE` when any probe exceeds the gate;
* malformed inputs (missing file, bad JSON, mismatched targets) fail
  loudly before any work happens.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shop_probe.cli import EXIT_OK, EXIT_USAGE, main
from shop_probe.report import BrowserMeta, ProbeReport, ProbeResult
from shop_probe.targets import Target

_TARGET: Target = Target(
    label="sandbox/1",
    base_url="http://localhost:4000",
    kind="sandbox",
    pair_id="pair_1",
)
_RUBRIC_HASH: str = "a" * 64


def _browser_meta() -> BrowserMeta:
    return BrowserMeta(
        python_version="3.11.9",
        playwright_version="1.48.0",
        chromium_version="129.0.6668.58",
        user_agent="ShopProbe/0.0 (Chromium/129)",
        viewport=(1280, 800),
        headless=True,
    )


def _write_report(
    path: Path,
    *,
    rerun_index: int,
    results: tuple[ProbeResult, ...],
) -> None:
    report = ProbeReport(
        target=_TARGET,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=datetime(2026, 1, 15, 12, rerun_index, 0, tzinfo=UTC),
        probe_results=results,
        coverage_core=1.0,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=1.0,
        rerun_index=rerun_index,
    )
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _result(probe_id: str, *, passed: bool | None) -> ProbeResult:
    return ProbeResult(id=probe_id, passed=passed, duration_ms=10)


def test_aggregate_reruns_clean_group_writes_consolidated_report(
    tmp_path: Path,
) -> None:
    """Three runs that fully agree → flake_rate = 0 for every probe."""
    runs = []
    for i in (1, 2, 3):
        path = tmp_path / f"run{i}.json"
        _write_report(
            path,
            rerun_index=i,
            results=(
                _result("a.b", passed=True),
                _result("c.d", passed=False),
            ),
        )
        runs.append(path)
    out_path = tmp_path / "reports" / "sandbox__1.json"

    rc = main(
        [
            "aggregate-reruns",
            "--runs",
            *(str(p) for p in runs),
            "--out",
            str(tmp_path),
            "--gate",
            "0.01",
        ]
    )

    assert rc == EXIT_OK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    assert report.flake_rate_per_probe == {"a.b": 0.0, "c.d": 0.0}
    assert report.rerun_index == 1


def test_aggregate_reruns_one_disagreement_surfaces_third_flake(
    tmp_path: Path,
) -> None:
    """One True/False flip across N=3 runs → flake = 1/3 stamped on output."""
    paths = []
    for i, passed in ((1, True), (2, True), (3, False)):
        path = tmp_path / f"run{i}.json"
        _write_report(path, rerun_index=i, results=(_result("a.b", passed=passed),))
        paths.append(path)
    out_path = tmp_path / "reports" / "sandbox__1.json"

    rc = main(
        [
            "aggregate-reruns",
            "--runs",
            *(str(p) for p in paths),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == EXIT_OK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    assert report.flake_rate_per_probe["a.b"] == pytest.approx(1.0 / 3.0)


def test_aggregate_reruns_gate_violation_returns_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A flake at 1/3 exceeds the spec §5.8 default 1% gate → exit USAGE."""
    paths = []
    for i, passed in ((1, True), (2, True), (3, False)):
        path = tmp_path / f"run{i}.json"
        _write_report(path, rerun_index=i, results=(_result("a.b", passed=passed),))
        paths.append(path)
    out_path = tmp_path / "reports" / "sandbox__1.json"

    rc = main(
        [
            "aggregate-reruns",
            "--runs",
            *(str(p) for p in paths),
            "--out",
            str(tmp_path),
            "--gate",
            "0.01",
        ]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "exceeded flake gate" in captured.err
    assert "a.b" in captured.err
    # Even on gate violation the consolidated report is written so the
    # operator can inspect which probes flaked.
    assert out_path.is_file()


def test_aggregate_reruns_requires_at_least_two_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "run1.json"
    _write_report(path, rerun_index=1, results=(_result("a.b", passed=True),))
    rc = main(
        [
            "aggregate-reruns",
            "--runs",
            str(path),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "at least two" in captured.err


def test_aggregate_reruns_missing_input_file_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    valid = tmp_path / "run1.json"
    _write_report(valid, rerun_index=1, results=(_result("a.b", passed=True),))
    missing = tmp_path / "run_does_not_exist.json"
    rc = main(
        [
            "aggregate-reruns",
            "--runs",
            str(valid),
            str(missing),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "rerun report not found" in captured.err
    assert str(missing) in captured.err


def test_aggregate_reruns_invalid_json_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    valid = tmp_path / "run1.json"
    _write_report(valid, rerun_index=1, results=(_result("a.b", passed=True),))
    bogus = tmp_path / "bogus.json"
    bogus.write_text("{not json}", encoding="utf-8")
    rc = main(
        [
            "aggregate-reruns",
            "--runs",
            str(valid),
            str(bogus),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "invalid rerun report" in captured.err


def test_aggregate_reruns_mismatched_targets_fail_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reports for two different targets cannot form a coherent rerun group."""
    run1 = tmp_path / "run1.json"
    _write_report(run1, rerun_index=1, results=(_result("a.b", passed=True),))

    other = tmp_path / "run2.json"
    other_target = Target(
        label="sandbox/2",
        base_url="http://localhost:4001",
        kind="sandbox",
        pair_id="pair_2",
    )
    other_report = ProbeReport(
        target=other_target,
        rubric_version="v1",
        rubric_hash=_RUBRIC_HASH,
        runner_version="0.0.0",
        runtime=_browser_meta(),
        timestamp=datetime(2026, 1, 15, 12, 2, 0, tzinfo=UTC),
        probe_results=(_result("a.b", passed=True),),
        coverage_core=1.0,
        coverage_modern=0.0,
        coverage_advanced=0.0,
        coverage_weighted=1.0,
        rerun_index=2,
    )
    other.write_text(other_report.model_dump_json(indent=2), encoding="utf-8")

    rc = main(
        [
            "aggregate-reruns",
            "--runs",
            str(run1),
            str(other),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "rerun group mismatch" in captured.err
