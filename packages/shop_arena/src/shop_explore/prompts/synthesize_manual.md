# synthesize_manual.md — merge per-task notes into a single `manual.md`

You are the **synthesis pass** of the `shop_explore` pipeline. The
plan/execute loop has already run; every executor iteration left a
self-contained note under `artifact/parts/<task_id>.md` plus a partial
capabilities fragment under `artifact/parts/<task_id>.caps.json`. A
deterministic Python step has merged those fragments into the
`Capabilities` document attached below. Your job is to merge the
markdown notes into one cohesive **Shop Manual** body that downstream
consumers (notably `shop_gen`) read as the canonical UX description of
this storefront.

You receive exactly two inputs after this prompt:

1. `## Capabilities` — the merged structured tags as JSON. Treat it as
   ground truth: the prose must not contradict it.
2. `## Per-task parts` — every `parts/<task_id>.md` concatenated in
   sorted filename order, separated by blank lines. The raw `# <task>`
   markers are still present so you can tell the boundaries apart.

This is a **single-shot text generation call**. No browsing, no tool
calls, no follow-up questions. Emit the final `manual.md` body and
stop.

---

## 1. Output contract

- Output is **markdown only**. No JSON envelope, no fenced ```markdown
  wrapper, no commentary before or after.
- Start with a single H1 line:
  `# Shop Manual — <generic descriptor>`
  where `<generic descriptor>` is the anonymized store descriptor
  (e.g. "Premium Outdoor Gear Shop", "Independent Furniture Store").
  Pick it from the `shop` block of capabilities; never use the real
  store name.
- Use H2 (`##`) for each top-level area in this fixed order, skipping
  any area that has no relevant content in either input:
  1. `## Overview` — 2–4 sentences: vertical, scale signals from the
     `shop` block, customer-facing tone.
  2. `## Site shell` — header, footer, mega menu, announcement bar,
     locale switcher (mirror `site_shell` + `intl`).
  3. `## Homepage` — section taxonomy and ordering (`homepage`).
  4. `## Collections & navigation` — collection page UX, filters, sort,
     pagination (`collection`).
  5. `## Product page` — gallery, variant axes, options UX, swatches,
     stock signals (`product`).
  6. `## Cart` — drawer vs page, line-item controls, upsells, surfaces
     (`cart`).
  7. `## Search` — predictive vs full-page, suggestion grouping, empty
     state (`search`).
  8. `## Internationalization` — locale, currency, market switcher
     (`intl`, if not folded into Site shell).
  9. `## Floating UX` — popups, chat, banners (`floating`).
  10. `## Policy & info pages` — which pages exist + their role
      (`info_pages_present`).
- Keep the body **≤ 1200 words total**. The deliverable is a concise
  manual, not a transcript of the parts.
- Always end with a single newline.

## 2. How to merge

- Treat `Capabilities` as the **skeleton**: every truthy boolean / non-
  empty list there must show up somewhere in the prose. If parts
  contradict capabilities, prefer capabilities and silently drop the
  contradicting sentence.
- Treat `Per-task parts` as the **source of qualitative detail**:
  layout descriptions, interaction order, edge cases. Merge
  overlapping observations across tasks; do not list the same fact
  twice.
- If a task fragment is empty or trivially short (e.g. a `[!]` blocked
  task), drop it — note the gap implicitly by leaving that area thin,
  do not add `(blocked)` markers.
- If two parts disagree on a structural fact (e.g. one says the cart
  is a drawer, another a page), trust capabilities and ignore the
  outlier.
- Preserve any `Omitted Areas` style observations only if they are
  user-visible UX gaps (e.g. "no live search suggestions"); drop
  process notes ("we ran out of iterations") — they belong in
  `manifest.json`, not the manual.

## 3. Anonymization (final-pass safety net)

`AGENTS.md` already required executors to anonymize at write time.
This pass is the **last line of defense** before publication. Re-apply
every rule below verbatim while merging:

- **Store name.** Replace any surviving brand mention with a generic
  descriptor matching the `shop` block (e.g. "Luxury Jewelry Store").
- **Product names.** Replace real product names with category-level
  descriptions; keep variant axes (size, color, material), drop
  proper nouns. "Gold Letter Pendant" → "Personalized Letter Charm".
- **Brand references.** Replace with `[Brand]`.
- **People.** Replace named persons with their role — "designer",
  "founder", "collaborator artist".
- **URLs.** No source domain, no absolute URLs. Reference paths only:
  `/cart`, `/collections/<slug-redacted>`, `/policies/refund-policy`.
- **Email / phone / address.** Reduce to the structural fact: "a
  contact form", "a physical address in `<region>`".
- **On-page copy.** Never paste marketing copy verbatim. Summarize the
  *role* and *shape* — "a 1–2 sentence value-prop headline",
  "a 4-bullet feature list".
- **Image captions / alt text.** Describe the *role* of the image, not
  its specific subject beyond category-level facts.

Soft rules that **stay**: currency symbols, locale codes, language
tags, layout numerics (column count, section count, filter count),
aggregated catalog statistics (totals, medians). Generic e-commerce
terminology — "cart drawer", "predictive search", "mega menu" — is
encouraged; that is the vocabulary of the capabilities schema.

A reader of `manual.md` must be unable to identify the source shop.
If you are unsure whether a sentence leaks identity, cut it.

## 4. Style

- Crisp, structural, neutral. No marketing voice. No "we observed";
  write in the present tense about the storefront ("The cart opens
  as a right-side drawer.").
- Prefer bullet lists when describing inventories of features (filter
  facets, locale options, homepage sections); prefer prose when
  describing a flow.
- Reference the capabilities vocabulary directly — say
  "predictive search" not "search-as-you-type", "mega menu" not
  "expanded navigation".
- No internal references (`see parts/...`, `see evidence/...`);
  they would be dangling once the parts are deleted.
- No code fences, no JSON, no tables unless a comparison is genuinely
  clearer as a 2-column table.

## 5. Failure mode

If the inputs are too sparse to produce a meaningful manual (e.g. the
parts are all empty), emit only the `# Shop Manual — <descriptor>`
H1 and a single sentence noting the structural skeleton from
capabilities. The deterministic fallback in `synthesize.py` will
detect a too-short response (< 200 chars) and replace it with the
parts concatenation, so prefer a short-but-honest output to a padded
one.

---

Begin. Output the `manual.md` body now.
