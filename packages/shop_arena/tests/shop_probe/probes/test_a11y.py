"""Tests for ``probes.a11y.*`` against the localhost SandboxShop (T3.3)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import run_probe

from shop_probe.probes import a11y


def test_skip_to_content_link_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        a11y.skip_to_content_link,
        base_url=sandbox_url,
        probe_id="a11y.skip_to_content",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_combobox_role_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        a11y.combobox_role_present,
        base_url=sandbox_url,
        probe_id="a11y.combobox_role",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_dialog_role_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        a11y.dialog_role_present,
        base_url=sandbox_url,
        probe_id="a11y.dialog_role",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_live_region_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        a11y.live_region_present,
        base_url=sandbox_url,
        probe_id="a11y.live_region",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_alt_text_coverage_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        a11y.alt_text_coverage,
        base_url=sandbox_url,
        probe_id="a11y.alt_text_coverage",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_focus_visible_style_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        a11y.focus_visible_style,
        base_url=sandbox_url,
        probe_id="a11y.focus_visible",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
