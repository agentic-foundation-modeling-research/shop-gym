# `pair_hardware` pilot reports — T3.2 (M3 gate)

Spec: [`docs/specs/shop_arena/web_probe.md`](../../../docs/specs/shop_arena/web_probe.md) §7 M3
Plan: [`docs/impl/web_probe_implementation.md`](../../../docs/impl/web_probe_implementation.md) **T3.2**

## Run metadata

- **Pair**: `pair_hardware`
- **Source**: `source/hardware` — `https://hardware.shopify.com`
- **Sandbox**: `sandbox/hardware` — `http://localhost:3004` (local Hydrogen serving the
  generated `outputs/shops/mock_hardware` SandboxShop; the Cloud Run URL pinned in
  `cohort.yaml` (`shop-arena-51aad95a-…`) returned 404 at pilot time and is tracked
  in spec §8.5 open question 3)
- **Rubric**: `v1` · hash `dca7e6a776460ed0eec20d2b11b9b7b89e0d30ce48fc90b656c017c09de0347e`
- **Axes**: A + B (axis C lands in M4)
- **Runner**: `shop_probe 0.0.0` · Playwright `1.58.0` · Chromium `145.0.7632.6` ·
  headless · viewport 1280×800

## Top-line numbers

| Target           | `coverage_core` | `coverage_modern` | `coverage_weighted` | `surface.distinct_templates` |
|------------------|-----------------|-------------------|---------------------|------------------------------|
| `source/hardware`  | 0.783 | 0.310 | 0.604 | 32 |
| `sandbox/hardware` | 0.768 | 0.238 | 0.568 | 16 |

Pair-level fidelity (`fidelity.py::compute_pair_fidelity`):

- `coverage_gap_weighted` = `source - sandbox` = **+0.036**
- `surface_ratio` is undefined for `catalog_variants` because the source crawler
  observed `catalog_variants = 0` on `hardware.shopify.com` while the sandbox
  observed 18. The fidelity computation guards on this (raises `ValueError`)
  rather than silently dividing by zero, and the gap is recorded below.

## Files

- `sandbox.json` — full `ProbeReport` for `sandbox/hardware`
- `source.json` — full `ProbeReport` for `source/hardware`
- `evidence/` — per-probe screenshots + DOM snapshots (gitignored)

## Rubric gaps — v1.1 candidates

The 20 probes that fail on **both** sides are the strongest signal that the rubric
itself is brittle (probe under-specified, selector too narrow, or expected pattern
not actually conventional). They should be tightened or dropped in v1.1:

### Both sides fail (rubric / probe gaps — 20 of 61)

| Probe id | Cat | Lvl | Gap notes |
|---|---|---|---|
| `cart.promo_code` | cart | modern | Selector matches only inputs literally named "promo"; many storefronts label this "discount code". |
| `collection.filters.active_chips` | collection | modern | "Active filter" container is a soft pattern; selector list is too narrow. |
| `collection.filters.url_state_sync` | collection | modern | Probe requires `?query` on an `<a>` or a `<form method=get>`; modern SPAs use `history.pushState`. |
| `collection.pagination.present` | collection | core | "Pagination/infinite-scroll/load-more" detector misses scroll-sentinel patterns. |
| `dynamics.cart_count_badge` | dynamics | modern | Header cart-count badge is style-driven; not always semantic. |
| `dynamics.debounced_input` | dynamics | modern | Probes for a literal `data-debounce*` attribute — debounce is almost never a DOM attribute. |
| `dynamics.toast_region` | dynamics | modern | Requires `role=status/alert` with `aria-live`; many sites mount the toast lazily. |
| `dynamics.url_state_sync` | dynamics | modern | Same SPA-state problem as `collection.filters.url_state_sync`. |
| `floating.chat_widget` | floating | modern | Vendor-iframed chat widgets escape selector probes. |
| `floating.cookie_consent` | floating | modern | Late-injected; needs a `waitForFunction` not a snapshot probe. |
| `floating.newsletter_popup` | floating | modern | Time-gated — probe runs before popup shows. |
| `homepage.feature_grid` | homepage | modern | "Feature grid" is too vague; needs concrete heuristics. |
| `i18n.currency_switcher` | i18n | modern | Hardware site has currency under `<select name=country>`; probe doesn't catch that. |
| `media.swatch_image_swap` | media | modern | Looks for `data-*` image hints; modern shops bind via JS state. |
| `product.description.present` | product | core | Description selector list is narrow; both sites render it via headless CMS markup the probe doesn't recognize. |
| `product.gallery.thumbnails` | product | modern | Thumbnails counted only in static markup; many galleries are JS-mounted. |
| `product.recommendations` | product | modern | "Recommendations" section detector misses heading-driven sections. |
| `search.predictive_listbox` | search | modern | Requires both `role=combobox` and `role=listbox`; many shops use `aria-expanded` only. |
| `site_shell.footer.link_group` | site_shell | core | Both footers use unlabeled `<ul>` columns; probe demands `aria-labelledby`. |
| `site_shell.nav.mega_menu` | site_shell | modern | Hover-mounted; probe runs before hover. |

