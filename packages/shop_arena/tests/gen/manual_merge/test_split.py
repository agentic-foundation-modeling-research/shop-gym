"""Unit tests for :mod:`shop_arena.gen.manual_merge.split`.

Covers the spec contract from ``docs/specs/shop_arena/manual_split.md``:

* :func:`split_manual_into_parts` slices a merged manual into six
  per-area sub-manuals via the canonical routing map.
* Sub-manual files emit deterministic order and contain the routed H2
  sections in canonical order.
* A merged manual missing every required structural section raises
  :class:`ValueError` so a regressed merge is caught loudly.
* :class:`SplitManualPartsStep` reads ``manual/manual.md`` and writes
  ``manual/parts/<area>.md`` for each canonical sub-manual.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.manual_merge.split import (
    SplitManualPartsStep,
    split_manual_into_parts,
)
from shop_arena.gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _manual(sections: dict[str, str], *, descriptor: str = "Premium Storefront") -> str:
    """Render a merged-manual body with H1 + named H2 sections."""
    pieces = [f"# Shop Manual — {descriptor}", ""]
    for name, body in sections.items():
        pieces.append(f"## {name}")
        pieces.append("")
        pieces.append(body.rstrip())
        pieces.append("")
    return "\n".join(pieces).rstrip() + "\n"


def _h2_names(body: str) -> list[str]:
    """Return every ``## <name>`` heading in ``body`` in document order."""
    return [match.group(1).strip() for match in re.finditer(r"^##\s+(.+)$", body, re.MULTILINE)]


def _build_ctx(out_dir: Path) -> StepContext:
    """Build a :class:`StepContext` rooted at ``out_dir`` for the step run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    seed_dir = out_dir.parent / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    cfg = ShopGenConfig(seeds=[seed_dir], out_dir=out_dir)
    return StepContext(config=cfg, out_dir=out_dir, runtime=None)


_PART_NAMES: Final[tuple[str, ...]] = (
    "homepage",
    "navigation",
    "product",
    "collections",
    "cart_and_search",
    "info_pages",
)


_FULL_SECTIONS: Final[dict[str, str]] = {
    "Overview": "A focused, brand-anonymized storefront.",
    "Site shell": "Sticky header with three-deep mega menu.",
    "Homepage": "Hero, featured collections, editorial blocks.",
    "Collections & navigation": "Two-rail sidebar with filters.",
    "Product page": "Variant pickers, sticky add-to-cart.",
    "Cart": "Right-side drawer with promo input.",
    "Search": "Predictive search modal with categories.",
    "Internationalization": "Currency switcher in the header.",
    "Floating UX": "Newsletter overlay and chat widget.",
    "Policy & info pages": "Returns, shipping, and FAQ pages.",
    "UX Patterns Summary": "Reusable patterns across the storefront.",
}


# --------------------------------------------------------------------------- #
# split_manual_into_parts — happy path
# --------------------------------------------------------------------------- #


def test_split_emits_every_canonical_part() -> None:
    """All six sub-manual names are present, in deterministic order."""
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    assert tuple(bodies.keys()) == _PART_NAMES


def test_split_routes_homepage_section_to_homepage_part() -> None:
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    homepage = bodies["homepage"]
    assert homepage.startswith("# Sub-Manual — Homepage\n")
    assert "Hero, featured collections" in homepage
    # Floating UX is also routed to homepage per the spec.
    assert "Newsletter overlay" in homepage


def test_split_routes_site_shell_and_i18n_to_navigation() -> None:
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    nav = bodies["navigation"]
    assert nav.startswith("# Sub-Manual — Navigation\n")
    assert "Sticky header" in nav
    assert "Currency switcher" in nav


def test_split_routes_collections_section_to_collections_part() -> None:
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    collections = bodies["collections"]
    assert collections.startswith("# Sub-Manual — Collections\n")
    assert "Two-rail sidebar" in collections


def test_split_routes_product_page_to_product_part() -> None:
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    product = bodies["product"]
    assert product.startswith("# Sub-Manual — Product\n")
    assert "Variant pickers" in product


def test_split_routes_cart_and_search_into_one_part() -> None:
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    cart_and_search = bodies["cart_and_search"]
    assert cart_and_search.startswith("# Sub-Manual — Cart & Search\n")
    assert "Right-side drawer" in cart_and_search
    assert "Predictive search modal" in cart_and_search
    # Cart precedes Search per the canonical ordering.
    cart_idx = cart_and_search.index("Right-side drawer")
    search_idx = cart_and_search.index("Predictive search modal")
    assert cart_idx < search_idx


def test_split_routes_policy_section_to_info_pages_part() -> None:
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    info_pages = bodies["info_pages"]
    assert info_pages.startswith("# Sub-Manual — Info Pages\n")
    assert "Returns, shipping" in info_pages


def test_split_overview_and_summary_stay_in_full_manual_only() -> None:
    """Overview / UX Patterns Summary do not appear in any sub-manual."""
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    for body in bodies.values():
        assert "## Overview" not in body
        assert "## UX Patterns Summary" not in body


def test_split_sub_manuals_carry_h2_in_canonical_order() -> None:
    """When a part receives 2+ sections they are emitted in canonical order."""
    bodies = split_manual_into_parts(_manual(_FULL_SECTIONS))
    # navigation carries Site shell + Internationalization, in that canonical order.
    assert _h2_names(bodies["navigation"]) == ["Site shell", "Internationalization"]
    # homepage carries Homepage + Floating UX.
    assert _h2_names(bodies["homepage"]) == ["Homepage", "Floating UX"]
    # cart_and_search carries Cart then Search.
    assert _h2_names(bodies["cart_and_search"]) == ["Cart", "Search"]


def test_split_empty_part_receives_placeholder() -> None:
    """A part with no routed content emits the empty-body placeholder."""
    # Drop every section that routes to ``info_pages``.
    sections = {k: v for k, v in _FULL_SECTIONS.items() if k != "Policy & info pages"}
    bodies = split_manual_into_parts(_manual(sections))
    info_pages = bodies["info_pages"]
    assert info_pages.startswith("# Sub-Manual — Info Pages\n")
    assert "no sections from the merged manual route" in info_pages


# --------------------------------------------------------------------------- #
# split_manual_into_parts — validation
# --------------------------------------------------------------------------- #


def test_split_raises_when_no_required_sections_present() -> None:
    """A merged manual missing every required structural section is rejected."""
    bare = _manual(
        {
            "Overview": "Trivial overview only.",
            "UX Patterns Summary": "No structural sections present.",
        },
    )
    with pytest.raises(ValueError, match="required structural section"):
        split_manual_into_parts(bare)


def test_split_passes_when_only_one_required_section_is_present() -> None:
    """Spec contract: at least *one* of the required sections is enough."""
    body = _manual({"Homepage": "Hero only."})
    bodies = split_manual_into_parts(body)
    # ``homepage`` carries the routed body; every other part falls back
    # to the placeholder but is still emitted.
    assert "Hero only." in bodies["homepage"]
    assert tuple(bodies.keys()) == _PART_NAMES


def test_split_unknown_h2_section_is_ignored_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unrecognized sections route nowhere but do not raise."""
    sections = dict(_FULL_SECTIONS)
    sections["Loyalty Programs"] = "Off-canonical extra."
    with caplog.at_level("WARNING", logger="shop_arena.gen.manual_merge.split"):
        bodies = split_manual_into_parts(_manual(sections))
    assert any("Loyalty Programs" in record.getMessage() for record in caplog.records)
    for body in bodies.values():
        assert "Off-canonical extra." not in body


