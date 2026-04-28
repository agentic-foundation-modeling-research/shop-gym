"""Tests for ``probes.collection.*`` against the localhost SandboxShop (T1.7)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import SAMPLE_COLLECTION_PATH, run_probe

from shop_probe.probes import collection


def test_has_product_cards_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        collection.has_product_cards,
        base_url=sandbox_url,
        probe_id="collection.listing.product_cards",
        evidence_root=tmp_path / "evidence",
        sample_collection_url=sandbox_url + SAMPLE_COLLECTION_PATH,
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_has_product_cards_skips_without_sample(tmp_path: Path, sandbox_url: str) -> None:
    """If the runner did not pre-resolve a sample collection URL, return ``None``."""
    outcome = run_probe(
        collection.has_product_cards,
        base_url=sandbox_url,
        probe_id="collection.listing.product_cards",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is None
    assert outcome.notes is not None
    assert "no sample_collection_url" in outcome.notes


def test_product_card_links_to_pdp_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        collection.product_card_links_to_pdp,
        base_url=sandbox_url,
        probe_id="collection.listing.product_card_links_to_pdp",
        evidence_root=tmp_path / "evidence",
        sample_collection_url=sandbox_url + SAMPLE_COLLECTION_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_has_filters_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        collection.has_filters,
        base_url=sandbox_url,
        probe_id="collection.listing.has_filters",
        evidence_root=tmp_path / "evidence",
        sample_collection_url=sandbox_url + SAMPLE_COLLECTION_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_has_sort_control_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        collection.has_sort_control,
        base_url=sandbox_url,
        probe_id="collection.listing.has_sort",
        evidence_root=tmp_path / "evidence",
        sample_collection_url=sandbox_url + SAMPLE_COLLECTION_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_has_pagination_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        collection.has_pagination_or_infinite_scroll,
        base_url=sandbox_url,
        probe_id="collection.pagination.present",
        evidence_root=tmp_path / "evidence",
        sample_collection_url=sandbox_url + SAMPLE_COLLECTION_PATH,
    )
    assert outcome.passed is True, outcome.notes
