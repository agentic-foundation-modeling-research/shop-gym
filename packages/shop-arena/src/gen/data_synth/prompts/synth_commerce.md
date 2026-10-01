You are deriving the checkout rules (`commerce.json`) for a fake
storefront from its identity and its policy pages.

The brand identity is fixed:

```json
{{identity}}
```

The shipping policy is:

```html
{{shipping_policy}}
```

The refund policy is:

```html
{{refund_policy}}
```

The merged capabilities say this about checkout (ground truth when it
names payment methods or shipping options):

```json
{{checkout_capabilities}}
```

Output one JSON object with exactly these fields and nothing else:

- `tax_rate`: fraction of the merchandise subtotal charged as tax,
  between 0 and 0.3 (e.g. `0.08`). Pick a plausible rate for the
  identity's country.
- `free_shipping_threshold`: subtotal (decimal string, e.g. `"75.00"`)
  at or above which shipping is free, or `null` when the shipping
  policy offers no free shipping.
- `shipping_methods`: 1-4 objects `{"handle", "title", "price"}`.
  `handle` is a lowercase slug (e.g. `"standard"`, `"express"`),
  `title` a short display name, `price` a flat rate as a decimal
  string in the storefront's currency. Mirror the options the shipping
  policy names.
- `payment_methods`: 1-4 objects `{"handle", "title"}` (e.g.
  `{"handle": "card", "title": "Credit card"}`). Use generic method
  names only; never a real payment company or wallet brand.

Rules:

- Handles must be unique within each array.
- Do NOT mention any real-world company, product, or trademark.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{{brand_safety}}
