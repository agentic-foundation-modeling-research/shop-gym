"""Generator: end-to-end shopping journeys (skill ``e2e``).

This generator uses an LLM (via litellm) to author realistic, multi-step
shopping journeys based on the shop's extracted data. It implements the
prompting strategy defined in ``manual_journey_prompt.md`` and adds a
self-polish loop that uses :mod:`shop_guru.validate` findings to drive
regeneration of low-quality tasks.

Because these tasks are LLM-generated, they may still contain edge-case
hallucinations even after the polish loop. A human MUST review and test
the output before relying on it for evaluation.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
from typing import Any

from shop_guru._dotenv import load_project_env
from shop_guru.config import Shop
from shop_guru.filters import collections_with_min_products
from shop_guru.validate import Issue, validate_tasks

log = logging.getLogger(__name__)

try:
    import litellm
except ImportError:
    litellm = None

# Maximum number of polish-loop iterations. Each iteration costs one
# additional LLM call but only re-asks for the tasks the validator
# flagged.
_POLISH_MAX_ROUNDS = 2

# Cap how many option values are inlined into the prompt per option to
# keep the per-product line readable.
_MAX_OPTION_VALUES_IN_PROMPT = 4

SYSTEM_PROMPT = """You are an expert at designing evaluation tasks for e-commerce web agents.
Your job is to author realistic end-to-end shopping journeys that mirror how
real human buyers actually browse and transact on online stores.

Hard rules:
- Every task must be 100% grounded in the provided shop data. Do not invent
  products, collections, page titles, or variant options that are not in
  the data dump below.
- A product mentioned in a task must exist in the catalog (Title + handle).
- A collection mentioned in a task must exist (Title + handle).
- If you ask the agent to "select a Color variant" or "select a Size",
  the named product MUST have that variant option AND values. Otherwise
  use generic phrasing like "select any variant" or simply "add it to cart".
