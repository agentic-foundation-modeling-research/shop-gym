# `synth_product_details` prompt

Used by `shop_gen.data_synth.details.SynthProductDetailsStep` to fill in
the details for one collection's worth of product skeletons — variants,
options, `description_html`, `vendor` (drawn from the fake-brand
allowlist), and `tags`. The step issues one LLM call per collection
(parallel; ≤ 5 concurrent), with one re-prompt allowed per rejection;
the orchestrator fails the step if > 5% of the collection's skeletons
fail validation across both attempts (spec §5.3).

The whole file body is the `str.format()` template; documentation
(this paragraph and the heading above) lives outside it because the
loader returns everything below the first `---` divider.

---

You are filling in the rich product details for one collection of a
storefront's catalog. The catalog skeleton (titles, handles, prices,
collection assignments) is already drafted; your job is to attach the
purchasable shape — variants, options, description HTML, vendor, and
tags — for every product in this collection.

The brand identity is fixed:

```json
{identity}
```

The collection you are populating is:

```json
{collection}
```

The product skeletons you must complete for this collection are:

```json
{skeletons}
```

Output one JSON array containing exactly {product_count} product
detail objects, one per skeleton, **in the same order as the
skeletons above**. Each object has exactly these fields and nothing
else:

- `handle`: must equal the skeleton's `handle` exactly (used to pair
  the detail with its skeleton).
- `description_html`: 1-3 short paragraphs of HTML describing the
  product. Use `<p>`, `<ul>`, `<li>` tags only. No real-world brands.
  No external links. No `<script>` or `<style>` tags. Max 1500
  characters.
- `vendor`: a fake-brand token drawn from this exact allowlist (case
  sensitive): {allowlist}. Pick one that fits the product; the same
  token may be reused across products.
- `product_type`: one short noun phrase classifying the product
  (e.g. ``"jacket"``, ``"mug"``, ``"wallet"``). 1-3 words, lowercase
  or Title Case, plain descriptive — NO brand names.
- `tags`: 2-6 short lowercase tags as plain strings (e.g.
  ``"waterproof"``, ``"insulated"``). No spaces inside a tag (use
  hyphens). No brand names, no real-world products.
- `options`: 1-3 option groups. Each group is an object with:
  - `name`: option group name (e.g. ``"Size"``, ``"Color"``).
  - `position`: 1-indexed integer (1, 2, 3, ...).
  - `values`: 2-6 distinct option values as strings.
- `variants`: 1-12 purchasable variants. Each variant is an object
  with:
  - `title`: variant display title (e.g. ``"Small / Black"``).
  - `sku`: short SKU string or `null`.
  - `price`: decimal price as a string (e.g. ``"29.99"``). Anchor to
    the skeleton's price hint; small per-variant deltas are fine.
  - `compare_at_price`: strikethrough price as a string, or `null`.
  - `available`: boolean.
  - `option1`: selected value for the first option group, or `null`
    when the product has fewer options.
  - `option2`: selected value for the second option group, or `null`.
  - `option3`: selected value for the third option group, or `null`.
  - `position`: 1-indexed integer.
  - `requires_shipping`: boolean.

Rules:

- Emit exactly {product_count} product detail objects — one per
  skeleton, in the same order.
- Every variant's `optionN` must be present in the matching
  `options[N-1].values` list (or `null` when that option group does
  not exist).
- `description_html`, `product_type`, and `tags` are plain
  descriptive: NO brand-shaped tokens (your own fake brand,
  real-world brands, or made-up proper nouns). The brand name lives
  in `vendor` only.
- Do NOT mention any real-world company, product, jurisdiction, or
  trademark.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.
