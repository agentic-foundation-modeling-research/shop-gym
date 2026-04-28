"""Tests for ``probes.dynamics.*`` against the localhost SandboxShop (T3.3)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import SAMPLE_COLLECTION_PATH, run_probe

from shop_probe.probes import dynamics


def test_has_toast_region_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        dynamics.has_toast_region,
        base_url=sandbox_url,
        probe_id="dynamics.toast_region",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_url_state_sync_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        dynamics.url_state_sync_present,
        base_url=sandbox_url,
        probe_id="dynamics.url_state_sync",
        evidence_root=tmp_path / "evidence",
        sample_collection_url=sandbox_url + SAMPLE_COLLECTION_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_url_state_sync_skips_without_sample(tmp_path: Path, sandbox_url: str) -> None:
    """Without a sample collection URL the probe is not_applicable."""
    outcome = run_probe(
        dynamics.url_state_sync_present,
        base_url=sandbox_url,
        probe_id="dynamics.url_state_sync",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is None
    assert outcome.notes is not None
    assert "no sample_collection_url" in outcome.notes


def test_debounced_input_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        dynamics.debounced_input_present,
        base_url=sandbox_url,
        probe_id="dynamics.debounced_input",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_ajax_cart_endpoint_discoverable_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        dynamics.ajax_cart_endpoint_discoverable,
        base_url=sandbox_url,
        probe_id="dynamics.ajax_cart_endpoint",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_cart_count_badge_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        dynamics.cart_count_badge_present,
        base_url=sandbox_url,
        probe_id="dynamics.cart_count_badge",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
