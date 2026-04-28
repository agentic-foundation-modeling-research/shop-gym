"""End-to-end test for ``shop-probe run --axes A`` (T1.8 + T3.3 — spec §7 M1+M3 gates).

Drives the CLI against the localhost SandboxShop fixture and asserts the
emitted JSON validates as a closed :class:`ProbeReport`. Acceptance:

* every rubric leaf in ``rubric/v1.yaml`` produces a ``ProbeResult`` row;
* per-level + weighted coverage are computed per spec §5.3;
* the rubric version + content hash, runner version, and the pinned
  Playwright/Chromium runtime metadata are embedded in the report
  header per spec §5.6 + §5.8;
* the SandboxShop fixture is built to satisfy every probe in the M3
  rubric (core + modern), so ``coverage_weighted`` lands at 1.0 on a
  clean run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from shop_probe.cli import EXIT_OK, EXIT_USAGE, main
from shop_probe.report import ProbeReport
from shop_probe.rubric import load_rubric

# `tests/` is on sys.path via pytest's rootdir; `_sandbox.py` lives there.
_TESTS_ROOT = Path(__file__).resolve().parent
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _sandbox import SandboxShop  # noqa: E402 — sys.path adjustment above

_RUBRIC_V1_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "shop_probe"
    / "rubric"
    / "v1.yaml"
)


def test_cli_run_emits_valid_probe_report(tmp_path: Path) -> None:
    """Spec §7 M1 gate: ``shop-probe run --axes A`` against a localhost
    SandboxShop produces a valid :class:`ProbeReport`."""
    out_path = tmp_path / "report.json"
    evidence_dir = tmp_path / "evidence"
    with SandboxShop() as base_url:
        rc = main(
            [
                "run",
                base_url,
                "--label",
                "sandbox/fixture",
                "--rubric",
                "v1",
                "--axes",
                "A",
                "--kind",
                "sandbox",
                "--pair-id",
                "pair_fixture",
                "--out",
                str(out_path),
                "--evidence-dir",
                str(evidence_dir),
            ]
        )
    assert rc == EXIT_OK
    assert out_path.is_file()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)

    # Every rubric leaf produced one ProbeResult row.
    rubric = load_rubric(_RUBRIC_V1_PATH)
    assert {r.id for r in report.probe_results} == {e.id for e in rubric.entries}

    # Header carries the rubric version + content hash and runner metadata.
    assert report.rubric_version == rubric.version
    assert report.rubric_hash == rubric.content_hash
    assert report.runner_version  # populated, non-empty
    assert report.runtime.viewport == (1280, 800)
    assert report.runtime.headless is True
    assert "ShopProbe/" in report.runtime.user_agent
    assert report.runtime.chromium_version
    assert report.runtime.playwright_version

    # The fixture is built to pass every M3 core + modern probe.
    assert report.coverage_core == pytest.approx(1.0)
    assert report.coverage_modern == pytest.approx(1.0)
    assert report.coverage_weighted == pytest.approx(1.0)
    # No advanced probes ship in v1 (spec §5.3) — that slot stays at 0.0.
    assert report.coverage_advanced == 0.0

    # Per-category rollups cover the full v1 slice (11 categories).
    assert {c.category for c in report.categories} == {
        "site_shell",
        "homepage",
        "collection",
        "product",
        "search",
        "cart",
        "i18n",
        "floating",
        "dynamics",
        "a11y",
        "media",
    }
    for cat in report.categories:
        assert cat.weight_total > 0
        assert cat.coverage == pytest.approx(1.0)

    # Evidence trail landed under the requested directory.
    assert evidence_dir.is_dir()
    # At least one PNG screenshot per probe id under evidence root.
    captured = {p.parent.name for p in evidence_dir.rglob("*.png")}
    # Every rubric probe captured at least one screenshot.
    assert {e.id for e in rubric.entries}.issubset(captured)

    # Axis-A-only run leaves the axis-B surface field unset.
    assert report.surface is None


def test_cli_run_axes_a_b_populates_report_surface(tmp_path: Path) -> None:
    """Spec §7 M2 gate: ``shop-probe run --axes A,B`` populates ``report.surface``."""
    out_path = tmp_path / "report.json"
    evidence_dir = tmp_path / "evidence"
    with SandboxShop() as base_url:
        rc = main(
            [
                "run",
                base_url,
                "--label",
                "sandbox/fixture",
                "--rubric",
                "v1",
                "--axes",
                "A,B",
                "--kind",
                "sandbox",
                "--pair-id",
                "pair_fixture",
                "--out",
                str(out_path),
                "--evidence-dir",
                str(evidence_dir),
            ]
        )
    assert rc == EXIT_OK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)

    # Axis A still aggregates correctly under the combined run.
    assert report.coverage_core == pytest.approx(1.0)

    # Axis B — surface metrics populated; T2.3 gate: distinct_templates >= 3.
    assert report.surface is not None
    assert report.surface.distinct_templates >= 3  # noqa: PLR2004
    assert report.surface.routes_crawled > 0


def test_cli_run_rejects_unsupported_axes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """M2 wires axes A and A,B; axis C lands in M4."""
    rc = main(
        [
            "run",
            "http://localhost:0",
            "--label",
            "sandbox/fixture",
            "--axes",
            "A,B,C",
            "--kind",
            "sandbox",
            "--pair-id",
            "pair_fixture",
            "--out",
            str(tmp_path / "report.json"),
        ]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "not supported" in captured.err


def test_cli_run_rejects_inconsistent_kind_and_pair_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--kind sandbox`` without ``--pair-id`` violates the Target invariant."""
    rc = main(
        [
            "run",
            "http://localhost:0",
            "--label",
            "sandbox/fixture",
            "--kind",
            "sandbox",
            "--out",
            str(tmp_path / "report.json"),
        ]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "invalid target" in captured.err


def test_cli_run_rejects_missing_rubric(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown rubric names fail loudly before any browser launches."""
    rc = main(
        [
            "run",
            "http://localhost:0",
            "--label",
            "sandbox/fixture",
            "--rubric",
            "v999_missing",
            "--kind",
            "sandbox",
            "--pair-id",
            "pair_fixture",
            "--out",
            str(tmp_path / "report.json"),
        ]
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "v999_missing" in captured.err


_RUBRIC_V1_1_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "shop_probe"
    / "rubric"
    / "v1.1.yaml"
)


def test_cli_run_v1_1_default_skips_auth_and_transactional(tmp_path: Path) -> None:
    """T7.4: by default the v1.1 auth + transactional slice is filtered out."""
    out_path = tmp_path / "report.json"
    evidence_dir = tmp_path / "evidence"
    with SandboxShop() as base_url:
        rc = main(
            [
                "run",
                base_url,
                "--label",
                "sandbox/fixture",
                "--rubric",
                "v1.1",
                "--axes",
                "A",
                "--kind",
                "sandbox",
                "--pair-id",
                "pair_fixture",
                "--out",
                str(out_path),
                "--evidence-dir",
                str(evidence_dir),
            ]
        )
    assert rc == EXIT_OK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    rubric = load_rubric(_RUBRIC_V1_1_PATH)

    # Header pins v1.1 — we ran the v1.1 rubric, even though only the v1 slice fired.
    assert report.rubric_version == "v1.1"
    assert report.rubric_hash == rubric.content_hash

    # Only v1 entries (the 61 unflagged ones) produced ProbeResult rows.
    expected_ids = {e.id for e in rubric.entries if not (e.authenticated or e.transactional)}
    assert {r.id for r in report.probe_results} == expected_ids

    # No account.* / checkout.* entries are present in the report at all.
    fired = {c.category for c in report.categories}
    assert "account" not in fired
    assert "checkout" not in fired

    # The v1 slice still passes cleanly against the fixture.
    assert report.coverage_core == pytest.approx(1.0)
    assert report.coverage_modern == pytest.approx(1.0)
    assert report.coverage_weighted == pytest.approx(1.0)


def test_cli_run_v1_1_with_include_auth_runs_full_rubric(tmp_path: Path) -> None:
    """T7.4: ``--include-auth`` opts the v1.1 auth + transactional slice in."""
    out_path = tmp_path / "report.json"
    evidence_dir = tmp_path / "evidence"
    with SandboxShop() as base_url:
        rc = main(
            [
                "run",
                base_url,
                "--label",
                "sandbox/fixture",
                "--rubric",
                "v1.1",
                "--axes",
                "A",
                "--kind",
                "sandbox",
                "--pair-id",
                "pair_fixture",
                "--out",
                str(out_path),
                "--evidence-dir",
                str(evidence_dir),
                "--include-auth",
            ]
        )
    assert rc == EXIT_OK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    rubric = load_rubric(_RUBRIC_V1_1_PATH)

    # Every rubric entry produced a ProbeResult row, including the v1.1 slice.
    assert {r.id for r in report.probe_results} == {e.id for e in rubric.entries}
    fired = {c.category for c in report.categories}
    assert "account" in fired
    assert "checkout" in fired

    # Fixture serves the new auth + checkout pages, so the full v1.1 rubric passes.
    assert report.coverage_core == pytest.approx(1.0)
    assert report.coverage_weighted == pytest.approx(1.0)
