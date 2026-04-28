"""Tests for ``probes.site_shell.*`` against the localhost SandboxShop (T1.7)."""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import run_probe

from shop_probe.probes import site_shell


def test_header_is_sticky_passes_on_sticky_header(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        site_shell.header_is_sticky,
        base_url=sandbox_url,
        probe_id="site_shell.header.sticky",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    # Spec §5.3: every probe emits screenshot + DOM snapshot evidence.
    kinds = sorted(e.kind for e in outcome.evidence)
    assert kinds == ["dom_snapshot", "screenshot"]


def test_header_logo_links_home_passes_on_root_href(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        site_shell.header_logo_links_home,
        base_url=sandbox_url,
        probe_id="site_shell.header.logo_links_home",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_header_has_cart_link_passes_on_cart_link(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        site_shell.header_has_cart_link,
        base_url=sandbox_url,
        probe_id="site_shell.header.cart_link",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_nav_has_primary_collection_link_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        site_shell.nav_has_primary_collection_link,
        base_url=sandbox_url,
        probe_id="site_shell.nav.primary_collection_link",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes


def test_footer_has_link_group_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        site_shell.footer_has_link_group,
        base_url=sandbox_url,
        probe_id="site_shell.footer.link_group",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
