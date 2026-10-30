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
- `discount_codes`: 3-5 Discount codes a shopper can type at
  checkout, with at least one of each kind. Each is an object
  `{"code", "kind", "amount", "minimum_subtotal", "hint"}`:
  - `code`: 3-20 uppercase letters and digits (e.g. `"WELCOME10"`).
  - `kind`: `"percentage"` (a percent off the merchandise subtotal),
    `"fixed_amount"` (money off the merchandise subtotal) or
    `"free_shipping"` (the shipping charge becomes zero).
  - `amount`: decimal string. For `percentage`, the percent, above 0
    and below 100 (`"10"` is 10% off). For `fixed_amount`, the money
    off in the storefront's currency, above 0 (e.g. `"5.00"`). For
    `free_shipping`, `"0"`.
  - `minimum_subtotal`: merchandise subtotal before the discount that
    the cart must reach, as a decimal string (e.g. `"40.00"`), or
    `null` for no minimum.
  - `hint`: at most 80 characters of shopper-facing text that says
    what the code does, with its amount and minimum (e.g. `"$5 off
    orders over $40"`).

Rules:

- Handles must be unique within each array.
- No two Discount codes are the same when case is ignored.
- Discount codes must agree with the shipping and refund policies.
  When shipping is free above `free_shipping_threshold`, a
  free-shipping code's minimum must be below it, or the code saves
  nothing. Never offer a code that the policies rule out.
- Do NOT mention any real-world company, product, or trademark.
- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.

{{brand_safety}}
