"""Unit tests for the SC5 coverage gate (T4.4).

Covers ``shop_explore.coverage`` end-to-end on synthetic prefetch and
``plan.md`` inputs. The module is the deterministic check the M4
live-fixture run (T4.5) plugs into to verify success criterion SC5
("On the fixture set, every coverage-taxonomy area that prefetch
evidence indicates is present appears as either a planner task or a
justified omission"); these tests prove the check itself is correct
before applying it to recorded fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

from shop_explore.coverage import (
    coverage_gaps,
    evidenced_areas,
    parse_plan_coverage,
)

# --------------------------------------------------------------------------- #
# Fixture builders
# --------------------------------------------------------------------------- #


def _seed_full_prefetch(prefetch_dir: Path) -> None:
    """Lay out a prefetch tree that evidences every checkable area."""
    prefetch_dir.mkdir(parents=True, exist_ok=True)
    (prefetch_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (prefetch_dir / "cart.js").write_text(json.dumps({"items": []}), encoding="utf-8")
    (prefetch_dir / "search_suggest.json").write_text(
        json.dumps({"resources": {}}), encoding="utf-8"
    )
    (prefetch_dir / "search.html").write_text("<html>search</html>", encoding="utf-8")
    (prefetch_dir / "products.json").write_text(
        json.dumps({"products": [{"id": 1, "title": "A"}]}), encoding="utf-8"
    )
    (prefetch_dir / "collections.json").write_text(
        json.dumps({"collections": [{"id": 100}]}), encoding="utf-8"
    )
    (prefetch_dir / "pages").mkdir()
    (prefetch_dir / "policies").mkdir()
    for relative in (
        "pages/about.html",
        "pages/contact.html",
        "pages/faq.html",
        "policies/shipping-policy.html",
        "policies/refund-policy.html",
        "policies/privacy-policy.html",
        "policies/terms-of-service.html",
    ):
        (prefetch_dir / relative).write_text("<html></html>", encoding="utf-8")


_FULL_AREAS: frozenset[str] = frozenset(
    {
        "homepage_sections",
        "header_navigation",
        "footer",
        "cart",
        "search_predictive",
        "search_results",
        "product_detail",
        "collection",
        "info_about",
        "info_contact",
        "info_faq",
        "info_shipping",
        "info_returns",
        "info_privacy",
        "info_tos",
    }
)


# --------------------------------------------------------------------------- #
# evidenced_areas
# --------------------------------------------------------------------------- #


def test_evidenced_areas_returns_empty_set_when_prefetch_dir_missing(tmp_path: Path) -> None:
    """Missing prefetch dir returns the empty set rather than raising."""
    assert evidenced_areas(tmp_path / "absent") == set()


def test_evidenced_areas_full_storefront_evidences_every_checkable_area(
    tmp_path: Path,
) -> None:
    """A complete prefetch tree evidences every area defined in ``_AREAS``."""
    prefetch = tmp_path / "prefetch"
    _seed_full_prefetch(prefetch)
    assert evidenced_areas(prefetch) == _FULL_AREAS


def test_evidenced_areas_homepage_only(tmp_path: Path) -> None:
    """A storefront with only ``/`` saved evidences the three homepage-shell areas."""
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    (prefetch / "index.html").write_text("<!doctype html>", encoding="utf-8")
    assert evidenced_areas(prefetch) == {"homepage_sections", "header_navigation", "footer"}


def test_evidenced_areas_empty_products_json_does_not_evidence_product_detail(
    tmp_path: Path,
) -> None:
    """``products.json`` with ``[]`` is not enough evidence — no PDPs to verify."""
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    (prefetch / "products.json").write_text(json.dumps({"products": []}), encoding="utf-8")
    assert evidenced_areas(prefetch) == set()


def test_evidenced_areas_malformed_products_json_is_silently_ignored(
    tmp_path: Path,
) -> None:
    """Malformed JSON does not raise — treat as no evidence."""
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    (prefetch / "products.json").write_text("not json", encoding="utf-8")
    (prefetch / "collections.json").write_text("[]", encoding="utf-8")  # not a dict
    assert evidenced_areas(prefetch) == set()


def test_evidenced_areas_cart_html_alone_is_sufficient(tmp_path: Path) -> None:
    """Either ``cart.js`` or ``cart.html`` evidences the cart area."""
    prefetch = tmp_path / "prefetch"
    prefetch.mkdir()
    (prefetch / "cart.html").write_text("<html>cart</html>", encoding="utf-8")
    assert "cart" in evidenced_areas(prefetch)


# --------------------------------------------------------------------------- #
# parse_plan_coverage
# --------------------------------------------------------------------------- #


def test_parse_plan_coverage_extracts_task_ids_and_omitted_slugs() -> None:
    """Mixed-status task lines and omitted-area entries are normalised to slug sets."""
    plan_md = """\
