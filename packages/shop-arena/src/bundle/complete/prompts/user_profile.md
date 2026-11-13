You are writing the profile of one shopper of an online shop, from what
the shopper bought and reviewed. The profile describes the shopper as of
{{cutoff}}. Later, other writers use it to state shopping needs that
this shopper would have in this shop, so it must fit the history below
and the catalog of the shop.

The catalog of the shop has these categories (a category path, most
general first, and the number of products under it), most products
first:

```json
{{categories}}
```

Prices in the catalog go from {{price_min}} to {{price_max}}
{{currency}}. The median price is {{price_median}} {{currency}}.

The history of the shopper before {{cutoff}}, oldest first:

```json
{{history}}
```

Each history item gives the `date`, the `product` (its `title`, `brand`,
`category_path` and `price`), `bought` (true when the shopper bought
it), and the `review` that the shopper wrote, if any (`rating` from 1 to
5, `title` and `text`).

Output one JSON object with these fields:

- `demographics`: what the history suggests, each field optional:
  `age_range` (for example `25-34`), `gender`, `location` (`country` as
  an ISO 3166 code and `region`), and `household` (for example
  `["partner", "child"]`).
- `preferences`:
  - `price_sensitivity`: `budget`, `mid` or `premium`, compared with the
    catalog prices above.
  - `category_interests`: one to five category paths. Each one is a
    category path from the list above, or the first part of one, with
    the names copied exactly.
  - `brand_preferences`: the brands that the shopper buys again or
    praises, copied from the history. An empty list when there are
    none.
  - `focus_aspects`: two to five things that the shopper cares about,
    for example `battery life` or `value for money`.
- `sizes`: optional, only when the history shows sizes, for example
  `{"shoes_us": "9"}`.
- `habits`: short facts as text values, for example
  `{"shop_frequency": "monthly", "reviews": "often"}`.
- `narrative`: two to four plain sentences, in the third person, about
  who the shopper is, what they use the products for, and how they
  shop.

Rules:

- **Grounded**: every fact follows from the history. When the history
  does not show a demographic fact, leave that field out.
- **No account fields**: no name, email, password, phone number, street
  address or other contact details, in any field or in the narrative.
- **No later facts**: do not name products or events after {{cutoff}}.
- **Plain**: no HTML, no markdown, no emoji.
- Output JSON only. No markdown code fences, no commentary, no trailing
  prose.
