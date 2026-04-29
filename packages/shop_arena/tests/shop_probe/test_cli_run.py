"""End-to-end test for ``shop-probe run`` (web_probe_patch.md).

Drives the CLI against the localhost SandboxShop fixture and asserts the
emitted JSON validates as a closed :class:`ProbeReport`.
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
    Path(__file__).resolve().parent.parent.parent / "src" / "shop_probe" / "rubric" / "v1.yaml"
)
_RUBRIC_V1_1_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "src" / "shop_probe" / "rubric" / "v1.1.yaml"
)


def _run_args(base_url: str, tmp_path: Path, *, axes: str = "A", rubric: str = "v1") -> list[str]:
    return [
        "run",
        base_url,
        "--name",
        "fixture",
        "--label",
        "sandbox",
        "--rubric",
        rubric,
        "--axes",
        axes,
        "--out",
        str(tmp_path),
    ]


def test_cli_run_emits_valid_probe_report(tmp_path: Path) -> None:
    """``shop-probe run --axes A`` against a localhost SandboxShop produces a valid ProbeReport."""
    out_path = tmp_path / "reports" / "sandbox__fixture__rerun1.json"
    evidence_dir = tmp_path / "evidence" / "sandbox__fixture__rerun1"
    with SandboxShop() as base_url:
        rc = main(_run_args(base_url, tmp_path))
    assert rc == EXIT_OK
    assert out_path.is_file()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)

    rubric = load_rubric(_RUBRIC_V1_PATH)
    assert {r.id for r in report.probe_results} == {e.id for e in rubric.entries}

    assert report.rubric_version == rubric.version
    assert report.rubric_hash == rubric.content_hash
    assert report.runner_version
    assert report.runtime.viewport == (1280, 800)
    assert report.runtime.headless is True
    assert "ShopProbe/" in report.runtime.user_agent
    assert report.runtime.chromium_version
    assert report.runtime.playwright_version

    assert report.target.name == "fixture"
    assert report.target.label == "sandbox"

    assert report.coverage_core == pytest.approx(1.0)
    assert report.coverage_modern == pytest.approx(1.0)
    assert report.coverage_weighted == pytest.approx(1.0)
    assert report.coverage_advanced == 0.0

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

    assert evidence_dir.is_dir()
    captured = {p.parent.name for p in evidence_dir.rglob("*.png")}
    assert {e.id for e in rubric.entries}.issubset(captured)

    assert report.surface is None


def test_cli_run_axes_a_b_populates_report_surface(tmp_path: Path) -> None:
    """``shop-probe run --axes A,B`` populates ``report.surface``."""
    out_path = tmp_path / "reports" / "sandbox__fixture__rerun1.json"
    with SandboxShop() as base_url:
        rc = main(_run_args(base_url, tmp_path, axes="A,B"))
    assert rc == EXIT_OK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)

    assert report.coverage_core == pytest.approx(1.0)

    assert report.surface is not None
    assert report.surface.distinct_templates >= 3  # noqa: PLR2004
    assert report.surface.routes_crawled > 0


def test_cli_run_rejects_unsupported_axes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(_run_args("http://localhost:0", tmp_path, axes="A,B,C"))
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "not supported" in captured.err


def test_cli_run_rejects_invalid_label(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "run",
            "http://localhost:0",
            "--name",
            "fixture",
            "--label",
            "source",  # not in {sandbox, real}
            "--out",
            str(tmp_path),
        ]
    )
    # argparse-level rejection produces a SystemExit-style error code.
    assert rc != EXIT_OK
    _ = capsys.readouterr()


def test_cli_run_rejects_missing_rubric(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(_run_args("http://localhost:0", tmp_path, rubric="v999_missing"))
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert "v999_missing" in captured.err


def test_cli_run_v1_1_default_skips_auth_and_transactional(tmp_path: Path) -> None:
    """T7.4: by default the v1.1 auth + transactional slice is filtered out."""
    out_path = tmp_path / "reports" / "sandbox__fixture__rerun1.json"
    with SandboxShop() as base_url:
        rc = main(_run_args(base_url, tmp_path, rubric="v1.1"))
    assert rc == EXIT_OK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    rubric = load_rubric(_RUBRIC_V1_1_PATH)

    assert report.rubric_version == "v1.1"
    assert report.rubric_hash == rubric.content_hash

    expected_ids = {e.id for e in rubric.entries if not (e.authenticated or e.transactional)}
    assert {r.id for r in report.probe_results} == expected_ids

    fired = {c.category for c in report.categories}
    assert "account" not in fired
    assert "checkout" not in fired

    assert report.coverage_core == pytest.approx(1.0)
    assert report.coverage_modern == pytest.approx(1.0)
    assert report.coverage_weighted == pytest.approx(1.0)


def test_cli_run_v1_1_with_include_auth_runs_full_rubric(tmp_path: Path) -> None:
    """T7.4: ``--include-auth`` opts the v1.1 auth + transactional slice in."""
    out_path = tmp_path / "reports" / "sandbox__fixture__rerun1.json"
    with SandboxShop() as base_url:
        rc = main([*_run_args(base_url, tmp_path, rubric="v1.1"), "--include-auth"])
    assert rc == EXIT_OK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = ProbeReport.model_validate(payload)
    rubric = load_rubric(_RUBRIC_V1_1_PATH)

    assert {r.id for r in report.probe_results} == {e.id for e in rubric.entries}
    fired = {c.category for c in report.categories}
    assert "account" in fired
    assert "checkout" in fired

    assert report.coverage_core == pytest.approx(1.0)
    assert report.coverage_weighted == pytest.approx(1.0)
