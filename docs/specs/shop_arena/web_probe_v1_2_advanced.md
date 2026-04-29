# `web_probe` v1.2 — `advanced` (behavioral) tier

Status: **Draft (proposed)** · Applies to: `docs/specs/shop_arena/web_probe.md` v0.1
Owners: ShopGym
Last updated: **2026-04-29**

## Overview

ShopProbe today is a **structural fidelity** instrument. The shipped rubric
(`v1.yaml`, 61 probes; `v1.1.yaml`, 66 probes with the auth + checkout slice)
asserts presence of UI primitives — does the page have a `<select>` for sort,
an `input[type=checkbox]` for filters, a `data-cart-count` element in the header.
It does **not** verify those primitives actually work. Across the 28 `v1`
reports under `outputs/shop_probe/result/reports/`, sandbox shops score 0.000
on `coverage_advanced` because that bucket is intentionally empty in v1
(`web_probe.md` §5.3).

This spec defines `rubric/v1.2.yaml`, an 8-probe `level: advanced` expansion.
v1.2 layers behavioral assertions on top of v1.1's 66 entries → 74 total.
Every probe drives an interaction (click, type, navigate) and asserts that
the page state actually changes.

## Terminology

- **Presence probe** — asserts that an element matching a CSS / ARIA selector
  exists in the DOM. Cheap, deterministic, theme-tolerant. The full v1 +
  v1.1 rubric is presence-only with two small exceptions (cart line-item
  flow + `/cart.js` HTTP fetch).
- **Behavioral probe** — drives an interaction (click / type / navigate)
  and asserts that the resulting page state differs from the baseline.
  Stricter than presence; can fail on a non-functional implementation
  even when the markup looks correct.
- **`level: advanced`** — third tier defined by `web_probe.md` §5.3 alongside
  `core` and `modern`. v1 deferred this tier; v1.2 lights it up with
  behavioral probes.
- **`passed=None` / not-applicable** — `ProbeOutcome.passed` carries `True`,
  `False`, or `None`. `None` means the probe ran but the storefront does
  not expose the surface required to assert a result (e.g. a sort probe
  on a collection with one product). The runner excludes `None` results
  from coverage aggregation per `_runner.py:69-93`.

## Current Status

Implemented surface (as of v1.1):

```
v1   (61 probes) — core + modern, presence-only.
                   Used by all 28 reports in outputs/shop_probe/result/reports/.

v1.1 (66 probes) — v1 + 5 auth/checkout entries (account.*, checkout.*),
                   gated behind --include-auth.

           level: advanced ───── empty bucket ─────────────────► 0
```

Two probes today drive real interactions:

- `cart.line_item.shows_after_add` (and the two siblings) — clicks
  add-to-cart, navigates to `/cart`, asserts the line item is present.
- `dynamics.ajax_cart_endpoint` — HTTP-fetches `/cart.js` and verifies the
  JSON shape.

Everything else is DOM presence. As a result, a storefront could pass
`collection.listing.has_sort` while shipping a non-functional `<select>`,
and `coverage_weighted` would not notice.

## Desired Status

```
v1   (61 probes)  ─── unchanged
v1.1 (66 probes)  ─── unchanged
v1.2 (74 probes)  ─── v1.1 + 8 behavioral probes at level: advanced

           level: advanced ───── 8 probes, weight total 14 ───► non-zero
```

After v1.2:

- `coverage_advanced` becomes a meaningful axis — it answers "do the
  primitives the storefront advertises actually fire."
- A storefront that passes `collection.listing.has_sort` but ships a
  broken sort dropdown drops 2 weight units on
  `collection.sort.changes_order`, and that gap shows up in the report.
- v1 + v1.1 reports remain reproducible against their original rubrics
  (content-addressable hash invariant per spec §5.8).

## Proposal

### 1. Rubric file

New file `packages/shop_arena/src/shop_probe/rubric/v1.2.yaml`:

