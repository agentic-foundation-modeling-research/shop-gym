You are drafting the `store.json` record for a fake storefront.

The brand identity is fixed:

```json
{{identity}}
```

Use it as ground truth: never invent a different name, currency, or
country, and let the descriptor + tone shape the storefront's voice.

Output one JSON object containing exactly these fields and nothing else:

- `domain`: lowercase ASCII storefront domain like
  `"dune-ridge-outfitters.example"`. Use `.example`, `.test`, or
  `.invalid` as the TLD so it cannot resolve to a real site. Hyphens
  between words; no spaces, no underscores.
- `description`: 1-2 sentence storefront description, max 320
  characters. Brand-free aside from the identity name above.
- `payment_settings`: object `{"accepted_card_brands": [...]}` listing
  2-4 SCREAMING_SNAKE_CASE card-brand identifiers
  (e.g. `"VISA"`, `"MASTER"`, `"AMERICAN_EXPRESS"`, `"DISCOVER"`).
- `brand`: object `{"logo_url": null | string, "colors": {"primary":
  hex, "secondary": hex}}`. Hex codes are 7 characters starting with
  `#` (e.g. `"#1f6f43"`). `logo_url` may be `null`.

Rules:

- Do NOT include `shop_id`, `name`, `currency_code`, or `country_code`;
  the orchestrator fills those in from the identity.
- Do NOT mention any real-world company, product, or trademark in
  `description` or anywhere else.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{{brand_safety}}
