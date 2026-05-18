"""Closed list of stateful interaction rules (spec §5.5.2).

EnvEval's stateful pass attempts a deterministic, per-page-class set of
interactions and asks the state-namer LLM only when a structural diff
fires.  This module owns the *versioned* declarative list of those
rules; the selector resolution and execution glue live in
:mod:`shop_arena.env_eval.transition.stateful`.

The list is intentionally small (10 entries) and **closed**: adding,
re-ordering, or removing a rule is a schema-versioned event
(``metrics.json:version`` bump) so cohort comparisons stay meaningful.

Each :class:`Rule` pins:

* ``page_class`` — which discovered page bucket the rule applies to
  (one of :data:`PAGE_CLASSES`).  ``cart`` and ``search`` are the two
  sub-buckets of the merged ``cart_and_search`` discovery bucket.
* ``action`` — the Playwright verb (``click`` or ``fill``).
* ``selector`` — role + name regex + landmark scope used to locate the
  axtree node, and therefore the BrowserGym ``bid`` the executor will
  drive.
* ``expected_state`` — the state name candidate emitted on a structural
  diff.  The state-namer LLM may downgrade the result to ``no_change``
  / ``other`` / ``popup_modal``; those values are produced by the
  prompt, not by rules, and are therefore deliberately absent from
  :data:`RULE_STATE_NAMES`.
* ``needs_derived_query`` — when ``True``, the rule is silently skipped
  if page selection could not infer a search query (spec §5.5.2).

The module is import-safe: building :data:`RULES` only compiles regexes
and constructs frozen dataclasses, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal, get_args

__all__ = [
    "ACTION_VERBS",
    "LANDMARKS",
    "PAGE_CLASSES",
    "RULES",
    "RULE_STATE_NAMES",
    "RULE_VERSION",
    "ActionVerb",
    "Landmark",
    "PageClass",
    "Rule",
    "RuleStateName",
    "Selector",
]

#: Version of the rule list this module ships.  Bumped on **any** change
#: to :data:`RULES` — added/removed entries, selector-shape changes, or
#: ``expected_state`` re-targeting.  Recorded in
#: ``manifest.json:rule_version`` (spec §5.7) so a measured graph stays
#: traceable to the rule list that produced it.
RULE_VERSION: Final[str] = "0.3"


#: Closed enum of page buckets the rule executor dispatches against.
#: ``cart`` and ``search`` are the two leaves of the ``cart_and_search``
#: discovery bucket (see :class:`shop_arena.env_eval.pages.CartAndSearch`);
#: ``policy`` has no rules and is therefore deliberately omitted from
#: this Literal so a typo can't reach :data:`RULES`.
PageClass = Literal["homepage", "collection", "product", "cart", "search"]
PAGE_CLASSES: Final[tuple[PageClass, ...]] = get_args(PageClass)

#: Closed enum of action verbs a rule may invoke.  v0.3 adds ``hover`` so
#: a rule can trigger a CSS/JS hover-only affordance (e.g. desktop mega
#: menu) without falling back to ``click`` (which would navigate away on
#: an underlying ``<a>`` element).
ActionVerb = Literal["click", "fill", "hover"]
ACTION_VERBS: Final[tuple[ActionVerb, ...]] = get_args(ActionVerb)

#: Closed ARIA landmark roles the selector may scope to.  ``banner`` is
#: the page header (announcement bar, primary nav, search/cart icons),
#: ``main`` is the page body, and ``navigation`` is any nav landmark
#: (added in v0.3 so the mega-menu rule can scope to a primary nav
#: container without dragging in unrelated banner-level affordances).
Landmark = Literal["banner", "main", "navigation"]
LANDMARKS: Final[tuple[Landmark, ...]] = get_args(Landmark)

#: Closed enum of state names a rule may *predict*.  This is a strict
#: subset of the LLM state-namer enum: ``no_change``, ``other``, and
#: ``popup_modal`` are produced only by the LLM (the rule itself never
#: predicts "no change") and therefore deliberately omitted here.
RuleStateName = Literal[
    "announcement_dismissed",
    "cart_drawer",
    "cart_qty_changed",
    "filter_panel_open",
    "mega_menu",
    "predictive_panel",
    "search_overlay",
    "sort_menu_open",
    "variant_select_open",
]
RULE_STATE_NAMES: Final[tuple[RuleStateName, ...]] = get_args(RuleStateName)


@dataclass(frozen=True, slots=True)
class Selector:
    """Axtree selector for a stateful rule's target node.

    The selector is resolved by :mod:`stateful` against the merged
    BrowserGym axtree of the loaded page, not against raw DOM:
    role/name come from accessibility attributes, and ``landmark``
    constrains the search to descendants of the first axtree node with
    that ARIA role.  Keeping the resolution pure-axtree means the rule
    list is reproducible across BrowserGym minor versions.

    Attributes:
        roles: Tuple of ARIA roles, any of which the target node may
            carry.  Themes encode the same affordance with different
            roles (e.g. a header cart can be ``role=link`` for an
            ``<a href="/cart">`` or ``role=button`` for a drawer
            toggle); the resolver matches the first node whose role is
            in this tuple.  Order is treated as priority — a theme that
            exposes both forms resolves to the role listed first.
            Roles are matched case-sensitively against
            ``axtree_node.role.value``.
        name_pattern: Compiled regex (``re.IGNORECASE`` + ``re.UNICODE``)
            applied to the node's accessible name.  Patterns are
            intentionally strict so a vague match (e.g. a "Close" link
            in the footer) cannot be selected when the rule wanted the
            header announcement-bar close button.
        landmark: ARIA landmark scope.  The executor walks down from
            the first axtree node whose role equals ``landmark`` and
            considers only its descendants.
    """

    roles: tuple[str, ...]
    name_pattern: re.Pattern[str]
    landmark: Landmark


@dataclass(frozen=True, slots=True)
class Rule:
    """A single (page-class, action, selector → expected-state) entry.

    Attributes:
        id: Stable, snake_case identifier unique within :data:`RULES`.
            Recorded verbatim in ``trace.jsonl`` so a state node /
            edge can be traced to the rule that produced it.
        page_class: Discovered bucket the rule fires on.
        action: Playwright verb the executor will invoke.
        selector: Axtree selector for the target node.
        expected_state: State name candidate emitted to the LLM as the
            "rule's guess".  The LLM may downgrade to ``no_change`` /
            ``other``.
        needs_derived_query: When ``True`` (only used for ``fill`` rules
            in v0.1), the executor skips the rule if page selection
            could not infer a search query (spec §5.5.2).
    """

    id: str
    page_class: PageClass
    action: ActionVerb
    selector: Selector
    expected_state: RuleStateName
    needs_derived_query: bool


def _make(
    *,
    rule_id: str,
    page_class: PageClass,
    action: ActionVerb,
    roles: tuple[str, ...],
    name_pattern: str,
    landmark: Landmark,
    expected_state: RuleStateName,
    needs_derived_query: bool = False,
) -> Rule:
    """Construct a :class:`Rule` from its primitive fields.

    Internal helper; centralizing construction makes the :data:`RULES`
    table read like the spec §5.5.2 ASCII table while keeping regex
    compilation in one place (so flag drift is impossible).
    """
    return Rule(
        id=rule_id,
        page_class=page_class,
        action=action,
        selector=Selector(
            roles=roles,
            name_pattern=re.compile(name_pattern, re.IGNORECASE | re.UNICODE),
            landmark=landmark,
        ),
        expected_state=expected_state,
        needs_derived_query=needs_derived_query,
    )


#: Closed rule list (spec §5.5.2 table).  Order matches the spec so
#: ``trace.jsonl`` reads top-to-bottom in the same sequence as the doc.
#: Wrapped in a tuple so accidental ``RULES.append(...)`` fails loudly.
RULES: Final[tuple[Rule, ...]] = (
    _make(
        rule_id="homepage_dismiss_announcement_bar",
        page_class="homepage",
        action="click",
        # Announcement bars are typically a header-region close button
        # whose accessible name is "Close" / "Dismiss" / "✕".  Anchor on
        # word boundaries so a "Closet" link in nav can't match.
        roles=("button",),
        name_pattern=r"^\s*(?:(?:close|dismiss|x)\b|[×✕])",  # noqa: RUF001 — themed close-button glyphs
        landmark="banner",
        expected_state="announcement_dismissed",
    ),
    _make(
        rule_id="homepage_open_cart_drawer",
        page_class="homepage",
        action="click",
        # Cart icons are encoded two ways across themes: as a link
        # (``<a href="/cart">``) for navigate-to-cart-page themes, or
        # as a button for drawer-style themes.  We accept both — the
        # state-namer LLM downgrades the link/navigate case to
        # ``no_change``/``other`` from pre/post screenshots.  Banner
        # scope keeps an in-page "View cart" CTA from matching.  Some
        # themes label the affordance "Bag" / "Shopping bag".
        roles=("link", "button"),
        name_pattern=r"\b(cart|bag)\b",
        landmark="banner",
        expected_state="cart_drawer",
    ),
    _make(
        rule_id="homepage_open_search_overlay",
        page_class="homepage",
        action="click",
        roles=("button",),
        name_pattern=r"\bsearch\b",
        landmark="banner",
        expected_state="search_overlay",
    ),
    _make(
        rule_id="homepage_open_mega_menu",
        page_class="homepage",
        # Desktop mega menus open on hover, not click — a click on the
        # underlying ``<a>`` would navigate to the category page instead
        # of opening the panel.  Hovering keeps the homepage URL stable
        # so the structural diff captures the menu opening, not a
        # navigation.
        action="hover",
        # Both ``link`` (Shopify default: ``<a href>`` with hover-driven
        # mega menu) and ``button`` (themes that mark the trigger
        # explicitly with ``role=button``) are accepted.  Order matters:
        # ``link`` first so themes with both forms resolve to the link.
        roles=("link", "button"),
        # Match anything — every theme labels the trigger differently
        # ("Women", "Shop", "Catalog", "Brands", …), so we anchor on
        # "first nav-landmark child with a name" rather than a category
        # vocabulary.  ``\\S`` (instead of ``.+``) skips the rare empty-
        # name node a theme might emit for a logo placeholder.
        name_pattern=r"\S",
        # ``navigation`` (added in v0.3) scopes the search to the first
        # ``role=navigation`` landmark — the primary header nav — so the
        # logo / search / cart affordances inside ``banner`` cannot match
        # before a real nav item does.
        landmark="navigation",
        expected_state="mega_menu",
    ),
    _make(
        rule_id="homepage_click_mega_menu",
        page_class="homepage",
        # Click-to-open variant for themes whose nav trigger is wired to a
        # click handler (drawer-style nav, mobile-first themes, custom
        # builds) and CSS ``:hover`` does nothing.  Same expected_state as
        # the hover variant: both rules collapse onto a single state node
        # via :func:`state_node_id` so a shop with both forms still maps
        # to one canonical ``state:/:mega_menu`` (only the first attempt
        # to fire writes the state-node folder).
        action="click",
        # Restrict to ``button`` (skip ``link``).  A click on an ``<a
        # href="/collections/...">`` mega-menu trigger would navigate away
        # from the homepage, polluting the post snapshot with the category
        # page; the hover rule above already covers that link-shaped case.
        # Themes that wire a real ``<button>`` into the navigation landmark
        # are exactly the ones the hover rule misses, so click here is
        # narrowly targeted.
        roles=("button",),
        name_pattern=r"\S",
        landmark="navigation",
        expected_state="mega_menu",
    ),
    _make(
        rule_id="homepage_predictive_search",
        page_class="homepage",
        action="fill",
        # Searchbox is the canonical role; some themes still mark it as
        # plain textbox, so the executor falls back to ``textbox`` only
        # via a separate rule if needed (not in v0.1 — keep it closed).
        roles=("searchbox",),
        name_pattern=r"\bsearch\b",
        landmark="banner",
        expected_state="predictive_panel",
        needs_derived_query=True,
    ),
    _make(
        rule_id="collection_open_filter_panel",
        page_class="collection",
        action="click",
        roles=("button",),
        name_pattern=r"\bfilter\b",
        landmark="main",
        expected_state="filter_panel_open",
    ),
    _make(
        rule_id="collection_open_sort_menu",
        page_class="collection",
        action="click",
        roles=("button",),
        name_pattern=r"\bsort\b",
        landmark="main",
        expected_state="sort_menu_open",
    ),
    _make(
        rule_id="product_open_variant_select",
        page_class="product",
        action="click",
        # Variant pickers are usually radio inputs grouped by option
        # (size, color).  The executor will pick the first matching
        # node; the rule asserts that *some* variant control exists.
        roles=("radio",),
        name_pattern=r".+",
        landmark="main",
        expected_state="variant_select_open",
    ),
    _make(
        rule_id="product_add_to_cart",
        page_class="product",
        action="click",
        roles=("button",),
        name_pattern=r"\b(add to cart|add to bag)\b",
        landmark="main",
        expected_state="cart_drawer",
    ),
    _make(
        rule_id="cart_increase_quantity",
        page_class="cart",
        action="click",
        roles=("button",),
        # Themes label this "+", "Increase", "Increase quantity", "More".
        name_pattern=r"^(\+|increase\b|more\b)",
        landmark="main",
        expected_state="cart_qty_changed",
    ),
    _make(
        rule_id="search_predictive_search",
        page_class="search",
        action="fill",
        roles=("searchbox",),
        name_pattern=r"\bsearch\b",
        landmark="banner",
        expected_state="predictive_panel",
        needs_derived_query=True,
    ),
)
