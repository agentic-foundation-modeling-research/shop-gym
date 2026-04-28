"""Tests for ``probes.i18n.*`` against the localhost SandboxShop (T3.3)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import run_probe

from shop_probe.probes import i18n


def test_has_locale_switcher_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        i18n.has_locale_switcher,
        base_url=sandbox_url,
        probe_id="i18n.locale_switcher",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_has_currency_switcher_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        i18n.has_currency_switcher,
        base_url=sandbox_url,
        probe_id="i18n.currency_switcher",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_has_country_list_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        i18n.has_country_list,
        base_url=sandbox_url,
        probe_id="i18n.country_list",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
