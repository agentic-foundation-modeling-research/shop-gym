"""Tests for ``probes.homepage.*`` against the localhost SandboxShop (T3.3)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import run_probe

from shop_probe.probes import homepage


def test_has_hero_section_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        homepage.has_hero_section,
        base_url=sandbox_url,
        probe_id="homepage.hero.present",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    # Spec §5.3: every probe emits screenshot + DOM snapshot evidence.
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_has_cta_to_collection_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        homepage.has_cta_to_collection,
        base_url=sandbox_url,
        probe_id="homepage.cta_to_collection",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_has_feature_grid_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        homepage.has_feature_grid,
        base_url=sandbox_url,
        probe_id="homepage.feature_grid",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_has_testimonial_section_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        homepage.has_testimonial_section,
        base_url=sandbox_url,
        probe_id="homepage.testimonials",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_multiple_section_types_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        homepage.multiple_section_types,
        base_url=sandbox_url,
        probe_id="homepage.multiple_section_types",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