# --------------------------------------------------------------------------- #
# SplitManualPartsStep — disk integration
# --------------------------------------------------------------------------- #


def test_step_metadata_matches_contract() -> None:
    """Step id / phase / inputs / outputs match the spec contract."""
    step = SplitManualPartsStep(upstream_step_id="merge_manual_prose")
    assert step.id == "split_manual_parts"
    assert step.phase == "manual_merge"
    assert step.depends_on == ["merge_manual_prose"]
    assert [path.name for path in step.outputs] == [f"{name}.md" for name in _PART_NAMES]


def test_step_run_writes_each_sub_manual(tmp_path: Path) -> None:
    """``run()`` writes one file per canonical sub-manual under ``manual/parts/``."""
    out_dir = tmp_path / "out"
    (out_dir / "manual").mkdir(parents=True)
    (out_dir / "manual" / "manual.md").write_text(_manual(_FULL_SECTIONS), encoding="utf-8")

    step = SplitManualPartsStep(upstream_step_id="merge_manual_prose")
    step.run(_build_ctx(out_dir))

    parts_dir = out_dir / "manual" / "parts"
    for name in _PART_NAMES:
        target = parts_dir / f"{name}.md"
        assert target.is_file(), name
        assert target.read_text(encoding="utf-8").startswith("# Sub-Manual —"), name


def test_step_run_raises_when_manual_missing(tmp_path: Path) -> None:
    """A missing ``manual/manual.md`` is a wiring bug — fail fast."""
    step = SplitManualPartsStep(upstream_step_id="merge_manual_prose")
    with pytest.raises(FileNotFoundError, match="merged manual not found"):
        step.run(_build_ctx(tmp_path / "out"))


def test_step_run_supports_single_seed_upstream(tmp_path: Path) -> None:
    """Single-seed runs declare ``copy_seed_manual`` as the upstream step."""
    step = SplitManualPartsStep(upstream_step_id="copy_seed_manual")
    assert step.depends_on == ["copy_seed_manual"]