# Plan

## Tasks

- [ ] homepage_sections — capture sections [priority: 8]
- [x] cart_drawer — done [priority: 7]
- [!] search_predictive — blocked [priority: 6]

## Omitted Areas

- mega_menu — header is single-row only.
- age_gate - storefront is not age-restricted.
- chat_widget
"""
    task_ids, omitted = parse_plan_coverage(plan_md)
    assert task_ids == {"homepage_sections", "cart_drawer", "search_predictive"}
    assert omitted == {"mega_menu", "age_gate", "chat_widget"}


def test_parse_plan_coverage_ignores_lines_outside_named_sections() -> None:
    """Bullets under unrelated headings must not leak into task / omitted sets."""
    plan_md = """\
# Plan

## Browse Notes

- [ ] not_a_task — narrative bullet [priority: 1]

## Tasks

- [ ] real_task — actual task [priority: 5]

## Open Questions

- some_dangling — should be ignored.
"""
    task_ids, omitted = parse_plan_coverage(plan_md)
    assert task_ids == {"real_task"}
    assert omitted == set()


def test_parse_plan_coverage_handles_empty_input() -> None:
    """Empty ``plan.md`` (e.g. before the planner ran) returns empty sets."""
    assert parse_plan_coverage("") == (set(), set())


# --------------------------------------------------------------------------- #
# coverage_gaps — happy paths
# --------------------------------------------------------------------------- #


def _seed_full_run_dir(
    tmp_path: Path,
    *,
    plan_md: str,
) -> Path:
    """Build a ``run_dir`` with a full-coverage prefetch tree + the given plan."""
    run_dir = tmp_path / "domain" / "run"
    _seed_full_prefetch(run_dir / "artifact" / "prefetch")
    (run_dir / "plan.md").write_text(plan_md, encoding="utf-8")
    return run_dir


def test_coverage_gaps_empty_when_every_area_is_a_task_or_omission(
    tmp_path: Path,
) -> None:
    """A plan that addresses every evidenced area passes SC5."""
    plan_md = """\
# Plan

## Tasks

- [ ] homepage_sections — sections [priority: 8]
- [ ] header_navigation — nav [priority: 7]
- [ ] footer — footer columns [priority: 3]
- [ ] cart_drawer — cart [priority: 7]
- [ ] search_predictive — predictive [priority: 6]
- [ ] search_results — results page [priority: 4]
- [ ] product_variants — PDPs [priority: 5]
- [ ] collection_filters — filters [priority: 6]
- [ ] info_pages — info pages [priority: 3]

## Omitted Areas

- (none)
"""
    run_dir = _seed_full_run_dir(tmp_path, plan_md=plan_md)
    assert coverage_gaps(run_dir) == []


def test_coverage_gaps_accepts_canonical_area_names_in_omitted_areas(
    tmp_path: Path,
) -> None:
    """Listing the canonical area name under ``## Omitted Areas`` covers the gap."""
    plan_md = """\
# Plan

## Tasks

- [ ] homepage_sections — sections [priority: 8]
- [ ] header_navigation — nav [priority: 7]
- [ ] footer — footer [priority: 3]
- [ ] cart_drawer — cart [priority: 7]
- [ ] search_predictive — predictive [priority: 6]
- [ ] product_variants — PDPs [priority: 5]
- [ ] collection_filters — filters [priority: 6]

## Omitted Areas

- search_results — only predictive panel exposed; results page is identical layout.
- info_pages — none of the policy URLs distinguish this shop.
"""
    run_dir = _seed_full_run_dir(tmp_path, plan_md=plan_md)
    assert coverage_gaps(run_dir) == []


