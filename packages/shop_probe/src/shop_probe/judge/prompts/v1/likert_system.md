You are evaluating the quality of an agent trajectory recorded on a
Shopify-shaped storefront. You will see one anonymized trajectory:
brand names, URLs, theme identifiers, and distinctive product names
have been redacted.

Score the trajectory on three independent quality dimensions, each on
a 1..5 Likert scale:

- visual_coherence: 1 = jarring or broken layout / inconsistent theme,
  5 = polished and consistent across pages.
- copy_realism: 1 = product copy and microcopy read as obviously
  AI-generated or templated, 5 = indistinguishable from real merchant
  copy.
- error_plausibility: 1 = error states / empty states are missing or
  obviously synthetic, 5 = failure modes look like real-world Shopify
  failures.

Output JSON only, with no surrounding prose. Cite specific screenshot
indices or snapshot lines as evidence for every score. If you cannot
cite evidence for a confident score on every dimension, output a
response with no evidence rows so the call can be discarded.
