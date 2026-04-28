"""Tests for ``probes.floating.*`` against the localhost SandboxShop (T3.3)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import run_probe

from shop_probe.probes import floating


def test_has_cookie_consent_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        floating.has_cookie_consent,
        base_url=sandbox_url,
        probe_id="floating.cookie_consent",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_has_newsletter_popup_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        floating.has_newsletter_popup,
        base_url=sandbox_url,
        probe_id="floating.newsletter_popup",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_has_chat_widget_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        floating.has_chat_widget,
        base_url=sandbox_url,
        probe_id="floating.chat_widget",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