def test_coverage_gaps_accepts_taxonomy_aliases_in_omitted_areas(
    tmp_path: Path,
) -> None:
    """Spec §5.3 taxonomy labels (``predictive``, ``about``, …) cover their leaf areas."""
    plan_md = """\
# Plan

## Tasks

- [ ] homepage_sections — sections [priority: 8]
- [ ] header_navigation — nav [priority: 7]
- [ ] footer — footer [priority: 3]
- [ ] cart_drawer — cart [priority: 7]
- [ ] product_variants — PDPs [priority: 5]
- [ ] collection_filters — filters [priority: 6]

## Omitted Areas

- predictive — search has no autocomplete on this storefront.
- search — full-page search results are not distinct from the predictive panel.
- about — page is auto-generated boilerplate.
- contact — contact info is footer-only.
- faq — no FAQ page on this shop.
- shipping_policy — boilerplate policy.
- returns_policy — boilerplate policy.
- privacy_policy — boilerplate policy.
- terms_of_service — boilerplate policy.
"""
    run_dir = _seed_full_run_dir(tmp_path, plan_md=plan_md)
    assert coverage_gaps(run_dir) == []


def test_coverage_gaps_homepage_sections_task_covers_header_and_footer(
    tmp_path: Path,
) -> None:
    """``homepage_sections`` is allowed to subsume ``header_navigation`` + ``footer``.

    Some shops fold these into a single homepage pass; the planner
    prompt allows it. Coverage must accept that arrangement.
    """
    prefetch = tmp_path / "run" / "artifact" / "prefetch"
    prefetch.mkdir(parents=True)
    (prefetch / "index.html").write_text("<!doctype html>", encoding="utf-8")
    plan_md = """\
# Plan

## Tasks

- [ ] homepage_sections — sections + header + footer [priority: 8]

## Omitted Areas

- (none)
"""
    (tmp_path / "run" / "plan.md").write_text(plan_md, encoding="utf-8")
    assert coverage_gaps(tmp_path / "run") == []


# --------------------------------------------------------------------------- #
# coverage_gaps — failure paths
# --------------------------------------------------------------------------- #


def test_coverage_gaps_reports_areas_with_neither_task_nor_omission(
    tmp_path: Path,
) -> None:
    """A plan that ignores evidenced info pages reports them as gaps."""
    plan_md = """\
# Plan

## Tasks

- [ ] homepage_sections — sections [priority: 8]
- [ ] header_navigation — nav [priority: 7]
- [ ] footer — footer [priority: 3]
- [ ] cart_drawer — cart [priority: 7]
- [ ] search_predictive — predictive [priority: 6]
- [ ] search_results — results [priority: 4]
- [ ] product_variants — PDPs [priority: 5]
- [ ] collection_filters — filters [priority: 6]

## Omitted Areas

- (none)
"""
    run_dir = _seed_full_run_dir(tmp_path, plan_md=plan_md)
    gaps = coverage_gaps(run_dir)
    assert gaps == sorted(
        [
            "info_about",
            "info_contact",
            "info_faq",
            "info_privacy",
            "info_returns",
            "info_shipping",
            "info_tos",
        ]
    )


def test_coverage_gaps_returns_empty_when_no_evidence(tmp_path: Path) -> None:
    """No prefetch evidence ⇒ no gaps even when ``plan.md`` is missing.

    SC5 talks about "areas prefetch evidence indicates are present"; if
    nothing is evidenced, nothing is required of the plan.
    """
    run_dir = tmp_path / "domain" / "run"
    (run_dir / "artifact" / "prefetch").mkdir(parents=True)
    # No plan.md, no prefetch files.
    assert coverage_gaps(run_dir) == []


def test_coverage_gaps_reports_every_evidenced_area_when_plan_is_missing(
    tmp_path: Path,
) -> None:
    """Full-evidence prefetch + missing ``plan.md`` ⇒ every evidenced area is a gap."""
    run_dir = tmp_path / "domain" / "run"
    _seed_full_prefetch(run_dir / "artifact" / "prefetch")
    # Intentionally no plan.md.
    assert set(coverage_gaps(run_dir)) == _FULL_AREAS