- Verbatim copy of v1.1's 66 entries (same hashes, same probe callables).
- 8 new entries appended, all `level: advanced`, all `authenticated:
  false`, `transactional: false`.
- `version: v1.2` in the header.
- Content-addressable: SHA-256 of raw bytes pinned in
  `tests/shop_probe/test_rubric_v1_2.py`.

### 2. The 8 advanced probes

Every probe follows the same skeleton: capture a baseline, drive the
interaction, capture the result, return a clean `True/False/None`. On any
shape the probe cannot exercise (no sort dropdown, single-product
collection, missing sample URL) the probe returns `passed=None` so the
runner excludes it from aggregation. False is reserved for "the
interaction ran but state did not change as expected."

| id | category | weight | What the interaction does | What the assertion checks |
|---|---|---|---|---|
| `collection.sort.changes_order` | collection | 2 | Toggle sort `<select>` to a different option, wait for the page or DOM to settle | First product card title differs from the baseline |
| `collection.filters.applies_to_results` | collection | 2 | Click the first available filter input | Product card count changed **or** URL gained a filter param |
| `collection.pagination.advances` | collection | 1 | Click pagination next / load-more | First card href differs (paged) **or** card count grew (load-more) |
| `collection.filters.url_state_advances` | collection | 2 | Click the first filter input | `page.url` mutated to include `?` / `&` |
| `product.variant.swap_updates_state` | product | 2 | Click the second variant swatch / radio | Price text **or** main gallery img src changed |
| `product.qty.spinner_increments` | product | 1 | Click `+` button (or `el.stepUp()`) | Numeric qty value increased |
| `search.predictive.populates_listbox` | search | 2 | Focus header search, type a 3-char debounced query | Listbox has ≥ 1 visible option within 1500 ms |
| `dynamics.cart_count_badge_updates` | dynamics | 2 | ATC sample PDP via existing cart-flow helper | Header badge text changed (numeric increase or empty → non-empty) |

Total weight added: **14** (collection +7, product +3, search +2, dynamics +2).

### 3. CLI / runner changes

**None required.** The aggregation logic in `cli.py:577-620` already
initializes `by_level["advanced"]` and emits `coverage_advanced` from
the same path as `coverage_core` / `coverage_modern`. The loader
(`rubric/loader.py:_resolve_rubric_arg`) already accepts any packaged
rubric file by name. A user opts into v1.2 with `--rubric v1.2`.

`--include-auth` semantics are unchanged: v1.2's 8 advanced probes are
all `authenticated: false` / `transactional: false`, so they ship
without the gate.

### 4. Failure modes the probes defend against

Three patterns surface specifically because behavioral probes are
stricter than presence:

1. **Async UI**. Filter clicks re-render results after a fetch. Probes
   use Playwright's `page.wait_for_url()` when URL change is the
   assertion or `locator.wait_for(state="visible")` on the new element.
   Each wait has a hard 3-second ceiling so a missing event does not
   blow the 10-second probe timeout.
2. **Theme variance**. Real Shopify themes implement sort as `<select>`,
   custom popover button, or anchor list. Behavioral probes match the
   selector union of the corresponding presence probe; a no-match
   returns `passed=None`, never `False`.
3. **Insufficient sample data**. A collection with one product cannot
   exercise sort. A PDP with one variant cannot exercise variant swap.
   Probes count the precondition before driving the interaction; below
   the minimum, return `passed=None`.

Each `passed=None` carries a structured note (`"only 1 product card in
sample collection — sort cannot be exercised"`) so the report reader
can distinguish "feature broken" from "not enough data to test".

## Alternative

**Upgrade existing presence probes in place** — replace
`collection.listing.has_sort` with the behavioral assertion. Rejected:
breaks comparability with the 28 existing v1 reports, conflates two
fidelity dimensions in one rubric entry, and makes real shops with
quirky sort UIs (anchor lists, custom popovers) drop weight without a
clean way to attribute the loss.

## Milestones

