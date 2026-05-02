"""Unit tests for :mod:`shop_guru.validate`."""
from __future__ import annotations

from typing import Any

from shop_guru.config import Shop
from shop_guru.validate import has_errors, validate_tasks


def _data() -> dict[str, Any]:
    """Shop fixture with two collections so the ``known_dim_names`` index
    captures both ``Color`` (Hats collection) and ``Size`` (Shoes
    collection). This lets us assert error vs. warning behavior for dim
    names the shop *does* know (Size on Hats → error) vs. ones it doesn't
    (e.g. localized labels → warning).
    """
    return {
        "collections": [
            {
                "id": 1,
                "title": "Hats",
                "handle": "hats",
                "product_handles": ["red-hat"],
            },
            {
                "id": 2,
                "title": "Shoes",
                "handle": "shoes",
                "product_handles": ["blue-shoe"],
            },
        ],
        "products": [
            {
                "id": 1,
                "title": "Red Hat",
                "handle": "red-hat",
                "product_type": "Hats",
                "vendor": "WoolCo",
                "options": [{"name": "Color", "values": ["Red"]}],
                "variants": [{"title": "Default", "available": True}],
            },
            {
                "id": 2,
                "title": "Blue Shoe",
                "handle": "blue-shoe",
                "product_type": "Shoes",
                "vendor": "FootCo",
                "options": [{"name": "Size", "values": ["M", "L"]}],
                "variants": [{"title": "Default", "available": True}],
            },
        ],
        "pages": [{"handle": "shipping-info", "title": "Shipping Info"}],
    }


def _make_task(**overrides: Any) -> dict:
    base: dict[str, Any] = {
        "id": "tiny-exact-1",
        "type": "shopping",
        "intent": "Find the product named Red Hat and select any variant to add to cart.",
        "success_criteria": {"url_contains": "/products/red-hat", "type": "product_search"},
    }
    base.update(overrides)
    return base


def test_validate_clean_task_emits_no_issues(tiny_shop: Shop) -> None:
    issues = validate_tasks([_make_task()], tiny_shop, _data())
    assert issues == []


