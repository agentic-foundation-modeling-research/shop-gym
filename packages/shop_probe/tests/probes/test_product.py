"""Tests for ``probes.product.*`` against the localhost SandboxShop (T1.7)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import SAMPLE_PRODUCT_PATH, run_probe

from shop_probe.probes import product


def test_gallery_has_image_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        product.gallery_has_image,
        base_url=sandbox_url,
        probe_id="product.gallery.image",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_gallery_has_image_skips_without_sample(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        product.gallery_has_image,
        base_url=sandbox_url,
        probe_id="product.gallery.image",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is None
    assert outcome.notes is not None
    assert "no sample_product_url" in outcome.notes


def test_has_title_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        product.has_title,
        base_url=sandbox_url,
        probe_id="product.title.present",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_has_price_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        product.has_price,
        base_url=sandbox_url,
        probe_id="product.price.present",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_has_add_to_cart_button_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        product.has_add_to_cart_button,
        base_url=sandbox_url,
        probe_id="product.add_to_cart.button",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_has_description_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        product.has_description,
        base_url=sandbox_url,
        probe_id="product.description.present",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes
