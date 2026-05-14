# Fixes for `gen_collections`

These rules supersede anything in `execute.md` §3 they contradict.

## Reuse `<Breadcrumbs>`

Render breadcrumb trails through the template's `<Breadcrumbs>`
primitive (`app/components/Breadcrumbs.tsx`) rather than building an
ad-hoc `<nav><ol>` per route:

- **`<Breadcrumbs.FromMatches>`** — for collection-list and other
  non-PDP routes. Pass `useMatches()` plus a `crumbBuilders` map
  keyed by route id; unknown ids are silently skipped so a single
  call site can serve a layout that hosts heterogeneous child
  routes.

Re-deriving the breadcrumb structure inline — especially fabricating
a mid-crumb that is not in `product.collections.nodes` — is a
verifier failure under the same `navigation_primitive_usage` rule.
