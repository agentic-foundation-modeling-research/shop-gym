# Fixes for `gen_product`

These rules supersede anything in `execute.md` §3 they contradict.

## Reuse `<Breadcrumbs>`

Render breadcrumb trails through the template's `<Breadcrumbs>`
primitive (`app/components/Breadcrumbs.tsx`) rather than building an
ad-hoc `<nav><ol>` per route:

- **`<Breadcrumbs.FromCollections>`** — the canonical PDP path. Pass
  the product's `collections` (from the Storefront query), the
  `productTitle`, and a `navPriority` array of preferred collection
  handles; the primitive picks the priority winner over the first-
  membership fallback and emits `Home → <collection> → <product>`
  with `aria-current="page"` on the trailing crumb. Every link is
  provably backed by real data — no fabricated mid-crumbs.

Re-deriving the breadcrumb structure inline — especially fabricating
a mid-crumb that is not in `product.collections.nodes` — is a
verifier failure under the same `navigation_primitive_usage` rule.
