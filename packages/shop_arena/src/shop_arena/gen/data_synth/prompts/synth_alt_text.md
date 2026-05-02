# `synth_alt_text` prompt

Used by `shop_arena.gen.data_synth.alt_text.SynthAltTextStep` to author alt-text
strings for one collection's products. The step issues one LLM call per
collection (parallel; ≤ 5 concurrent) and asks for `images_per_product`
distinct alt-text strings per product, used by `gen_images` and embedded
in `products[].images[].alt`.

The whole file body is the `str.format()` template; documentation
(this paragraph and the heading above) lives outside it because the
loader returns everything below the first `---` divider.

---

You are authoring image alt-text for one collection of a storefront's
catalog. The catalog skeleton (titles, handles, prices) and product
details (variants, options, vendor, tags) are already drafted; your job
is to write {images_per_product} short, plain-descriptive alt-text
strings for each product so the upstream image generator can render
them and the storefront can use them as accessibility labels.

The collection you are populating is:

```json
{collection}
```

The products in this collection (skeleton + detail merged) are:

```json
{products}
```

Output one JSON array containing exactly one object per product handle
listed above (every handle must appear, no extras). Each object has
exactly two fields and nothing else:

- ``handle``: the product handle, copied verbatim from the products
  list above.
- ``alts``: an array of exactly {images_per_product} alt-text strings,
  in display order.

Each alt-text string has these constraints:

- **Length**: between {min_chars} and {max_chars} characters
  (inclusive). Short alt text fails screen readers; long alt text
  fails most CMS validators.
- **Plain descriptive**: describe what the picture shows — material,
  color, framing, surface, posture — using common nouns and
  adjectives. NO brand names (your fake brand, real-world brands, or
  invented proper nouns), NO product titles repeated verbatim, NO
  trademarks, NO model numbers, NO real-world companies or
  jurisdictions.
- **Distinct**: the {images_per_product} strings for one product
  must each describe a different shot — e.g. front view on a wooden
  bench, close-up of the stitched seam, draped across a chair back.
  Do not repeat one description with minor punctuation differences.
- **No HTML, no markdown, no emoji.** Do not put any double-quote
  character (``"``) inside the alt-text value — it breaks JSON
  parsing. Use plain words only. If you would normally quote a
  phrase, drop the quotes.

Rules:

- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.
- Cover every product handle. Missing handles fail the step.
- Do not invent extra handles. Extra entries fail the step.
- Each handle appears **exactly once** in the output array. Duplicate
  handles fail the step.

{brand_safety}
