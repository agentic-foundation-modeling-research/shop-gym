You are drafting the storefront's product catalog skeleton: every
product's display name, URL handle, rough price, and which collection
it belongs to. Variants, descriptions, vendors, and images come later;
your job is the catalog's spine.

The collections you must populate are:

```json
{{collections}}
```

Output one JSON array containing exactly {{total_products}} product
skeleton objects. Each object has exactly these fields and nothing
else:

- `title`: plain English noun phrase. **Two to five whitespace-
  separated words.** Numeric size or capacity must be glued to its
  unit with no space: write `"12oz"`, `"7qt"`, or `"7-quart"`, never
  `"12 oz"` or `"7 quart"`. Examples: `"white sport t-shirt"`,
  `"ceramic coffee mug 12oz"`, `"cast iron dutch oven 7qt"`,
  `"leather card wallet"`. Lowercase or Title Case is fine; do NOT
  invent brand names; do NOT include any allowlisted brand token; do
  NOT reference real-world brands or products.
- `handle`: URL-safe slug (lowercase ASCII, hyphens between words,
  no leading/trailing hyphen). Derived from `title`, e.g.
  `"white-sport-t-shirt"`. Handles must be unique across the whole
  array.
- `price`: rough price as a decimal string in the storefront's
  currency, e.g. `"29.99"`. Pick a value that fits the collection's
  positioning; the variant pass refines it later.
- `collection_handle`: handle of the collection this product belongs
  to. Must match exactly one of the handles listed above.

Rules:

- Emit exactly {{total_products}} skeletons, no more, no fewer.
- Each collection's `target_product_count` is the number of skeletons
  you must assign to that collection. The sum across collections
  equals {{total_products}}.
- Titles must be plain descriptive: NO brand-shaped tokens, no proper
  nouns, no real-world products, no model numbers that could be
  trademarks. Pretend you are labeling generic shelf tags.
- Do NOT mention any real-world company, product, jurisdiction, or
  trademark.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{{brand_safety}}