- A product/collection pairing in the same task (e.g. "Navigate to X
  collection and add product Y") is only valid if Y is actually a member
  of X according to the Product-to-Collection Mappings section.
- Every task must end in a well-defined state the agent can reach: a
  specific set of items in the cart, a specific URL visited for a
  navigation task. Never "and then browse around".
- **Never instruct the agent to click Checkout, proceed to checkout, head
  to a checkout page, abandon checkout, or otherwise traverse the cart \u2192
  checkout boundary.** Checkout is intentionally disabled on SandboxShops
  and the LLM judge grades tasks on the **final cart state only**. End
  shopping tasks with wording like "Once the product is in your cart,
  end the session. Do not click any Checkout button." For tasks involving
  cart edits (add \u2192 remove, quantity change), describe the expected final
  cart explicitly.
- Intents should be second-person, imperative. Shopping tasks should be
  one or two short paragraphs; they may include natural detours (policy
  lookup, About page, brand comparison) before the cart-state terminal.
- Avoid tasks that require user authentication, payment entry, or any
  externally-gated flow.
- Do not produce tasks that require human judgment calls the agent cannot
  verify (e.g., "pick the most stylish product").

Quality bar (this is what separates a great task from a basic one):
- Open with a one-sentence persona or motivation that frames the journey
  ("First-time visitor.", "You're a returns-cautious shopper.",
  "Multi-pet household shopping.", "Sales hunting.").
- Reference specific storefront UI elements (homepage banner, top menu,
  footer Quick Links, brand menu) by name when they exist.
- Mix at least 2-3 distinct skills per task (search + compare + cart edit;
  policy lookup + nav drilldown + add). Single-step "search and add"
  tasks are too easy and should be the minority.
- Use exact brand/product/collection titles as written in the data \u2014
  never paraphrase ("Fresh Drops" not "new arrivals", "Womens Run Club"
  not "running gear").

Output format: a JSON object with a single key "tasks" containing an array
of task objects, each with fields:
  id (slug-friendly string),
  type ("shopping" or "navigation"),
  intent (string),
  success_criteria (object with url_contains and a descriptive type field).
Do not include the `url` field \u2014 that will be filled in downstream.
"""

USER_PROMPT_TEMPLATE = """Author {count} end-to-end evaluation tasks for the following store.
Follow the system prompt's schema and quality bar. Cover as many of the
behavior categories below as this store supports, and skip any that are
not applicable to this store.

### Shop profile
Name: {store_name}
Description: {store_description}
Country: {country}, Currency: {currency}, Language: {language}
Domain: {shop_url}

### Top collections (title \u2014 handle)
{collections_list}

### Top product types
{product_types_list}

### Example products (title \u2014 handle, with REAL variant options & values)
{products_list}

### Product-to-Collection memberships (use these to ground multi-step tasks)
{mapping_str}

### Collection facets / option patterns (for filter tasks)
{option_patterns_list}

### Policy / info pages (title \u2014 /pages/handle)
{pages_list}

### Gift card products
{gift_card_list_or_none}

### Behavior categories to cover (aim for at least 10 of 14)
1. Search & atomic add-to-cart
2. Nav drilldown (menu \u2192 sub-menu \u2192 collection \u2192 product)
3. Filter + sort (e.g. Format=Hardcover then sort by price)
4. Filter that returns zero results, then recover
5. Substitute-match discovery (intended product missing \u2192 close alternative)
6. Review / detail read on a product page
7. Size chart / fit guide lookup
8. Shipping policy lookup (with cart action after)
9. Returns / refunds lookup (with cart action after)
10. Gift card purchase (only if the shop sells gift cards)
11. Multi-product cart with edit (add A, add B, remove A, set qty 2 on B)
12. Cross-collection or cross-brand comparison (compare A and B, pick one)
13. Contact / store locator / about page
14. Free-shipping threshold or sale-discount calculation (if banner exists)

### High-quality reference tasks (from other shops in this benchmark suite)
Notice the persona opener, multi-step structure, the use of exact
storefront text, and the descriptive ``success_criteria.type`` field.

Example A \u2014 multi-pet household shopping (mock_pet_food):
  intent: "Multi-pet household shopping. Navigate to the Dog Kibble collection via the Dogs menu and add any kibble product to cart. Navigate to Cats \u2192 Litter from the top menu and open <CatLitterBrand>. Select any size variant (for example Original 28lb) and add it to cart. Open the full cart page and increase the cat litter quantity from 1 to 2. Once the cart contains one dog kibble and two units of cat litter, end the session. Do not click any Checkout button."
  success_criteria.type: "cart_multi_pet_with_quantity_edit"

Example B \u2014 first-time visitor exploring About + Contact (mock_pet):
  intent: "First-time visitor. Open the Apie mus (About Us) page from the top menu and read the store description and values. Navigate to the Kontaktai (Contact) page from the same menu, and note the phone number and email listed on the page. Navigate back to the homepage via the logo. Open the Š unims menu, click Žaislai (Toys), pick any toy product, open its page, and add it to cart with any Dydis variant. Once the toy is in your cart, end the session. Do not click any Checkout button."
  success_criteria.type: "cart_after_first_visit_explore"

Example C \u2014 free-shipping threshold calculation (mock_pet):
  intent: "Hit the free-shipping threshold. Note the \\"Nemokamas pristatymas nuo 49 Eur\\" banner on the homepage. Navigate to Š unims \u2192 Skanėstai and add a treat product under \u20ac25 to the cart. Open the cart page, observe how much more you need to reach \u20ac49 for free shipping. Go back to the store, navigate to the same Skanėstai category, and add a second product that pushes the total over \u20ac49. Return to cart, confirm the free-shipping banner has updated. Once both products are in your cart with a total over \u20ac49, end the session. Do not click any Checkout button."
  success_criteria.type: "cart_after_free_shipping_threshold"

Example D \u2014 cross-brand comparison (mock_pet):
  intent: "Cross-brand dog-food comparison. Open the <BrandA> collection from the brand menu, pick a <BrandA> š unų pašaras product, open it, and note the Svoris options (e.g. 3 kg, 12 kg). Without adding it, navigate to the <BrandB> š unų pašaras collection and pick a <BrandB> dog food product; compare its Svoris options. Decide on one of the two brands, return to that product, select any Svoris variant, and add it to cart. Once that dog food is in your cart, end the session. Do not click any Checkout button."
  success_criteria.type: "cart_after_cross_brand_compare"

Example E \u2014 filter that returns zero results, then recover (mock_toy):
  intent: "Navigate to the Christmas & Hanukkah collection via the Shop by Holidays & Events menu. Apply a Size filter for \\"3-6 Months\\"; results will likely be sparse or empty. Observe the empty or filtered state, then clear the Size filter and apply a different one such as Color = Blue. If products appear, open the first one, select any variant, and add it to cart; if still empty, remove all filters and pick any product from the unfiltered list. Once a product is in your cart, end the session. Do not click any Checkout button."
  success_criteria.type: "cart_after_filter_recover"

Example F \u2014 multi-product cart with cross-brand edit (mock_toy):
  intent: "Open the Shop by Brand menu and click <AuthorBrand>. Note a hardcover title you'd like; do not add it yet. Navigate back via the top menu to Shop by Brand and click <PlushBrand>. Browse the <PlushBrand> Toys collection, pick any plush, and add it to cart with any variant. Return to the <AuthorBrand> collection (via Shop by Brand again), find the book you noted, and add it to cart. Open the cart and remove the <PlushBrand> plush (keeping only the <AuthorBrand> book). Once the cart contains only the <AuthorBrand> book, end the session. Do not click any Checkout button."
  success_criteria.type: "cart_after_cross_brand_edit"

Example G \u2014 returns-cautious browse, no cart (mock_toy):
  intent: "You're a returns-cautious shopper. From the footer, navigate to the Return and refund policy page (Terms and Conditions) and read the 14-day return window, the store-credit-only refund terms, and the sale-items-excluded note. Navigate back to the homepage, then open the New Arrivals collection via the top menu and pick the first product with multiple variants. Open its product page and read the description but do not add to cart; end the session once you've reviewed both the policy and a candidate product."
  success_criteria.type: "policy_first_browse_no_cart"

Example H \u2014 substitute-match discovery (mock_toy):
  intent: "Open the Shop by Brand menu and click <PlushBrand>. Browse the <PlushBrand> Toys collection and note a plush you find appealing; do not add it. Instead, use the top search bar to search for \\"plush\\" to find similar products across brands. From the search results open a Stuffed Toys & Plushies product that is not a <PlushBrand> item (for example a plush from a different brand listed in the storefront). Read the description, pick any variant, and add it to cart. Once the non-<PlushBrand> plush is in your cart, end the session. Do not click any Checkout button."
  success_criteria.type: "cart_contains_substitute_brand"

### Anti-patterns to AVOID
- "Search for X. Pick a Color and Size variant. Add to cart." \u2014 too thin,
  no persona, no detour, single skill.
- Mentioning "Color" or "Size" for a product whose options list above does
  NOT include that name.
- Generic UI references like "navigate to the homepage" without naming a
  specific section or CTA.
- Two products in one intent that are not co-located in any collection
  according to the membership list above.

When constructing tasks, USE EXACT product titles, collection titles, and
option names from the lists above. Use the storefront's own wording for
collection names (\"Fresh Drops\" not \"new arrivals\"). For multi-step
tasks, ensure each (collection, product) pair you mention is a real
membership.

Respond with a JSON object with a "tasks" key containing the array of
{count} tasks. Each `id` should use the format
"{shop_slug}-e2e-v1-{{index}}" replacing {{index}} with numbers starting at 1.
"""


def generate(shop: Shop, data: dict[str, Any], seed: int = 0, count: int = 16) -> list[dict]:
    """Emit up to ``count`` E2E tasks for ``shop`` using an LLM.

    The pipeline is:

    1. Sample shop context (collections, products w/ real options, policies).
    2. Call the LLM with a richly grounded prompt + many few-shot examples.
    3. Validate the returned tasks via :func:`shop_guru.validate.validate_tasks`.
    4. If issues are found, build a polish prompt that lists each failed
       task + its specific issues + the fresh shop context, and ask the LLM
       to regenerate ONLY those tasks. Loop up to ``_POLISH_MAX_ROUNDS``.
    5. Return the merged best-effort task list.
    """
    if not litellm:
        log.warning("litellm is not installed. Skipping auto-e2e generation.")
        return []

    # Load .env so OPENAI_BASE_URL / OPENAI_API_KEY are populated
    # before the litellm call. Idempotent across multiple invocations.
    load_project_env()

    model = os.environ.get("SHOPGURU_E2E_MODEL", "openai/google:gemini-3.1-pro-preview")
    api_base = os.environ.get("OPENAI_BASE_URL")
    log.info(
        "Generating %d E2E tasks for %s using model %s via %s...",
        count,
        shop.slug,
        model,
        api_base or "<default>",
    )

    context = _build_prompt_context(shop, data, seed=seed, count=count)
    user_prompt = USER_PROMPT_TEMPLATE.format(**context)

    tasks = _llm_generate(model, api_base, SYSTEM_PROMPT, user_prompt, seed=seed)
    if not tasks:
        return []

    # Polish loop: repeatedly fix tasks the validator flags.
    for round_num in range(1, _POLISH_MAX_ROUNDS + 1):
        issues = validate_tasks(tasks, shop, data)
        actionable = [
            i for i in issues
            if i.severity == "error"
            or i.rule in {"option-mismatch", "product-not-in-collection", "filter-dim-unknown"}
        ]
        if not actionable:
            break
        log.warning(
            f"polish round {round_num}: {len(actionable)} issue(s) flagged; "
            f"asking LLM to regenerate affected tasks..."
        )
        tasks = _polish_tasks(
            model=model,
            api_base=api_base,
            seed=seed + round_num,
            tasks=tasks,
            issues=actionable,
            context=context,
        )

    log.warning(
        f"\n{'!' * 60}\nGenerated {len(tasks)} E2E tasks for {shop.slug} using LLM "
        f"(after up to {_POLISH_MAX_ROUNDS} polish rounds).\n"
        f"These MUST still be manually reviewed and tested before evaluation use!\n"
        f"{'!' * 60}\n"
    )
    return tasks


# ---------------------------------------------------------------------------
# Context / prompt construction
# ---------------------------------------------------------------------------


def _build_prompt_context(
    shop: Shop, data: dict[str, Any], *, seed: int, count: int
) -> dict[str, Any]:
    """Pure-function builder of the dict passed to ``USER_PROMPT_TEMPLATE.format``."""
    rng = random.Random(seed)

    # Collections (≥3 products, non-generic).
    collections = collections_with_min_products(data.get("collections") or [], min_products=3)
    rng.shuffle(collections)
    col_str = (
        "\n".join(f"- {c['title']} \u2014 {c['handle']}" for c in collections[:20]) or "None"
    )

    # Product types (top 10 by frequency).
    stats = data.get("stats") or {}
    ptypes = stats.get("product_types") or []
    ptype_str = (
        "\n".join(
            f"- {p.get('product_type')} ({p.get('count')} products)"
            for p in sorted(ptypes, key=lambda p: p.get("count", 0), reverse=True)[:10]
        )
        or "None"
    )

    # Sample products: bias toward multi-variant, then top up with single-variant.
    products = data.get("products") or []
    multi_variant = [p for p in products if len(p.get("variants") or []) > 1]
    single_variant = [p for p in products if len(p.get("variants") or []) <= 1]
    rng.shuffle(multi_variant)
    rng.shuffle(single_variant)
    sample_products = (multi_variant[:12] + single_variant)[:18]
    rng.shuffle(sample_products)

    prod_str = "\n".join(_format_product_with_options(p) for p in sample_products) or "None"

    # Per-product collection memberships, restricted to the sampled products
    # to keep the prompt focused.
    mapping_str = (
        "\n".join(_format_product_collections(p, collections) for p in sample_products) or "None"
    )

    # Option patterns (shop-wide), used by collection_filter generator and
    # also a useful hint here for filter-style intents.
    #
    # Two known shapes in the wild (see io.py):
    #   1. Calibration shops emit a list of dicts:
    #      [{"name": "Color", "count": 90, "sample_values": ["Red", ...]}, ...]
    #   2. Composite shops (multi_pipeline.py) emit a list of single-element
    #      lists: [["Color"], ["Size"], ...] — name-only, no values.
    # Be defensive about both.
    option_patterns = stats.get("option_patterns") or []
    opt_pat_lines: list[str] = []
    for entry in option_patterns:
        if isinstance(entry, dict):
            name = (entry.get("name") or "").strip()
            samples = entry.get("sample_values") or []
        elif isinstance(entry, list) and entry:
            name = str(entry[0]).strip()
            samples = list(entry[1:])
        elif isinstance(entry, str):
            name = entry.strip()
            samples = []
        else:
            continue
        if not name or name.lower() in {"title", "default"}:
            continue
        suffix = f": e.g. {', '.join(str(s) for s in samples[:3])}" if samples else ""
        opt_pat_lines.append(f"- {name}{suffix}")
    opt_pat_str = "\n".join(opt_pat_lines) or "None"

    # Policy / info pages.
    pages = data.get("pages") or []
    policy_keywords = re.compile(
        r"ship|return|refund|size|contact|gift|faq|about", re.IGNORECASE
    )
    policy_pages = [
        p
        for p in pages
        if policy_keywords.search(p.get("title", ""))
        or policy_keywords.search(p.get("handle", ""))
    ]
    page_str = (
        "\n".join(f"- {p.get('title')} \u2014 /pages/{p.get('handle')}" for p in policy_pages)
        or "None"
    )

    # Gift cards.
    gift_cards = [
        p for p in products if p.get("is_gift_card") or "gift-card" in (p.get("handle") or "")
    ]
    gc_str = (
        "\n".join(_format_product_with_options(p) for p in gift_cards[:5])
        if gift_cards
        else "None"
    )

    store = data.get("store") or {}
    return {
        "count": count,
        "shop_slug": shop.slug,
        "store_name": shop.name,
        "store_description": store.get("description", "N/A"),
        "country": shop.country,
        "currency": shop.currency,
        "language": shop.language,
        "shop_url": shop.shop_url,
        "collections_list": col_str,
        "product_types_list": ptype_str,
        "products_list": prod_str,
        "mapping_str": mapping_str,
        "option_patterns_list": opt_pat_str,
        "pages_list": page_str,
        "gift_card_list_or_none": gc_str,
    }


def _format_product_with_options(product: dict) -> str:
    """Render a product line with its real option names AND a few real values.

    Why values matter: the LLM otherwise hallucinates "select Color and Size"
    on a gift card whose values are nominal ("No Color", "$25"). With the
    actual values in front of it the LLM can either skip the variant
    instruction or use a more accurate phrasing ("select a $50 denomination").
    """
    title = product.get("title") or ""
    handle = product.get("handle") or ""
    options = []
    for opt in product.get("options") or []:
        name = (opt.get("name") or "").strip()
        if not name or name.lower() in {"title", "default"}:
            continue
        values = [str(v).strip() for v in (opt.get("values") or [])]
        sample_vals = ", ".join(values[:_MAX_OPTION_VALUES_IN_PROMPT]) + (
            "…" if len(values) > _MAX_OPTION_VALUES_IN_PROMPT else ""
        )
        options.append(f"{name}=[{sample_vals}]")
    opt_str = f" (Options: {'; '.join(options)})" if options else " (no variant options)"
    return f"- {title} \u2014 {handle}{opt_str}"


def _format_product_collections(product: dict, collections: list[dict]) -> str:
    """Return one line listing the collections this product is a member of."""
    handle = product.get("handle")
    if not handle:
        return f"- {product.get('title', '?')}: in no collections"
    member_titles = [c["title"] for c in collections if handle in (c.get("product_handles") or [])]
    if not member_titles:
        return f"- {product.get('title')}: not in any browseable collection"
    return f"- {product.get('title')}: in collections {', '.join(member_titles[:6])}"


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


def _llm_generate(
    model: str, api_base: str | None, system_prompt: str, user_prompt: str, *, seed: int
) -> list[dict]:
    """Single LLM call returning a list of task dicts. Empty list on error."""
    try:
        response = litellm.completion(
            model=model,
            api_base=api_base,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            seed=seed,
        )
        content = response.choices[0].message.content
        return json.loads(content).get("tasks", []) or []
    except Exception as exc:
        log.error(f"LLM call failed: {exc}")
        return []


def _polish_tasks(
    *,
    model: str,
    api_base: str | None,
    seed: int,
    tasks: list[dict],
    issues: list[Issue],
    context: dict[str, Any],
) -> list[dict]:
    """Re-ask the LLM to regenerate only the tasks that the validator flagged.

    The polish prompt re-uses the same shop context so the LLM has a
    chance to ground the fixes properly. We only replace tasks whose ID
    appears in ``issues``; the rest of the original list passes through
    untouched.
    """
    by_id = {(t.get("id") or ""): t for t in tasks if isinstance(t, dict)}
    flagged: dict[str, list[str]] = {}
    for issue in issues:
        flagged.setdefault(issue.task_id, []).append(f"  - {issue.rule}: {issue.message}")
    if not flagged:
        return tasks

    failing_section = "\n\n".join(
        f"Task {tid} (current intent below) had these issues:\n"
        + "\n".join(flagged[tid])
        + f"\n  Current task JSON:\n  {json.dumps(by_id.get(tid, {}), ensure_ascii=False)}"
        for tid in flagged
    )

    polish_prompt = (
        "Some tasks you previously generated have specific issues. Use the "
        "shop context below to regenerate ONLY the listed tasks, preserving "
        "their IDs but rewriting the intent and success_criteria so the "
        "issues are resolved. Keep the same quality bar (persona opener, "
        "multi-step structure, exact storefront wording).\n\n"
        f"### Failing tasks and their issues\n{failing_section}\n\n"
        f"### Shop context (re-state for grounding)\n"
        f"Top collections (title \u2014 handle):\n{context['collections_list']}\n\n"
        f"Sample products with real option values:\n{context['products_list']}\n\n"
        f"Product-to-Collection memberships:\n{context['mapping_str']}\n\n"
        f"Option patterns:\n{context['option_patterns_list']}\n\n"
        f"Pages:\n{context['pages_list']}\n\n"
        "Respond with a JSON object whose 'tasks' key contains ONLY the "
        "regenerated task objects (one per failing ID), each with id, "
        "type, intent, and success_criteria. Do not include any tasks that "
        "weren't flagged."
    )

    fixes = _llm_generate(model, api_base, SYSTEM_PROMPT, polish_prompt, seed=seed)
    if not fixes:
        log.warning("polish call returned no tasks; keeping original outputs.")
        return tasks

    fixes_by_id = {(f.get("id") or ""): f for f in fixes if isinstance(f, dict)}
    merged: list[dict] = []
    replaced = 0
    for task in tasks:
        tid = task.get("id") or ""
        if tid in fixes_by_id:
            merged.append(fixes_by_id[tid])
            replaced += 1
        else:
            merged.append(task)
    log.info(f"polish round replaced {replaced} task(s) of {len(flagged)} flagged.")
    return merged
