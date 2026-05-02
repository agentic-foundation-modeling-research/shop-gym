"""Post-generation benchmark validator.

A small, dependency-free audit pass that catches systematic problems in
generated and hand-authored ShopGuru tasks before they reach an evaluator
sweep. The validator returns a list of :class:`Issue` records rather than
raising, so callers can decide whether to error or just warn.

Rules
-----

The current rule set targets the failure modes that drove manual benchmark
patches in PRs #53 / #54 / #56:

* ``unknown-collection`` — the task's ``url_contains`` references a
  collection handle that doesn't exist in ``data["collections"]``.
* ``unknown-product`` — same for ``/products/<handle>``.
* ``unknown-page`` — same for ``/pages/<handle>`` (only when the host shop
  exposes ``data["pages"]``).
* ``infeasible-filter`` — for ``<slug>-filter-N`` tasks, the dim/value the
  intent names is not realized by any product in the targeted collection.
  This catches the C1 bug class from the design doc.
* ``intent-answer-leak`` — when ``success_criteria.response_contains``
  exists, no listed value may appear verbatim (case-insensitive) in the
  ``intent``. Without this rule, an agent can pass by echoing values out
  of the prompt without ever navigating to the page where the values
  live.
* ``product-not-in-collection`` — the intent mentions a product alongside
  a collection that does not actually contain that product. Catches LLM
  hallucinations that mismatch product/collection memberships.
* ``option-mismatch`` — the intent asks the agent to "select a
  <Option> variant" for a product (e.g. Color, Size) but the product has
  no variant option of that name. Catches the gift-card-with-Color/Size
  hallucination class.

Usage
-----

::

    from shop_guru.io import load_shop_data
    from shop_guru.validate import validate_tasks

    data = load_shop_data(shop)
    issues = validate_tasks(tasks, shop, data)
    for issue in issues:
        print(issue)

The CLI auto-runs this on freshly generated benchmarks and exits non-zero
when any issue is at ``error`` severity. Pass ``--no-validate`` to skip.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from shop_guru.config import Shop

# Tasks whose ID matches this pattern are treated as collection_filter
# benchmarks for the feasibility check. Mirrors emit.make_id(shop, "filter", n).
_FILTER_ID_RE = re.compile(r"^[\w-]+-filter-\d+$")

# Pattern matching `(e.g. <value>)` in collection_filter intents. Captures
# the dimension name plus the sample value.
_FILTER_INTENT_RE = re.compile(
    r"use the (?P<dim>[^\s]+(?:\s+[^\s]+){0,3}?) filter \(e\.g\. (?P<value>[^)]+?)\)"
)


@dataclass(frozen=True)
class Issue:
    """A single validation finding."""

    rule: str
    severity: str  # "error" or "warning"
    task_id: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.task_id} {self.rule}: {self.message}"


def validate_tasks(
    tasks: list[dict],
    shop: Shop,
    data: dict[str, Any],
) -> list[Issue]:
    """Run every rule against ``tasks`` and return collected issues.

    Pure function: makes no I/O, never raises (other than for genuine
    programmer errors like a non-list ``tasks`` argument).
    """
    issues: list[Issue] = []
    indexes = _Indexes.build(data)
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or "?")
        issues.extend(_check_url_contains(task, task_id, indexes))
        issues.extend(_check_filter_feasibility(task, task_id, indexes))
        issues.extend(_check_intent_answer_leak(task, task_id))
        issues.extend(_check_product_in_collection(task, task_id, indexes))
        issues.extend(_check_option_mismatch(task, task_id, indexes))
        issues.extend(_check_single_sku_value_selection(task, task_id, indexes))
    return issues


def has_errors(issues: Iterable[Issue]) -> bool:
    """Return True if any issue has severity ``error``."""
    return any(issue.severity == "error" for issue in issues)


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Indexes:
    collections_by_handle: dict[str, dict]
    products_by_handle: dict[str, dict]
    page_handles: frozenset[str]
    known_dim_names: frozenset[str]  # case-folded

    @classmethod
    def build(cls, data: dict[str, Any]) -> _Indexes:
        collections = {
            c["handle"]: c
            for c in (data.get("collections") or [])
            if c.get("handle")
        }
        products = {
            p["handle"]: p
            for p in (data.get("products") or [])
            if p.get("handle")
        }
        pages = frozenset(
            p["handle"] for p in (data.get("pages") or []) if p.get("handle")
        )
        # All dimension names we recognize when checking filter feasibility:
        # storefront-rendered aliases (Brand/Type), the underlying field
        # names, and every distinct variant option name in the catalog.
        known: set[str] = {
            "brand",
            "vendor",
            "type",
            "producttype",
            "product type",
        }
        for product in products.values():
            for opt in product.get("options") or []:
                name = (opt.get("name") or "").strip().casefold()
                if name:
                    known.add(name)
        return cls(
            collections_by_handle=collections,
            products_by_handle=products,
            page_handles=pages,
            known_dim_names=frozenset(known),
        )


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _check_url_contains(task: dict, task_id: str, indexes: _Indexes) -> list[Issue]:
    sc = task.get("success_criteria") or {}
    url_value = sc.get("url_contains")
    if not isinstance(url_value, str) or not url_value:
        return []

    handle, kind = _extract_handle(url_value)
    if handle is None or kind is None:
        return []

    if kind == "collection" and not _matches_handle_prefix(
        handle, indexes.collections_by_handle
    ):
        return [
            Issue(
                rule="unknown-collection",
                severity="error",
                task_id=task_id,
                message=(
                    f"url_contains {url_value!r} references collection handle "
                    f"{handle!r}, which is not in data/collections.json"
                ),
            )
        ]
    if kind == "product" and not _matches_handle_prefix(handle, indexes.products_by_handle):
        return [
            Issue(
                rule="unknown-product",
                severity="error",
                task_id=task_id,
                message=(
                    f"url_contains {url_value!r} references product handle "
                    f"{handle!r}, which is not in data/products.json"
                ),
            )
        ]
    if (
        kind == "page"
        and indexes.page_handles
        and not _matches_handle_prefix_set(handle, indexes.page_handles)
    ):
        # Pages are softer than collections/products: many storefronts use
        # /policies/* or fallthrough routes rather than data/pages.json. Use
        # `warning` so callers can choose strict vs. lax enforcement.
        return [
            Issue(
                rule="unknown-page",
                severity="warning",
                task_id=task_id,
                message=(
                    f"url_contains {url_value!r} references page handle "
                    f"{handle!r}, which is not in data/pages.json"
                ),
            )
        ]
    return []


def _check_filter_feasibility(
    task: dict, task_id: str, indexes: _Indexes
) -> list[Issue]:
    if not _FILTER_ID_RE.match(task_id):
        return []
    intent = task.get("intent") or ""
    sc = task.get("success_criteria") or {}
    url = sc.get("url_contains") or ""
    handle = url.removeprefix("/collections/") if url.startswith("/collections/") else None
    if not handle:
        return []
    collections = _resolve_collections(handle, indexes.collections_by_handle)
    if not collections:
        # already flagged by _check_url_contains; don't double-report
        return []

    match = _FILTER_INTENT_RE.search(intent)
    if not match:
        return [
            Issue(
                rule="filter-intent-malformed",
                severity="warning",
                task_id=task_id,
                message=(
                    "filter task intent does not match expected "
                    "'use the <dim> filter (e.g. <value>)' pattern"
                ),
            )
        ]
    dim = match.group("dim").strip()
    value = match.group("value").strip()

    realizable = any(
        _filter_realizable(c, indexes.products_by_handle, dim, value) for c in collections
    )
    if realizable:
        return []

    # Distinguish "we know this is infeasible" from "we can't recognize the
    # dim name". A localized storefront (e.g. a Lithuanian shop using
    # for product_type) may name dims in ways the validator doesn't model.
    # Downgrade to a warning in that case so reviewers can adjudicate.
    if not _dim_is_known(dim, indexes.known_dim_names):
        return [
            Issue(
                rule="filter-dim-unknown",
                severity="warning",
                task_id=task_id,
                message=(
                    f"could not verify filter dim {dim!r} on collection "
                    f"{handle!r}; the dim name does not match any product "
                    f"option, vendor/product_type field, or known alias. "
                    f"Manually confirm the storefront exposes this filter."
                ),
            )
        ]

    return [
        Issue(
            rule="infeasible-filter",
            severity="error",
            task_id=task_id,
            message=(
                f"no product in collection {handle!r} has "
                f"{dim}={value!r}; the filter task cannot succeed"
            ),
        )
    ]


def _check_intent_answer_leak(task: dict, task_id: str) -> list[Issue]:
    sc = task.get("success_criteria") or {}
    expected = sc.get("response_contains")
    if not expected:
        return []
    if isinstance(expected, str):
        expected_values = [expected]
    elif isinstance(expected, list):
        expected_values = [v for v in expected if isinstance(v, str) and v.strip()]
    else:
        return []

    intent = (task.get("intent") or "").lower()
    issues: list[Issue] = []
    for value in expected_values:
        needle = value.strip().lower()
        if not needle:
            continue
        if needle in intent:
            issues.append(
                Issue(
                    rule="intent-answer-leak",
                    severity="error",
                    task_id=task_id,
                    message=(
                        f"intent text contains response_contains value "
                        f"{value!r} verbatim; an agent could pass by "
                        f"echoing the prompt without visiting the page"
                    ),
                )
            )
    return issues


# Match phrases like "select Color and Size options" or "select a Format variant".
# Captures everything between "select" and the trailing "(variant|option|value)s?"
# token. We then scan inside the captured phrase for capitalized option names.
_OPTION_PHRASE_RE = re.compile(
    r"[Ss]elect\s+(?P<phrase>[\w ,/]+?)\s+(?:variant|option|value)s?\b"
)
# Capitalized 1- or 2-word tokens inside the phrase. The first letter must be
# uppercase to filter out lowercase adjectives ("appropriate", "preferred",
# "determined") that English speakers use before the actual option name.
_OPTION_NAME_RE = re.compile(r"\b([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20})?)\b")
# Tokens that match the regex but are pre-canned conjunctions/articles/etc.
_OPTION_STOPWORDS: frozenset[str] = frozenset({
    "and",
    "or",
    "any",
    "a",
    "the",
    "an",
    "variant",
    "option",
    "product",
    "item",
    "page",
    "card",
    "this",
    "that",
    "these",
    "those",
    "first",
    "second",
    "third",
})


def _check_option_mismatch(task: dict, task_id: str, indexes: _Indexes) -> list[Issue]:
    """Flag intents that ask for a variant option a product doesn't have.

    Example failure caught: an intent saying "select the appropriate Color and
    Size options" for a Gift Card whose only options are ``Color: ['No Color']``
    and ``Size: ['$25', '$50', ...]``. While the option *names* technically
    match, the values are nominal and the intent reads as a hallucination.
    More commonly, this catches a Gift Card with no Color option at all
    being asked to select a Color.

    The check is intentionally lenient:
    - We only run when the intent mentions at least one product by title.
    - We only flag option names that are explicitly written in the intent
      AND don't appear in any of the mentioned products' real options.
    """
    intent = task.get("intent") or ""
    if not intent:
        return []

    # Find products whose title appears verbatim in the intent.
    mentioned_products: list[dict] = []
    for product in indexes.products_by_handle.values():
        title = (product.get("title") or "").strip()
        if title and len(title) > 4 and title in intent:
            mentioned_products.append(product)
    if not mentioned_products:
        return []

    # Collect the union of real option names across the mentioned products,
    # case-folded. Plus their values (case-folded) for additional hint
    # checking ("select Hardcover" should match an option whose values
    # include "Hardcover" even if the option name itself isn't called out).
    real_option_names: set[str] = set()
    real_option_values: set[str] = set()
    for product in mentioned_products:
        for opt in product.get("options") or []:
            name = (opt.get("name") or "").strip().casefold()
            if name and name not in {"title", "default"}:
                real_option_names.add(name)
            for value in opt.get("values") or []:
                v = (value or "").strip().casefold()
                if v and v not in {"default title", "no color"}:
                    real_option_values.add(v)

    # Extract candidate option names referenced in the intent. We first
    # locate "select … (variant|option|value)" phrases, then scan the
    # captured phrase for capitalized words — that's where the actual
    # option name lives in seed-shop intents (e.g. "select your preferred
    # Color and Size options" → ["Color", "Size"]).
    candidates: set[str] = set()
    for phrase_match in _OPTION_PHRASE_RE.finditer(intent):
        phrase = phrase_match.group("phrase") or ""
        for token_match in _OPTION_NAME_RE.finditer(phrase):
            token = token_match.group(1).strip().casefold()
            if not token or token in _OPTION_STOPWORDS:
                continue
            candidates.add(token)

    issues: list[Issue] = []
    for token in sorted(candidates):
        if token in real_option_names:
            continue
        # Token might describe a value rather than a name (e.g. "select
        # Hardcover" hints at Format=Hardcover). Don't flag in that case.
        if token in real_option_values:
            continue
        # Skip tokens that look like product nouns (more than two whitespace
        # words usually means it's a product description, not an option).
        if len(token.split()) > 2:
            continue
        product_titles = [p.get("title") for p in mentioned_products]
        issues.append(
            Issue(
                rule="option-mismatch",
                severity="warning",
                task_id=task_id,
                message=(
                    f"intent says to select a {token!r} variant/option but "
                    f"the referenced product(s) {product_titles!r} have no "
                    f"option matching that name. Real options on those "
                    f"products: {sorted(real_option_names) or 'none'}."
                ),
            )
        )
    return issues


def _check_single_sku_value_selection(
    task: dict, task_id: str, indexes: _Indexes
) -> list[Issue]:
    """Warn when an intent says ``select <value> for <option>`` but the
    cited product's PDP only has one value for that option.

    Some shops (e.g. mock_clothing) encode each color as a distinct
    product handle, so the PDP renders a Color selector with a single
    value. ``select Obsidian Leather for the Color option`` reads as if
    the agent is picking from a list — but there is no list to pick
    from, only a single auto-selected swatch. The fix is wording like
    ``is offered in Obsidian Leather`` or ``confirm Obsidian Leather for
    Color``, or aiming the task at a multi-value PDP. Severity is
    ``warning`` because the task is still technically solvable: the
    agent just confirms the only swatch.
    """
    intent = task.get("intent") or ""
    if not intent or "select" not in intent.lower():
        return []

    mentioned: list[dict] = []
    for product in indexes.products_by_handle.values():
        title = (product.get("title") or "").strip()
        if title and len(title) > 4 and title in intent:
            mentioned.append(product)
    if not mentioned:
        return []

    issues: list[Issue] = []
    for product in mentioned:
        for opt in product.get("options") or []:
            opt_name = (opt.get("name") or "").strip()
            values = opt.get("values") or []
            if not opt_name or opt_name.casefold() in {"title", "default"}:
                continue
            if len(values) != 1:
                continue
            sole_value = (values[0] or "").strip()
            if not sole_value or sole_value.casefold() == "default title":
                continue
            patterns = (
                # "select Obsidian Leather for the Color option"
                rf"[Ss]elect\s+(?:the\s+)?{re.escape(sole_value)}\s+for\s+(?:the\s+)?{re.escape(opt_name)}",
                # "select the Slate Color variant" / "select Slate Color variant"
                rf"[Ss]elect\s+(?:the\s+)?{re.escape(sole_value)}\s+{re.escape(opt_name)}\s+(?:variant|option)",
            )
            for pat in patterns:
                if re.search(pat, intent, flags=re.IGNORECASE):
                    issues.append(
                        Issue(
                            rule="single-sku-value-selection",
                            severity="warning",
                            task_id=task_id,
                            message=(
                                f"intent says to select {sole_value!r} for "
                                f"{opt_name!r} on {product.get('title')!r}, "
                                f"but that's the only {opt_name} value the PDP "
                                f"shows (single-SKU per Color). Reword as "
                                f"'is offered in {sole_value}' or 'confirm "
                                f"{sole_value} for {opt_name}' to match the UI."
                            ),
                        )
                    )
                    break
    return issues


def _check_product_in_collection(task: dict, task_id: str, indexes: _Indexes) -> list[Issue]:
    """Check if any explicitly mentioned product belongs to any explicitly mentioned collection."""
    intent = task.get("intent") or ""
    issues = []

    # Collect collections and products mentioned in the intent text by their titles
    mentioned_collections = []
    for _handle, c in indexes.collections_by_handle.items():
        title = c.get("title")
        if title and title in intent:
            mentioned_collections.append(c)

    mentioned_products = []
    for _handle, p in indexes.products_by_handle.items():
        title = p.get("title")
        # only check if title is a reasonably long string to avoid spurious matches
        if title and len(title) > 4 and title in intent:
            mentioned_products.append(p)

    if not mentioned_collections or not mentioned_products:
        return []

    # If the task mentions both collections and products, every mentioned product
    # should ideally be in at least ONE of the mentioned collections.
    for product in mentioned_products:
        product_handle = product["handle"]
        found_in_any = False
        for collection in mentioned_collections:
            if product_handle in (collection.get("product_handles") or []):
                found_in_any = True
                break

        if not found_in_any:
            # We warn rather than error because some valid multi-step tasks might mention
            # a collection just for context or as a detour (e.g., "Go to Mens, then search for Women's Hat").
            issues.append(
                Issue(
                    rule="product-not-in-collection",
                    severity="warning",
                    task_id=task_id,
                    message=(
                        f"intent mentions product {product.get('title')!r} and collection(s) "
                        f"{[c.get('title') for c in mentioned_collections]}, but the product "
                        f"does not belong to any of those collections in the data."
                    )
                )
            )

    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_handle(url_value: str) -> tuple[str | None, str | None]:
    """Pull the kind + handle out of a ``url_contains`` value.

    Returns ``(None, None)`` for URLs that don't follow the
    ``/collections/<handle>``, ``/products/<handle>``, or
    ``/pages/<handle>`` shape — those are out of scope for this rule.
    """
    for kind, prefix in (("collection", "/collections/"), ("product", "/products/"), ("page", "/pages/")):
        if url_value.startswith(prefix):
            handle = url_value[len(prefix):].split("?", 1)[0].split("/", 1)[0].strip()
            if handle:
                return handle, kind
            return None, None
    return None, None


def _matches_handle_prefix(query: str, by_handle: dict[str, dict]) -> bool:
    """``url_contains`` is a substring match at runtime: a final URL
    ``/products/whole-geode-compact-…`` satisfies a benchmark whose
    ``url_contains`` is ``/products/whole-geode``. The validator mirrors
    that by accepting any handle that *starts with* ``query``.
    """
    if query in by_handle:
        return True
    return any(handle.startswith(query) for handle in by_handle)


def _matches_handle_prefix_set(query: str, handle_set: frozenset[str]) -> bool:
    if query in handle_set:
        return True
    return any(handle.startswith(query) for handle in handle_set)


def _resolve_collections(
    query: str, collections_by_handle: dict[str, dict]
) -> list[dict]:
    """Return every collection whose handle starts with ``query``.

    Mirrors the runtime ``url_contains`` substring semantics for filter
    feasibility: when the queried prefix matches multiple collections, the
    task is feasible if *any* of them realizes the (dim, value).
    """
    out: list[dict] = []
    exact = collections_by_handle.get(query)
    if exact is not None:
        out.append(exact)
    for handle, collection in collections_by_handle.items():
        if handle == query:
            continue
        if handle.startswith(query):
            out.append(collection)
    return out


def _dim_is_known(dim: str, known_dim_names: frozenset[str]) -> bool:
    """Whether the validator can interpret ``dim`` against this shop.

    A dim is known if its case-folded form appears in ``known_dim_names``,
    which is the union of (a) English aliases like ``Brand``/``Type``,
    (b) the underlying ``vendor``/``product_type`` field names, and
    (c) every variant option name observed in the catalog. Anything else
    (e.g. localized storefront labels) becomes an ``unknown-dim`` warning
    rather than an infeasibility error.
    """
    return dim.casefold() in known_dim_names


def _filter_realizable(
    collection: dict,
    products_by_handle: dict[str, dict],
    dim: str,
    value: str,
) -> bool:
    """True if any product in the collection has ``dim == value``.

    Mirrors the dim resolution used by
    :mod:`shop_guru.generators.collection_filter`: the intent's display name
    can be ``Brand``/``Type`` (from ``DIMENSION_DISPLAY``), but the
    underlying product field is ``vendor``/``product_type``. Variant
    options are checked by raw option name.
    """
    target_dim = dim.casefold()
    target_value = value.casefold()
    for handle in collection.get("product_handles") or []:
        product = products_by_handle.get(handle)
        if not product:
            continue
        if (
            target_dim in {"brand", "vendor"}
            and (product.get("vendor") or "").casefold() == target_value
        ):
            return True
        if target_dim in {"type", "producttype", "product type"}:
            ptype = product.get("product_type") or product.get("productType") or ""
            if ptype.casefold() == target_value:
                return True
        for opt in product.get("options") or []:
            name = (opt.get("name") or "").casefold()
            if name != target_dim:
                continue
            for raw_value in opt.get("values") or []:
                if (raw_value or "").casefold() == target_value:
                    return True
    return False