def test_validate_unknown_collection_is_error(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-browse-1",
        success_criteria={"url_contains": "/collections/does-not-exist", "type": "navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert any(i.rule == "unknown-collection" and i.severity == "error" for i in issues)
    assert has_errors(issues)


def test_validate_unknown_product_is_error(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-exact-2",
        success_criteria={"url_contains": "/products/unicorn", "type": "product_search"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert any(i.rule == "unknown-product" and i.severity == "error" for i in issues)


def test_validate_unknown_page_is_warning(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-shipping-1",
        success_criteria={"url_contains": "/pages/never-published", "type": "page_navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert any(i.rule == "unknown-page" and i.severity == "warning" for i in issues)
    assert not has_errors(issues)


def test_validate_filter_feasibility_pass(tiny_shop: Shop) -> None:
    """A filter task whose (dim, value) is realizable in the collection."""
    task = _make_task(
        id="tiny-filter-1",
        intent=(
            'Navigate to the "Hats" collection on this store. Find and use '
            "the Color filter (e.g. Red) to select an option. If products are "
            "shown after filtering, select any variant of a product and add it "
            "to cart."
        ),
        success_criteria={"url_contains": "/collections/hats", "type": "navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert issues == []


def test_validate_filter_feasibility_dim_missing_is_error(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-filter-1",
        intent=(
            'Navigate to the "Hats" collection on this store. Find and use '
            "the Size filter (e.g. M) to select an option."
        ),
        success_criteria={"url_contains": "/collections/hats", "type": "navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert any(i.rule == "infeasible-filter" and i.severity == "error" for i in issues)


def test_validate_filter_feasibility_value_missing_is_error(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-filter-1",
        intent=(
            'Navigate to the "Hats" collection on this store. Find and use '
            "the Color filter (e.g. Magenta) to select an option."
        ),
        success_criteria={"url_contains": "/collections/hats", "type": "navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert any(i.rule == "infeasible-filter" and i.severity == "error" for i in issues)


def test_validate_filter_feasibility_brand_alias_resolves(tiny_shop: Shop) -> None:
    """`Brand` in the intent should map to the product `vendor` field for
    the feasibility check (mirrors collection_filter's display alias).
    """
    task = _make_task(
        id="tiny-filter-1",
        intent=(
            'Navigate to the "Hats" collection on this store. Find and use '
            "the Brand filter (e.g. WoolCo) to select an option."
        ),
        success_criteria={"url_contains": "/collections/hats", "type": "navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert issues == []


def test_validate_intent_answer_leak_email(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-e2e-14",
        intent="Open Contact Us. Note the email (info@shop.example) and report it back.",
        success_criteria={
            "url_contains": "/products/red-hat",
            "type": "cart_after_contact_detour",
            "response_contains": ["info@shop.example", "504 S 11th St"],
        },
    )
    issues = validate_tasks([task], tiny_shop, _data())
    leaks = [i for i in issues if i.rule == "intent-answer-leak"]
    assert len(leaks) == 1
    assert "info@shop.example" in leaks[0].message
    assert has_errors(issues)


def test_validate_intent_answer_leak_string_form(tiny_shop: Shop) -> None:
    """`response_contains` may be a single string rather than a list."""
    task = _make_task(
        id="tiny-e2e-1",
        intent="Visit Contact Us and the address 504 S 11th St shows up there.",
        success_criteria={
            "url_contains": "/products/red-hat",
            "type": "cart_after_contact_detour",
            "response_contains": "504 S 11th St",
        },
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert any(i.rule == "intent-answer-leak" for i in issues)


def test_validate_intent_answer_leak_no_leak(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-e2e-1",
        intent="Visit Contact Us and report the address back at the end of the session.",
        success_criteria={
            "url_contains": "/products/red-hat",
            "type": "cart_after_contact_detour",
            "response_contains": ["504 S 11th St"],
        },
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert all(i.rule != "intent-answer-leak" for i in issues)


def test_validate_handles_missing_url_contains_gracefully(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-other-1",
        success_criteria={"type": "page_navigation"},
    )
    # No url_contains shouldn't blow up; just no issues from url-rules.
    issues = validate_tasks([task], tiny_shop, _data())
    assert all(i.rule not in {"unknown-collection", "unknown-product"} for i in issues)


def test_validate_filter_intent_malformed_is_warning(tiny_shop: Shop) -> None:
    task = _make_task(
        id="tiny-filter-1",
        intent="Navigate to the Hats collection and click around.",
        success_criteria={"url_contains": "/collections/hats", "type": "navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert any(i.rule == "filter-intent-malformed" and i.severity == "warning" for i in issues)
    assert not has_errors(issues)


def test_validate_url_contains_supports_handle_prefix(tiny_shop: Shop) -> None:
    """``url_contains`` is a substring match at runtime, so a benchmark with
    a partial handle (``/products/whole-geode``) should validate against a
    catalog that contains the full handle (``whole-geode-compact``).
    """
    data = _data()
    data["products"].append(
        {
            "id": 9,
            "title": "Whole Geode Compact",
            "handle": "whole-geode-compact",
            "product_type": "Curiosities",
            "vendor": "Geo",
            "options": [],
            "variants": [{"title": "Default", "available": True}],
        }
    )
    task = _make_task(
        id="tiny-e2e-99",
        success_criteria={"url_contains": "/products/whole-geode", "type": "product_search"},
    )
    issues = validate_tasks([task], tiny_shop, data)
    assert all(i.rule != "unknown-product" for i in issues)


def test_validate_filter_localized_dim_is_warning_not_error(tiny_shop: Shop) -> None:
    """Storefronts may render localized labels (e.g. a Lithuanian shop using
    ``Produkto tipas`` for product_type). The validator can't always tell
    such a label from a typo, so it must downgrade unknown dims to a
    warning rather than raise a hard error.
    """
    task = _make_task(
        id="tiny-filter-1",
        intent=(
            'Navigate to the "Hats" collection on this store. Find and use '
            "the Produkto tipas filter (e.g. Hats) to select an option."
        ),
        success_criteria={"url_contains": "/collections/hats", "type": "navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert any(i.rule == "filter-dim-unknown" and i.severity == "warning" for i in issues)
    assert not has_errors(issues)


def test_validate_filter_known_dim_still_errors(tiny_shop: Shop) -> None:
    """A dim the validator *does* know (Color) but with a value the
    collection lacks must remain an error; the warning downgrade only
    applies to genuinely unknown dim names.
    """
    task = _make_task(
        id="tiny-filter-1",
        intent=(
            'Navigate to the "Hats" collection on this store. Find and use '
            "the Color filter (e.g. Magenta) to select an option."
        ),
        success_criteria={"url_contains": "/collections/hats", "type": "navigation"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    errors = [i for i in issues if i.rule == "infeasible-filter"]
    assert len(errors) == 1
    assert errors[0].severity == "error"


# ---------------------------------------------------------------------------
# single-sku-value-selection
# ---------------------------------------------------------------------------


def test_validate_single_sku_select_for_color_is_warning(tiny_shop: Shop) -> None:
    """An intent that asks the agent to ``select Red for the Color option``
    on a product with Color=['Red'] only should emit a warning. The PDP
    has no list to pick from."""
    task = _make_task(
        id="tiny-e2e-1",
        intent=(
            "Open the Red Hat product page and select Red for the Color option, "
            "then add it to your cart."
        ),
        success_criteria={"url_contains": "/products/red-hat", "type": "product_search"},
    )
    data = _data()
    data["products"][0]["options"] = [{"name": "Color", "values": ["Red"]}]
    issues = validate_tasks([task], tiny_shop, data)
    flagged = [i for i in issues if i.rule == "single-sku-value-selection"]
    assert len(flagged) == 1
    assert flagged[0].severity == "warning"
    assert "'Red'" in flagged[0].message
    assert "single-SKU" in flagged[0].message
    assert not has_errors(issues)


def test_validate_single_sku_select_color_variant_is_warning(tiny_shop: Shop) -> None:
    """The shorter ``select the Red Color variant`` phrasing also matches."""
    task = _make_task(
        id="tiny-e2e-2",
        intent="Open the Red Hat product page and select the Red Color variant.",
        success_criteria={"url_contains": "/products/red-hat", "type": "product_search"},
    )
    data = _data()
    data["products"][0]["options"] = [{"name": "Color", "values": ["Red"]}]
    issues = validate_tasks([task], tiny_shop, data)
    assert any(i.rule == "single-sku-value-selection" for i in issues)


def test_validate_single_sku_does_not_flag_multi_value(tiny_shop: Shop) -> None:
    """Selecting a value on a multi-value PDP is fine — the rule only
    fires on single-SKU options."""
    task = _make_task(
        id="tiny-e2e-3",
        intent=(
            "Open the Blue Shoe product page and select M for the Size option, "
            "then add it to your cart."
        ),
        success_criteria={"url_contains": "/products/blue-shoe", "type": "product_search"},
    )
    issues = validate_tasks([task], tiny_shop, _data())
    assert all(i.rule != "single-sku-value-selection" for i in issues)


def test_validate_single_sku_does_not_flag_confirm_wording(tiny_shop: Shop) -> None:
    """The recommended fix wording — ``confirm Red for Color`` and
    ``is offered in Red`` — must not trigger the warning."""
    task = _make_task(
        id="tiny-e2e-4",
        intent=(
            "Open the Red Hat product page (it is offered in Red), confirm "
            "Red for Color, and add it to your cart."
        ),
        success_criteria={"url_contains": "/products/red-hat", "type": "product_search"},
    )
    data = _data()
    data["products"][0]["options"] = [{"name": "Color", "values": ["Red"]}]
    issues = validate_tasks([task], tiny_shop, data)
    assert all(i.rule != "single-sku-value-selection" for i in issues)


def test_validate_single_sku_skips_when_product_not_mentioned(tiny_shop: Shop) -> None:
    """No product title in intent -> no rule fires (we don't know which
    PDP the agent is on)."""
    task = _make_task(
        id="tiny-e2e-5",
        intent="Browse the Hats collection and select Red for the Color option.",
        success_criteria={"url_contains": "/collections/hats", "type": "navigation"},
    )
    data = _data()
    data["products"][0]["options"] = [{"name": "Color", "values": ["Red"]}]
    issues = validate_tasks([task], tiny_shop, data)
    assert all(i.rule != "single-sku-value-selection" for i in issues)
