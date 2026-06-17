"""Unit tests for ``cart_surface_conformance`` build verifier."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from harness.verifiers import Verdict, VerifierContext
from shop_arena.gen.build.verifiers.cart_surface_conformance import (
    CartSurfaceConformanceVerifier,
)

_MANUAL_NO_DRAWER = """\
# Sub-Manual — Cart & Search

## Cart

The shop ships two cart surfaces: a small header mini-cart popover and a
server-rendered full-page `/cart` view. There is no slide-in side drawer or
full-screen modal.
"""

_MANUAL_ALLOWS_DRAWER = """\
# Sub-Manual — Cart & Search

## Cart

The shop uses a slide-in cart drawer with quantity controls and checkout
actions.
"""

_PAGE_WITH_CART_ASIDE = """\
import {Aside} from '~/components/Aside';

export function PageLayout() {
  return <Aside type="cart" heading="CART"><p>Cart</p></Aside>;
}

function CartAside() {
  return null;
}
"""

_HEADER_OPEN_CART = """\
import {useAside} from '~/components/Aside';

export function Header() {
  const {open} = useAside();
  return <button onClick={() => open('cart')}>Cart</button>;
}
"""

_HEADER_POPOVER = """\
export function Header() {
  return (
    <div className="header-cart">
      <a href="/cart">Cart</a>
      <div className="header-cart-popover" role="dialog" aria-label="Cart preview" />
    </div>
  );
}
"""


def _write_manual(artifact_dir: Path, body: str) -> Path:
    """Write the cart/search manual slice into the fixture artifact."""
    path = artifact_dir / "parts" / "cart_and_search.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_name_and_applicability() -> None:
    verifier = CartSurfaceConformanceVerifier()

    assert verifier.name == "cart_surface_conformance"
    assert verifier.applies_to("gen_cart_search") is True
    assert verifier.applies_to("visual_fix") is True
    assert verifier.applies_to("gen_product") is False


def test_passes_when_manual_does_not_forbid_drawer(
    artifact_dir: Path,
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write_manual(artifact_dir, _MANUAL_ALLOWS_DRAWER)
    write_app_file("components/PageLayout.tsx", _PAGE_WITH_CART_ASIDE)

    result = CartSurfaceConformanceVerifier().run(
        make_ctx(selected_task_id="gen_cart_search"),
    )

    assert result.verdict is Verdict.PASS
    assert result.details["manual_forbids_drawer"] is False


def test_passes_when_no_drawer_manual_has_only_header_popover(
    artifact_dir: Path,
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write_manual(artifact_dir, _MANUAL_NO_DRAWER)
    write_app_file("components/Header.tsx", _HEADER_POPOVER)

    result = CartSurfaceConformanceVerifier().run(
        make_ctx(selected_task_id="gen_cart_search"),
    )

    assert result.verdict is Verdict.PASS
    assert result.details["manual_forbids_drawer"] is True
    assert result.details["findings"] == []


def test_fails_when_no_drawer_manual_keeps_cart_aside(
    artifact_dir: Path,
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write_manual(artifact_dir, _MANUAL_NO_DRAWER)
    write_app_file("components/PageLayout.tsx", _PAGE_WITH_CART_ASIDE)

    result = CartSurfaceConformanceVerifier().run(
        make_ctx(selected_task_id="gen_cart_search"),
    )

    assert result.verdict is Verdict.FAIL
    assert result.details["manual_forbids_drawer"] is True
    assert "cart_aside_component" in result.details["triggered_rule_ids"]
    assert "cart_aside_mount" in result.details["triggered_rule_ids"]
    assert "no slide-in cart drawer/modal" in result.feedback


def test_fails_when_no_drawer_manual_opens_cart_aside_from_header(
    artifact_dir: Path,
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    _write_manual(artifact_dir, _MANUAL_NO_DRAWER)
    write_app_file("components/Header.tsx", _HEADER_OPEN_CART)

    result = CartSurfaceConformanceVerifier().run(
        make_ctx(selected_task_id="visual_fix"),
    )

    assert result.verdict is Verdict.FAIL
    assert result.details["triggered_rule_ids"] == ["open_cart_aside"]
    assert "open('cart')" in result.feedback


def test_falls_back_to_full_manual(
    artifact_dir: Path,
    make_ctx: Callable[..., VerifierContext],
    write_app_file: Callable[[str, str], Path],
) -> None:
    (artifact_dir / "manual.md").write_text(_MANUAL_NO_DRAWER, encoding="utf-8")
    write_app_file("components/Header.tsx", _HEADER_OPEN_CART)

    result = CartSurfaceConformanceVerifier().run(
        make_ctx(selected_task_id="gen_cart_search"),
    )

    assert result.verdict is Verdict.FAIL
    assert result.details["manual_path"].endswith("manual.md")


def test_fails_when_manual_is_missing(
    make_ctx: Callable[..., VerifierContext],
) -> None:
    result = CartSurfaceConformanceVerifier().run(
        make_ctx(selected_task_id="gen_cart_search"),
    )

    assert result.verdict is Verdict.FAIL
    assert result.details["manual_found"] is False
