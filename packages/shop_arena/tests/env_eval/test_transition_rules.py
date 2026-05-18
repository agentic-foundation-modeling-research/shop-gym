"""Unit tests for ``shop_arena.env_eval.transition.rules`` (spec §5.5.2).

The rule list is the *contract* between the stateful pass and the
metrics schema: every entry must use a closed-enum page class, action
verb, landmark, and state name.  These tests pin that contract so a
typo in the table can't slip in unnoticed.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from shop_arena.env_eval.transition import rules
from shop_arena.env_eval.transition.rules import (
    ACTION_VERBS,
    LANDMARKS,
    PAGE_CLASSES,
    RULE_STATE_NAMES,
    RULE_VERSION,
    RULES,
    Rule,
    Selector,
)


def test_rule_version_is_pinned() -> None:
    """``RULE_VERSION`` must match the spec §5.5.2 contract.

    Bumped from ``"0.1"`` to ``"0.2"`` when :class:`Selector` switched
    from a single ``role`` to a tuple of ``roles`` so themes that mark
    the cart affordance as ``button`` (drawer-style) resolve alongside
    the original ``link`` (navigate-style) form.  Bumped to ``"0.3"``
    with the ``homepage_open_mega_menu`` rule, which adds the ``hover``
    action verb, the ``navigation`` landmark, and the ``mega_menu``
    state name.
    """
    assert RULE_VERSION == "0.3"


def test_rules_is_immutable_tuple() -> None:
    """``RULES`` must be a tuple so accidental mutation fails loudly."""
    assert isinstance(RULES, tuple)
    with pytest.raises(AttributeError):
        RULES.append(RULES[0])  # type: ignore[attr-defined]


def test_rules_has_twelve_entries_matching_spec_table() -> None:
    """Spec §5.5.2 lists 10 rule rows; v0.3 adds ``homepage_open_mega_menu``
    plus its click-variant ``homepage_click_mega_menu`` for themes whose
    nav trigger does not respond to CSS ``:hover``."""
    assert len(RULES) == 12


def test_rule_dataclass_is_frozen() -> None:
    """:class:`Rule` and :class:`Selector` must be frozen so the table is hashable."""
    rule = RULES[0]
    assert dataclasses.is_dataclass(rule)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.id = "mutated"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.selector.roles = ("mutated",)  # type: ignore[misc]


def test_rule_ids_are_unique_and_snake_case() -> None:
    """Rule ids must be unique; ``trace.jsonl`` joins on them."""
    ids = [rule.id for rule in RULES]
    assert len(set(ids)) == len(ids), f"duplicate rule ids: {ids}"
    snake_case = re.compile(r"^[a-z][a-z0-9_]*$")
    for rule_id in ids:
        assert snake_case.fullmatch(rule_id), f"non-snake_case id: {rule_id!r}"


def test_every_page_class_is_in_closed_enum() -> None:
    """``page_class`` values must come from :data:`PAGE_CLASSES` only."""
    for rule in RULES:
        assert rule.page_class in PAGE_CLASSES


def test_every_action_is_in_closed_enum() -> None:
    """``action`` values must come from :data:`ACTION_VERBS` only."""
    for rule in RULES:
        assert rule.action in ACTION_VERBS


def test_every_landmark_is_in_closed_enum() -> None:
    """``selector.landmark`` values must come from :data:`LANDMARKS` only."""
    for rule in RULES:
        assert rule.selector.landmark in LANDMARKS


def test_every_expected_state_is_in_rule_state_names() -> None:
    """Rules predict a strict subset of the LLM enum (no ``no_change``/``other``)."""
    for rule in RULES:
        assert rule.expected_state in RULE_STATE_NAMES


def test_rule_state_names_excludes_llm_only_outputs() -> None:
    """``no_change`` / ``other`` / ``popup_modal`` are LLM-produced, never
    rule-predicted."""
    for forbidden in ("no_change", "other", "popup_modal"):
        assert forbidden not in RULE_STATE_NAMES


def test_needs_derived_query_only_set_on_fill_rules() -> None:
    """``needs_derived_query`` is meaningful only for ``fill`` rules
    (spec §5.5.2: "rules that require <derived_query>")."""
    for rule in RULES:
        if rule.needs_derived_query:
            assert rule.action == "fill", (
                f"rule {rule.id!r} sets needs_derived_query but action is {rule.action!r}"
            )


def test_every_fill_rule_requires_derived_query() -> None:
    """In v0.1 every ``fill`` rule fills the search box, so all of them
    must set ``needs_derived_query=True``."""
    for rule in RULES:
        if rule.action == "fill":
            assert rule.needs_derived_query, (
                f"rule {rule.id!r} is a fill rule but does not require a derived query"
            )


def test_name_patterns_are_case_insensitive() -> None:
    """All selector regexes must compile with ``re.IGNORECASE`` so theme
    casing differences (e.g. "Add to Cart" vs "ADD TO CART") don't drop
    rules."""
    for rule in RULES:
        assert rule.selector.name_pattern.flags & re.IGNORECASE


def test_name_patterns_are_compiled_regexes() -> None:
    """``selector.name_pattern`` must be a compiled :class:`re.Pattern`,
    not a raw string, so the executor never re-compiles per attempt."""
    for rule in RULES:
        assert isinstance(rule.selector.name_pattern, re.Pattern)


def test_spec_table_rows_present() -> None:
    """Pin the spec §5.5.2 ASCII table verbatim: the 10 ``(page_class,
    expected_state)`` pairs must all appear."""
    expected = {
        ("homepage", "announcement_dismissed"),
        ("homepage", "cart_drawer"),
        ("homepage", "mega_menu"),
        ("homepage", "search_overlay"),
        ("homepage", "predictive_panel"),
        ("collection", "filter_panel_open"),
        ("collection", "sort_menu_open"),
        ("product", "variant_select_open"),
        ("product", "cart_drawer"),
        ("cart", "cart_qty_changed"),
        ("search", "predictive_panel"),
    }
    actual = {(rule.page_class, rule.expected_state) for rule in RULES}
    assert actual == expected


def test_homepage_announcement_pattern_matches_close_synonyms() -> None:
    """The dismiss-announcement rule must accept the common labels themes
    use for the close button."""
    pattern = next(
        rule.selector.name_pattern
        for rule in RULES
        if rule.id == "homepage_dismiss_announcement_bar"
    )
    for label in ("Close", "close", "Dismiss", "DISMISS", "×", "✕", "X"):  # noqa: RUF001 — themed close glyphs
        assert pattern.search(label), f"{label!r} should match the dismiss pattern"
    # Prefix-only anchor: a "Closet" link must NOT match.
    assert not pattern.search("Closet collection")


def test_add_to_cart_pattern_matches_cart_and_bag_phrasing() -> None:
    """Some themes ship "Add to bag" instead of "Add to cart"; both must
    match so the rule fires reliably."""
    pattern = next(rule.selector.name_pattern for rule in RULES if rule.id == "product_add_to_cart")
    assert pattern.search("Add to cart")
    assert pattern.search("ADD TO CART")
    assert pattern.search("Add to bag")
    # "Add to wishlist" must not falsely match.
    assert not pattern.search("Add to wishlist")


def test_qty_increase_pattern_matches_plus_and_words() -> None:
    """The cart qty-increment rule must accept both glyph and verbose labels."""
    pattern = next(
        rule.selector.name_pattern for rule in RULES if rule.id == "cart_increase_quantity"
    )
    assert pattern.search("+")
    assert pattern.search("Increase")
    assert pattern.search("Increase quantity")
    assert pattern.search("More")
    # Must not accidentally match a "Decrease" button via a substring.
    assert not pattern.search("Decrease")


def test_homepage_open_mega_menu_uses_hover_under_navigation_landmark() -> None:
    """The mega-menu rule must hover (not click) the first nav-landmark child.

    A ``click`` would navigate the underlying ``<a>`` to the category page
    instead of opening the desktop hover-driven mega menu, so the action
    verb is the load-bearing detail of this rule.  ``landmark='navigation'``
    scopes the search to the primary nav and avoids matching banner-level
    affordances (logo, search button, cart button) that share the
    ``link``/``button`` roles."""
    rule = next(r for r in RULES if r.id == "homepage_open_mega_menu")
    assert rule.action == "hover"
    assert rule.selector.landmark == "navigation"
    assert rule.selector.roles == ("link", "button"), (
        "link first so themes that expose both link + button forms of the trigger "
        "resolve to the link the user actually clicks/hovers"
    )
    assert rule.expected_state == "mega_menu"
    # ``\\S`` matches any non-whitespace name so themes are not coupled to a
    # category vocabulary (\"Women\" / \"Shop\" / \"Catalog\" / … all match).
    for label in ("Women", "Shop", "Catalog", "Men", "ショップ"):
        assert rule.selector.name_pattern.search(label), label


def test_homepage_click_mega_menu_falls_back_to_button_only_click() -> None:
    """Click variant covers themes whose nav trigger needs an explicit click.

    The hover rule above misses themes that wire a real ``<button>`` into the
    primary navigation (drawer-style nav, mobile-first themes) because
    CSS ``:hover`` does nothing there.  This parallel rule fires a click on
    the same kind of selector but skips ``link`` so a click never navigates
    the underlying ``<a href>`` away from the homepage.  Both rules share
    ``expected_state='mega_menu'`` so they collapse onto one canonical state
    node — only the first attempt to fire writes the artifact."""
    rule = next(r for r in RULES if r.id == "homepage_click_mega_menu")
    assert rule.action == "click"
    assert rule.selector.landmark == "navigation"
    assert rule.selector.roles == ("button",), (
        "click must skip ``link`` so a click on an <a href> mega-menu trigger "
        "does not navigate away from the homepage; the hover rule covers links"
    )
    assert rule.expected_state == "mega_menu"

def test_selector_roles_match_aria_canon() -> None:
    """Every entry in ``selector.roles`` must come from the small ARIA
    set EnvEval counts elsewhere (button / link / searchbox / radio).
    Closing the set here keeps the executor's resolver simple."""
    allowed = {"button", "link", "searchbox", "radio"}
    for rule in RULES:
        assert rule.selector.roles, f"rule {rule.id!r} has empty roles tuple"
        for role in rule.selector.roles:
            assert role in allowed, f"rule {rule.id!r} uses unexpected role {role!r}"


