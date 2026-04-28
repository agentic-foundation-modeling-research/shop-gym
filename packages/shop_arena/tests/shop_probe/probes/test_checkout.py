"""Tests for ``probes.checkout.*`` against the localhost SandboxShop (T7.4).

Asserts the v1.1 ``transactional: true`` probes pass against the fixture's
``/cart`` checkout CTA and ``/checkout`` route, and that
:func:`flow_initiates` returns ``passed=None`` (not_applicable) when the
runner cannot pre-resolve a sample PDP URL (matches the cart line-item
probes' contract).
"""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import SAMPLE_PRODUCT_PATH, run_probe

from shop_probe.probes import checkout
from shop_probe.probes.checkout import _is_checkout_surface


def test_flow_initiates_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        checkout.flow_initiates,
        base_url=sandbox_url,
        probe_id="checkout.flow.initiates",
        evidence_root=tmp_path / "evidence",
        sample_product_url=sandbox_url + SAMPLE_PRODUCT_PATH,
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_flow_initiates_skips_without_sample(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        checkout.flow_initiates,
        base_url=sandbox_url,
        probe_id="checkout.flow.initiates",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is None
    assert outcome.notes is not None
    assert "no sample_product_url" in outcome.notes


def test_page_renders_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        checkout.page_renders,
        base_url=sandbox_url,
        probe_id="checkout.page.renders",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_is_checkout_surface_recognizes_same_origin_path() -> None:
    assert _is_checkout_surface("http://example.com/checkout", "http://example.com")
    assert _is_checkout_surface("http://example.com/checkouts/abc123", "http://example.com")


def test_is_checkout_surface_recognizes_checkout_subdomain() -> None:
    """Real Shopify storefronts redirect to ``checkout.shopify.com``."""
    assert _is_checkout_surface("https://checkout.shopify.com/abc", "https://example.com")


def test_is_checkout_surface_rejects_unrelated_url() -> None:
    assert not _is_checkout_surface("http://example.com/cart", "http://example.com")
    assert not _is_checkout_surface("http://other-merchant.com/checkout", "http://example.com")
