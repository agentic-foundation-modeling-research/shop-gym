You are naming the variants of one product in an online shop catalog.
The source lists {{variant_count}} variants of this product, but it does
not say how they differ. Infer the one option that most likely tells the
variants apart, and give one value for each variant.

The product is:

```json
{{product}}
```

The product gives its `title`, `category_path` (most general first),
`brand`, `description`, `bullets` (the feature list), `attributes`, and
`variant_count`.

Output one JSON object with exactly these fields and nothing else:

- `name`: the option name, one to three words in title case, for example
  `Platform`, `Edition`, `Color`, `Size`, `Style`, `Capacity` or
  `Bundle`.
- `values`: exactly {{variant_count}} values of that option, one per
  variant. Each value is one to five words.

Rules:

- **Grounded**: use the option and the values that the product facts
  show or suggest (for example the platforms, editions, colors or sizes
  that the title, the description or the bullets name). When the facts
  do not show them, choose the option and the values that are most
  usual for this kind of product.
- **Distinct**: every value is different from the other values.
- **Plain**: no prices, no stock words (for example "in stock" or
  "sold out"), no HTML, no markdown, no emoji.
- Output JSON only. No markdown code fences, no commentary, no trailing
  prose.
