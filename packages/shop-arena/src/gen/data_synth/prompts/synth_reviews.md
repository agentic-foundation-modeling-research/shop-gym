You are writing product reviews for a fake storefront. Code has already
planned each review: the product, the variant the reviewer bought, and
the star rating are fixed. Your job is to write only the title and the
text of each review, so that the words agree with the product and the
rating.

The products, each with the reviews to write, are:

```json
{{products}}
```

Each product gives its `title`, `product_type`, `tags`, and
`description_html`. Each of its `reviews` gives an `id`, a `rating`
from 1 (worst) to 5 (best), and the `variant` the reviewer bought.

Output one JSON array containing exactly one object per review id
listed above (every id must appear, no extras). Each object has exactly
these fields and nothing else:

- `id`: the review id, copied verbatim from the list above.
- `title`: a short headline of {{title_min}} to {{title_max}}
  characters.
- `body`: the review text, one to four plain sentences of
  {{body_min}} to {{body_max}} characters.

Each review has these constraints:

- **Rating**: the words match the rating. 5 is delighted, 4 is happy
  with a small reservation, 3 is mixed, 2 is disappointed, 1 is very
  unhappy.
- **Grounded**: mention only features, materials, and uses that the
  product facts support. A review may name the variant bought (for
  example the size or the color) and tell how it fits or works.
- **Distinct**: the reviews of one product talk about different things
  (fit, quality, look, comfort, value, how it lasted). Do not repeat a
  title.
- **First person**: write as a shopper who owns the product. Do not
  name the reviewer, the shop, the vendor, or any brand. Do not mention
  prices, discounts, shipping, or other reviews.
- **No HTML, no markdown, no emoji.** Do not put any double-quote
  character inside a value. Use plain words only.

Rules:

- Output JSON only. No markdown code fences, no commentary, no
  trailing prose.
- Cover every review id. Missing ids fail the step.
- Do not invent extra ids, and give each id **exactly once**. Extra or
  repeated ids fail the step.

{{brand_safety}}
