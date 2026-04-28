"""Tests for ``probes.search.*`` against the localhost SandboxShop (T3.3)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import run_probe

from shop_probe.probes import search


def test_header_has_search_trigger_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        search.header_has_search_trigger,
        base_url=sandbox_url,
        probe_id="search.header.trigger",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_results_page_renders_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        search.results_page_renders,
        base_url=sandbox_url,
        probe_id="search.results_page.renders",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_results_page_echoes_query_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        search.results_page_echoes_query,
        base_url=sandbox_url,
        probe_id="search.query_echo",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_no_results_state_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        search.no_results_state,
        base_url=sandbox_url,
        probe_id="search.no_results_state",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_predictive_listbox_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        search.predictive_listbox_present,
        base_url=sandbox_url,
        probe_id="search.predictive_listbox",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
