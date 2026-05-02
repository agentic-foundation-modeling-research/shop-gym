# Fixes for `gen_cart_search`

These rules supersede anything in `execute.md` §3 they contradict.

## Keep the local `/checkout` route as the cart CTA target

The template's `CartSummary` ships with `<CartCheckoutActions
checkoutUrl="/checkout" />` — a hard-coded link to the local
`app/routes/checkout.tsx` page that ships with the template. **Do not
replace that literal with `cart?.checkoutUrl`** when you re-author
`CartSummary.tsx`. The sandbox Storefront API returns `"#"` for
`cart.checkoutUrl` (there is no remote Shopify checkout for a
SandboxShop), so swapping in the dynamic value silently degrades the
button to `<a href="#">` — clicking it does nothing and the bug is
invisible to `tsc` / `build` / route-200 verifiers (the link still
resolves, it just doesn't go anywhere). Keep the literal `/checkout`,
which is the canonical confirmation page for every generated shop.

## Cart drawer summary must not overlap the line items

The drawer pins `.cart-summary-aside` to the bottom of the fixed aside
with `position: absolute; bottom: 0`, and reserves space above it with
`.cart-main { max-height: calc(100vh - var(--cart-aside-summary-height)); overflow-y: auto; }`.
That reservation must cover the **entire** vertical overhead between
the aside top and the summary, not just the summary's own height. At
viewport ≥768px the global reset applies `padding: 2rem 0` to every
`<section>` (and `.cart-main` is a `<section>`), and the aside also
spends ~80px on its header + `main { margin: 1rem }`. A token sized
to the summary alone (e.g. `250px`) leaves the last cart line covered
by the summary box.

When you author/update `app/styles/app.css` for `gen_cart_search`,
set the tokens generously and verify in the live drawer with three
items in the cart that the last item's quantity stepper is visible
above (or scrollable above, never *behind*) the summary box:

```css
:root {
  --cart-aside-summary-height: 460px;
  --cart-aside-summary-height-with-discount: 500px;
}
```

Don't try to shave these by guessing — the summary contains three
`dl` rows + Checkout button + footnote + three trust badges, and any
extra row (free-shipping banner, promo input) widens it further.

## Keep the `Total savings` amount on a single line

`CartSummary.tsx` renders the savings dd as `<>−<Money data={...} /></>`.
Hydrogen's `<Money>` renders a block-level `<div>` by default, which
forces the dollar amount onto a second line under the bare `−` text
node. Make the savings dd a flex container so both children land on
one row:

```css
.cart-summary-row-savings dd {
  color: var(--color-sale, #b3261e);
  display: flex;
  gap: 0.25rem;
  align-items: baseline;
}
```

## Free-shipping banner must use a `success` color, not the accent foreground

`.cart-free-shipping-banner` is a positive status message (subtotal
crossed the threshold). The default accent foreground token
(`--color-accent-fg`) is white — paired with the soft-tint background
the banner uses, that's white-on-light-green and effectively
invisible. Use the success color for the text and a soft-success bg
that pairs with it:

```css
.cart-free-shipping-banner {
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.75rem;
  background: var(--color-success-soft, #e6f0e9);
  color: var(--color-success, #2f6c40);
  font-weight: 600;
  text-align: center;
}
```

Spot-check in the live drawer (subtotal ≥ `FREE_SHIPPING_THRESHOLD`):
the banner text must be clearly readable against its background.

## Don't double-interpolate GraphQL fragments

When you edit the template's existing `app/routes/search.tsx`, the
predictive-search query already interpolates each fragment **exactly
once** at the end of the template literal:

```ts
${PREDICTIVE_SEARCH_ARTICLE_FRAGMENT}
${PREDICTIVE_SEARCH_COLLECTION_FRAGMENT}
${PREDICTIVE_SEARCH_PAGE_FRAGMENT}
${PREDICTIVE_SEARCH_PRODUCT_FRAGMENT}
${PREDICTIVE_SEARCH_QUERY_FRAGMENT}
```

If your edit adjusts what fields a fragment selects, **modify the
fragment definition in place** — do **not** append another
`${PREDICTIVE_SEARCH_*_FRAGMENT}` line. A duplicated interpolation
emits the same `fragment PredictiveProduct on Product { ... }`
declaration twice in one document, which the Storefront API rejects
at request time with `[h2:error:storefront.query] There can be only
one fragment named "PredictiveProduct"` (a runtime 500 that neither
`tsc` nor `build` catches). The same rule applies to any other route
that splices reusable `*_FRAGMENT` constants into a template literal:
read the existing interpolation block before adding to it.
