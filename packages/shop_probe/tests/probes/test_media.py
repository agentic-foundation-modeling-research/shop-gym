"""Tests for ``probes.media.*`` against the localhost SandboxShop (T3.3)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import SAMPLE_PRODUCT_PATH, run_probe

from shop_probe.probes import media


def test_lazy_loaded_images_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        media.lazy_loaded_images,
        base_url=sandbox_url,
        probe_id="media.lazy_load_images",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_responsive_srcset_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        media.responsive_srcset,
        base_url=sandbox_url,
        probe_id="media.responsive_srcset",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_lightbox_or_zoom_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        media.lightbox_or_zoom,
        base_url=sandbox_url,
        probe_id="media.lightbox_or_zoom",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes


def test_lightbox_or_zoom_skips_without_sample(tmp_path: Path, sandbox_url: str) -> None:
    """Without a sample PDP URL the probe is not_applicable."""
    outcome = run_probe(
        media.lightbox_or_zoom,
        base_url=sandbox_url,
        probe_id="media.lightbox_or_zoom",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is None
    assert outcome.notes is not None
    assert "no sample_product_url" in outcome.notes


def test_swatch_image_swap_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        media.swatch_image_swap,
        base_url=sandbox_url,
        probe_id="media.swatch_image_swap",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes
