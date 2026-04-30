# `synth_product_skeletons` prompt

Used by `shop_gen.data_synth.skeletons.SynthProductSkeletonsStep` to
draft the cached product-skeleton payload — every product's title,
handle, price hint, and collection assignment for the catalog. At v0.1
scale (~200 products) the entire catalog fits in one bulk LLM call;
bulk naming makes intra-collection duplicates impossible by
construction.

The whole file body is the `str.format()` template; documentation
(this paragraph and the heading above) lives outside it because the
loader returns everything below the first `---` divider.

---

You are drafting the storefront's product catalog skeleton — every
product's display name, URL handle, rough price, and which collection
it belongs to. Variants, descriptions, vendors, and images come later;
your job is the catalog's spine.

The collections you must populate are:

```json
{collections}
```

Output one JSON array containing exactly {total_products} product
skeleton objects. Each object has exactly these fields and nothing
else:

- `title`: plain English noun phrase. **Two to five whitespace-
  separated words.** Numeric size or capacity must be glued to its
  unit with no space — write ``"12oz"``, ``"7qt"``, or ``"7-quart"``,
  never ``"12 oz"`` or ``"7 quart"``. Examples:
  ``"white sport t-shirt"``, ``"ceramic coffee mug 12oz"``,
  ``"cast iron dutch oven 7qt"``, ``"leather card wallet"``.
  Lowercase or Title Case is fine; do NOT invent brand names; do NOT
  include any allowlisted brand token; do NOT reference real-world
  brands or products.
- `handle`: URL-safe slug (lowercase ASCII, hyphens between words,
  no leading/trailing hyphen). Derived from `title` — e.g.
  ``"white-sport-t-shirt"``.
- `price`: rough price as a decimal string in the storefront's
  currency, e.g. ``"29.99"``. Pick a value that fits the collection's
  positioning; the variant pass refines it later.
- `collection_handle`: handle of the collection this product belongs
  to. Must match exactly one of the handles listed above.

Rules:

- Emit exactly {total_products} skeletons — no more, no fewer.
- Each collection's `target_product_count` is the number of skeletons
  you should assign to that collection. The sum across collections
  equals {total_products}.
- Handles must be unique within each collection. Across collections,
  handle clashes are tolerated (the assembly step disambiguates) but
  prefer distinct handles where natural.
- Titles must be plain descriptive: NO brand-shaped tokens, no proper
  nouns, no real-world products, no model numbers that could be
  trademarks. Pretend you are labeling generic shelf tags.
- Do NOT mention any real-world company, product, jurisdiction, or
  trademark.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{brand_safety}