### Sandbox-only failures (real sandbox gaps — 11 of 61)

These are real Hydrogen-template gaps to feed back into ShopArena:

- `cart.line_item.shows_after_add` (core, w=3) — add-to-cart flow doesn't render line items.
- `collection.listing.product_cards` / `product_card_links_to_pdp` (core, w=3 each) —
  collection listings don't expose product cards in the shape the probe expects.
- `dynamics.ajax_cart_endpoint` (core, w=2) — `/cart.js` returns 404 on Hydrogen.
- `a11y.skip_to_content` (core, w=2), `a11y.combobox_role`, `a11y.focus_visible`,
  `a11y.live_region` — accessibility primitives missing from the template.
- `i18n.country_list`, `i18n.locale_switcher` — no market/locale UI.
- `media.lightbox_or_zoom` — no PDP zoom.

### Source-only failures (`hardware.shopify.com` quirks — 9 of 61)

These are a mix of probe brittleness against the *source* and genuine
hardware-site idiosyncrasies (it's a marketing-heavy site, not a vanilla Dawn
storefront). Logged here so we don't over-index on them as sandbox wins:

- `product.title.present` (core, w=3) — PDP doesn't use `<h1>` for product title.
- `cart.line_item.qty_editor`, `cart.line_item.remove` (core, w=2 each) — empty-cart
  page rendered at probe time.
- `collection.filters.sidebar_layout` (core, w=2) — filters inline, not in `<aside>`.
- `homepage.cta_to_collection` (core, w=2) — homepage CTAs route via marketing pages.
- `site_shell.header.logo_links_home` — logo on the configured base URL points to a
  marketing landing page, not `/`.
- `homepage.testimonials`, `homepage.multiple_section_types`, `product.breadcrumbs` —
  modern probes that miss the marketing-site shape.

### Surface-metric gap

- `surface.catalog_variants` for `source/hardware` is **0** while sandbox is **18**.
  The crawler never enumerates a variant — the source PDP variant picker is JS-mounted
  and the crawler's variant detector is static-DOM-only. Fold the variant picker into
  the same JS-aware sweep used for the gallery in v1.1.

## Repro

```bash
# 1. Boot the sandbox locally (in another shell).
cd outputs/shops/mock_hardware/hydrogen && pnpm dev   # serves http://localhost:3004

# 2. Re-run both sides of the pair.
cd packages/shop_probe
uv run shop-probe run http://localhost:3004 \
  --label sandbox/hardware --kind sandbox --pair-id pair_hardware \
  --rubric v1 --axes A,B \
  --out ../../outputs/web_probe/pair_1/sandbox.json \
  --evidence-dir ../../outputs/web_probe/pair_1/evidence/sandbox

uv run shop-probe run https://hardware.shopify.com \
  --label source/hardware --kind source --pair-id pair_hardware \
  --rubric v1 --axes A,B \
  --out ../../outputs/web_probe/pair_1/source.json \
  --evidence-dir ../../outputs/web_probe/pair_1/evidence/source
```
