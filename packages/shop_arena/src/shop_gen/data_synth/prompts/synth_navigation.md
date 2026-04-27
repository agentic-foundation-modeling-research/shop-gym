# `synth_navigation` prompt

Used by `shop_gen.data_synth.navigation.SynthNavigationStep` to draft the
storefront's `navigation.json` payload — the `main-menu` and `footer`
menus that link to collections and content pages. Conditioned on the
synthesized collections (so every category is reachable from the
header), the synthesized pages (so the footer surfaces the storefront's
content pages), and the merged capabilities (so the menu structure
respects the manual's promised IA).

The whole file body is the `str.format()` template; documentation
(this paragraph and the heading above) lives outside it because the
loader returns everything below the first `---` divider.

---

You are drafting the storefront's navigation menus.

The synthesized collections (every category the storefront ships) are:

```json
{collections}
```

The synthesized content pages (about / contact / FAQ / etc.) are:

```json
{pages}
```

The merged capabilities document — ground truth for the storefront's
information architecture — is:

```json
{capabilities}
```

Output one JSON object with exactly these top-level keys and nothing
else: `"main-menu"` and `"footer"`. Each value is an array of
navigation items. Each navigation item is an object with exactly these
fields and nothing else:

- `title`: short display label (1-3 words).
- `url`: absolute path. Collections must use `/collections/<handle>`
  (e.g. `/collections/outerwear`). Pages must use `/pages/<handle>`
  (e.g. `/pages/about`). Policies must use `/policies/<handle>`. The
  storefront root is `/`.
- `type`: one of `"COLLECTION"`, `"PAGE"`, `"BLOG"`, `"PRODUCT"`,
  `"HTTP"`. Use `"COLLECTION"` for collection links, `"PAGE"` for
  content-page and policy links, and `"HTTP"` for top-level groupings
  whose own URL is just `/` (a heading whose children carry the real
  links).
- `children`: array of nested navigation items. Use `[]` for leaf
  links. Nest at most one level deep.

Rules:

- The `main-menu` MUST link to every collection in the supplied
  collections array — either as a top-level item or as a child of a
  top-level grouping. Use the exact `/collections/<handle>` URL for
  each collection. Missing a collection is a hard error.
- A `main-menu` may also include a "Home" entry pointing at `/`
  (`type: "HTTP"`) and at most one or two grouping headers
  (`type: "HTTP"`, `url: "/"`) whose children are the collection
  links. Do not nest groupings inside groupings.
- The `footer` SHOULD link to the supplied content pages
  (`/pages/<handle>` with `type: "PAGE"`). It may additionally link to
  policies, but the storefront's policy pages are out of scope for
  this prompt — emit only what the supplied pages array contains.
- Titles must be plain descriptive. Do NOT mention any real-world
  company, product, or trademark.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.
