# `synth_collections` prompt

Used by `shop_arena.gen.data_synth.collections.SynthCollectionsStep` to draft
the cached collections payload — the storefront's category records
(``"outerwear"``, ``"kitchen tools"``, …). Conditioned on the merged
capabilities (which surfaces the category list the manual promises),
the synthesized identity (so the prose voice matches), and the merged
stats priors (so per-collection product counts add up to the catalog
budget).

The whole file body is the `str.format()` template; documentation
(this paragraph and the heading above) lives outside it because the
loader returns everything below the first `---` divider.

---

You are drafting the storefront's collections (categories).

The brand identity is fixed:

```json
{identity}
```

The merged capabilities document — ground truth for the categories the
manual promises — is:

```json
{capabilities}
```

The merged stats priors — typical scale of the seeds — are:

```json
{stats}
```

Output one JSON array containing exactly {target_count} collection
objects. Each object has exactly these fields and nothing else:

- `title`: short plain-descriptive category name (1-3 words). Examples:
  ``"outerwear"``, ``"kitchen tools"``, ``"trail running"``. Lowercase
  or Title Case is fine; do NOT include any brand name (your own or
  anyone else's). Use only common-noun phrases.
- `handle`: URL-safe slug (lowercase ASCII, hyphens between words,
  no leading/trailing hyphen). Derived from `title` — e.g.
  ``"trail-running"``.
- `description`: 1-2 sentence plain-text description of what the
  collection contains, in the identity's voice. Max 240 characters.
  No HTML. No real-world brands.
- `sort_order`: one of ``"manual"``, ``"best-selling"``,
  ``"created-desc"``, ``"price-asc"``, ``"price-desc"``,
  ``"alpha-asc"``.
- `target_product_count`: integer, the rough number of products this
  collection should contain. Must be at least 1. The sum across all
  collections should approximate the catalog's total product budget
  (see ``stats.products_total`` above; if it is zero or missing,
  budget for ~200 products spread across the {target_count}
  collections).

Rules:

- Emit exactly {target_count} collections — no more, no fewer.
- Handles must be unique within the array.
- Titles must be plain descriptive: NO brand-shaped tokens (your own
  fake brand, real-world brands, or made-up proper nouns). Pretend
  you are labeling shelves in a generic store.
- Cover the categories the merged capabilities mention; you may add
  general-purpose collections to round out the catalog.
- Do NOT mention any real-world company, product, jurisdiction, or
  trademark.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{brand_safety}