def test_public_surface_is_complete() -> None:
    """Every name in ``__all__`` must resolve on the module."""
    for name in rules.__all__:
        assert hasattr(rules, name), f"missing public name: {name}"


def test_selector_constructable_directly() -> None:
    """:class:`Selector` is part of the public surface; tests / external
    tools should be able to build one without going through ``RULES``."""
    selector = Selector(
        roles=("button",),
        name_pattern=re.compile("foo", re.IGNORECASE),
        landmark="main",
    )
    assert selector.roles == ("button",)
    assert selector.landmark == "main"


def test_rule_constructable_directly() -> None:
    """:class:`Rule` is part of the public surface; tests should be able
    to build a synthetic rule without registering it in :data:`RULES`."""
    rule = Rule(
        id="synthetic",
        page_class="homepage",
        action="click",
        selector=Selector(
            roles=("button",),
            name_pattern=re.compile("x"),
            landmark="banner",
        ),
        expected_state="cart_drawer",
        needs_derived_query=False,
    )
    assert rule.id == "synthetic"
    assert rule.page_class == "homepage"


def test_homepage_open_cart_drawer_accepts_link_and_button() -> None:
    """v0.2: the homepage cart rule must match both link- and
    button-style cart affordances so drawer-style themes (where the
    header cart is a ``<button>``) are not silently ``no_target``."""
    rule = next(r for r in RULES if r.id == "homepage_open_cart_drawer")
    assert rule.selector.roles == ("link", "button"), (
        "link must precede button so existing navigate-style themes resolve identically to v0.1"
    )


def test_homepage_cart_pattern_matches_cart_and_bag_phrasing() -> None:
    """v0.2: some themes label the cart affordance \"Bag\" / \"Shopping bag\"
    (Allbirds, Glossier, etc.); both wordings must match."""
    pattern = next(
        rule.selector.name_pattern for rule in RULES if rule.id == "homepage_open_cart_drawer"
    )
    for label in ("Cart", "cart", "My cart", "Bag", "Shopping bag", "BAG"):
        assert pattern.search(label), f"{label!r} should match the cart pattern"
    # Defensive: an unrelated link like "Cartography" must not match.
    assert not pattern.search("Cartography")
    # "Baggage" must not match either — word-boundary regex protects us.
    assert not pattern.search("Baggage claim")
