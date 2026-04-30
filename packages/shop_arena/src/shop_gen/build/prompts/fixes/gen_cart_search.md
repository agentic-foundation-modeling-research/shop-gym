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
