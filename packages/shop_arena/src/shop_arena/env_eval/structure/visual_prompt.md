# Structural variance visual-judge prompt — v0.1

Used by `shop_arena.env_eval.structure.visual` to compare all cohort screenshots
for one representative page type. The text below the first `---` divider is sent
to the model. Any contract-affecting prompt or response-schema change must bump
`VISUAL_PROMPT_VERSION`.

---

You are comparing screenshots of the same type of e-commerce page from shops
generated from one specification. All images belong to one cohort. The cohort
section maps each image, in the exact order provided, to its integer sample id.

Assess each sample's deviation from the cohort's dominant or shared visual
design. This shared design is a judgment target, not a literal average image.
Judge only visually observable design:

- layout and component arrangement;
- visual hierarchy;
- typography;
- color palette;
- spacing and density;
- visual component treatment.

Ignore product identity, product names and other text semantics, and differences
in the depicted product images. Do not penalize one shop merely because it shows
a different product or uses different copy. Image placement, aspect ratio,
cropping, and framing are layout decisions and should still be compared.

For every mapped sample, assign a distance in `[0, 1]`:

- `0.0`: visually indistinguishable design from the shared cohort design;
- `0.5`: substantial design differences, while the shared design remains clear;
- `1.0`: an extreme outlier with no meaningful visual design in common.

Return every mapped sample exactly once. Give a short rationale for each score
using concrete visual evidence, plus one cohort-level rationale describing the
shared pattern and the main differences. Do not calculate a cohort mean; the
caller calculates all aggregates.

Output only one JSON object in this exact shape:

```json
{
  "shops": [
    {"sample": 0, "distance": 0.0, "rationale": "short explanation"}
  ],
  "rationale": "short cohort-level explanation"
}
```

Do not return markdown, commentary, or keys outside this schema.
