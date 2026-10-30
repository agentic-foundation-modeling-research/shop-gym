You are synthesizing the brand identity for a fake storefront.

The merged capabilities document is the ground-truth feature contract.
The merged manual describes the storefront's UX and policies in prose.

Merged capabilities (JSON):
{{capabilities}}

Merged manual (Markdown):
{{manual}}

Copied catalog (JSON):

```json
{{catalog}}
```

The copied catalog is `null` when the catalog is synthesized later from
this identity. Otherwise the shop sells exactly the products it
summarizes.

Output one JSON object containing exactly these four fields and
nothing else:

- `descriptor`: one short brand-free phrase, max 12 words, no quotes,
  no trailing punctuation. Must match the merged tone and category.
- `tone`: array of 1 to 3 short adjectives or noun phrases capturing
  brand voice. Lowercase preferred; reuse the merged `shop.tone` tags
  when they fit.
- `currency`: ISO 4217 alpha-3 code in uppercase (e.g. `USD`, `EUR`,
  `GBP`). Prefer the merged `shop.currency` when present.
- `country`: ISO 3166-1 alpha-2 code in uppercase (e.g. `US`, `GB`,
  `DE`). Pick the country whose primary currency matches `currency`.

Rules:

- When the copied catalog is not `null`, the descriptor and tone must
  fit its collections, product types and prices, also where the manual
  describes a different category.
- Do NOT include a `name` field. The orchestrator picks the brand
  name from a curated allowlist; any `name` you emit is discarded.
- The descriptor must be brand-free: no real-company proper nouns,
  no trademarks, no celebrity names. The descriptor is a plain
  noun phrase, not a brand-shaped token.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{{brand_safety}}
