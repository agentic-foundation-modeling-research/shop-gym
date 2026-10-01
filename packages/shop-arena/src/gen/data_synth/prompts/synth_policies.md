You are drafting the storefront's policy pages.

The brand identity is fixed:

```json
{{identity}}
```

Output one JSON array. Each element is an object with exactly these
fields and nothing else:

- `handle`: one of `"privacy-policy"`, `"shipping-policy"`,
  `"terms-of-service"`, `"refund-policy"`. Each handle appears exactly
  once.
- `title`: short display title (2-5 words).
- `body_html`: HTML body. Use semantic tags (`<p>`, `<h2>`, `<ul>`,
  `<li>`). 2-5 short paragraphs per policy. No inline scripts, no
  inline styles, no real-world brands.

Rules:

- Emit all four policies (`privacy-policy`, `shipping-policy`,
  `terms-of-service`, `refund-policy`); every storefront ships the
  full set.
- The shipping policy must name concrete shipping options with flat
  prices and say whether orders above some subtotal ship free; the
  refund policy must give a concrete return window. Later steps derive
  the checkout rules from this text.
- Keep the prose plausible but generic; this is sample data, not legal
  advice.
- Do NOT mention any real-world company, product, jurisdiction, or
  trademark by name.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{{brand_safety}}
