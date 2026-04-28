"""Tests for ``probes.cart.*`` against the localhost SandboxShop (T1.7)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import SAMPLE_PRODUCT_PATH, run_probe

from shop_probe.probes import cart


def test_page_renders_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        cart.page_renders,
        base_url=sandbox_url,
        probe_id="cart.page.renders",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_shows_added_line_item_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        cart.shows_added_line_item,
        base_url=sandbox_url,
        probe_id="cart.line_item.shows_after_add",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_shows_added_line_item_skips_without_sample(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        cart.shows_added_line_item,
        base_url=sandbox_url,
        probe_id="cart.line_item.shows_after_add",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is None
    assert outcome.notes is not None
    assert "no sample_product_url" in outcome.notes


def test_line_item_has_qty_editor_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        cart.line_item_has_qty_editor,
        base_url=sandbox_url,
        probe_id="cart.line_item.qty_editor",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_line_item_has_remove_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        cart.line_item_has_remove,
        base_url=sandbox_url,
        probe_id="cart.line_item.remove",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_empty_state_renders_passes_on_empty_cart(tmp_path: Path, sandbox_url: str) -> None:
    """An empty cart (fresh fixture) renders an empty-state message."""
    outcome = run_probe(
        cart.empty_state_renders,
        base_url=sandbox_url,
        probe_id="cart.empty_state.present",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_promo_code_input_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        cart.promo_code_input,
        base_url=sandbox_url,
        probe_id="cart.promo_code",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