| Milestone | Deliverables |
|---|---|
| **M1** | `rubric/v1.2.yaml` written with 74 entries; `tests/test_rubric_v1_2.py` pins hash, count, category distribution, level invariants. Hash + structural tests green. |
| **M2** | 8 probe functions implemented across `probes/collection.py`, `probes/product.py`, `probes/search.py`, `probes/dynamics.py`. Strict `pyright` + `ruff` clean. |
| **M3** | Smoke run: `shop-probe run --rubric v1.2` against one sandbox + one real shop. Report shows `coverage_advanced` non-zero (or all 8 `passed=None` for a thin shop — both are valid signals). Evidence directories contain before/after screenshots for each advanced probe. |
| **M4** *(optional)* | Re-run the cohort under `outputs/shop_probe/result/` against v1.2; produce a follow-up `result_v1_2.md` analysis covering the new always-fail / always-pass tables. |

M1–M3 are the foundation. M4 is gated on cohort runtime budget.

## Appendix

### A.1 Reference behavioral probe shape

```python
async def sort_changes_order(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """Toggling the collection sort control changes the first card's title."""
    if ctx.sample_collection_url is None:
        return ProbeOutcome(passed=None, notes="no sample_collection_url provided")
    await page.goto(ctx.sample_collection_url, wait_until="domcontentloaded")
    cards = page.locator(
        '[class*="product-card"], article[class*="card"], '
        'li[class*="grid__item"]:has(a[href*="/products/"])'
    )
    if await cards.count() < 2:
        return ProbeOutcome(passed=None, notes="< 2 product cards; cannot exercise sort")
    sort = page.locator(
        'select[id*="sort" i], select[name*="sort" i], select[aria-label*="sort" i]'
    ).first
    if await sort.count() == 0:
        return ProbeOutcome(passed=None, notes="no <select>-shaped sort control")
    options = sort.locator("option")
    if await options.count() < 2:
        return ProbeOutcome(passed=None, notes="sort <select> has <2 options")
    before = (await cards.first.inner_text()).strip()
    before_shot = await ctx.screenshot("before-sort")
    before_snap = await ctx.snapshot("before-sort")
    other_value = await options.nth(1).get_attribute("value")
    if other_value is None:
        return ProbeOutcome(passed=None, notes="sort option has no value attribute")
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=3000):
        await sort.select_option(other_value)
    after = (await cards.first.inner_text()).strip()
    after_shot = await ctx.screenshot("after-sort")
    after_snap = await ctx.snapshot("after-sort")
    passed = before != after
    return ProbeOutcome(
        passed=passed,
        evidence=(before_shot, before_snap, after_shot, after_snap),
        notes=None if passed else f"first card title unchanged after sort: {before!r}",
    )
```

### A.2 Hash + count pinning

After writing `v1.2.yaml`, pin in `tests/shop_probe/test_rubric_v1_2.py`:

```python
EXPECTED_V1_2_HASH: str = "<sha256 of raw bytes>"
EXPECTED_V1_2_VERSION: str = "v1.2"
EXPECTED_V1_2_PROBE_COUNT: int = 74
EXPECTED_V1_2_ADVANCED_COUNT: int = 8
EXPECTED_V1_2_CATEGORY_COUNTS: dict[str, int] = {
    "site_shell": 6, "homepage": 5, "collection": 12,  # 8 v1 + 4 advanced
    "product": 12, "search": 6, "cart": 6, "i18n": 3, "floating": 3,
    "dynamics": 6, "a11y": 6, "media": 4, "account": 3, "checkout": 2,
}
```

### A.3 Out of scope

- Auth/checkout probes — v1.1's job, kept unchanged.
- Backfilling v1 reports against v1.2 — v1 reports remain valid against
  their own rubric. v1.2 vs v1.2 is the comparison axis going forward.
- Tightening existing `core`/`modern` presence probes in place.
- Mock HTML fixtures — codebase has none; spec calls for integration-only
  testing against real storefronts. v1.2 inherits this convention.
