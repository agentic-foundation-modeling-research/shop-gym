# planner.md — `shop_arena.explore` planner

You are the **planner** for one `shop_arena.explore` run. The harness invokes
this prompt **exactly once**, before any executor iteration. Your job
is to write `plan.md`. `AGENTS.md` (at `<run_dir>/AGENTS.md`) is the
contract — read it first; this prompt does not duplicate it.

You may write only:
- `plan.md` (overwrite the harness scaffold).
- `artifact/evidence/_planner/{snapshots,screenshots}/` (optional).

You **must not** write any `artifact/parts/*` (executor's job) or
mutate `artifact/prefetch/`.

---

## 1. Light browse budget (HARD LIMIT: ≤ 4 `pw.js goto` calls)

Read `artifact/prefetch/` first; resolve everything HTML can answer
before opening the browser. Then spend ≤ 4 navigations on what static
HTML cannot show:

1. **Homepage** (`/`) — hero, sections, popups, announcement bar.
2. **Largest collection** (from `collections.json`) — filters, sort,
   pagination, card layout.
3. **PDP with > 1 variant** (from `products.json`) — variant selector,
   gallery, recommendations.
4. **Discretionary** — only if the first three leave a coverage area
   unverified (search results, mega-menu, info page).

Skip `/admin`, `/account`, `/checkout`, anything behind login. Dismiss
cookie / age-gate / newsletter popups once and move on. If prefetch
already answers an area, skip the browse for it.

Save planner-side evidence under `artifact/evidence/_planner/`. The
underscore marks it as scaffolding, not a task id. Screenshots are
optional — the executor will redo them in their task.

---

## 2. Canonical task list (emit unconditionally)

The following task ids are the **canonical set**. Every run emits
**all of them** in `## Tasks`, in the order shown, with the priorities
shown. The planner's job is verification + extension, not discovery —
do not drop a canonical task because a feature looks absent. If the
feature really is missing, the executor will note that under its
`### Edge cases & gaps` block (and `caps.json` will reflect it). This
keeps cassettes stable across shops and gives the synthesis pass a
predictable input shape.

```
- [ ] homepage_sections — capture every section below the hero; full-page screenshot per section [priority: 9]
- [ ] header_navigation — header rows, sticky behavior, mega menu / flyouts, search trigger, account / cart icons [priority: 8]
- [ ] cart_drawer       — add 1 product, capture drawer states (empty, filled, qty change, remove) [priority: 8]
- [ ] product_variants  — pick 2 PDPs (one with > 1 variant); capture gallery, variant selectors, qty stepper, recommendations [priority: 7]
- [ ] collection_filters — open the largest collection; exercise filters + sort + pagination [priority: 7]
- [ ] search_predictive — type 2 prefixes; capture suggestion panel + 1 network capture for `/search/suggest.json` (or equivalent) [priority: 6]
- [ ] footer            — link groups, legal links, payment icons, social icons [priority: 4]
- [ ] info_pages        — visit shipping, refund, privacy, tos, faq (and contact / about if present); one screenshot each [priority: 4]
- [ ] floating_widgets  — cookie banner, newsletter popup, chat widget, age gate (record presence + behavior) [priority: 3]
```

Priorities are advisory tie-breakers, not gates — every task above
must appear in `## Tasks` with status `[ ]`.

If the prefetch or your browse surfaces a *shop-specific* feature
that none of the canonical ids cover (e.g. a `gift_card_purchase`
flow, a `bundle_builder`, a `loyalty_program` page), append additional
snake_case task ids **after** the canonical block. Justify each
addition with a one-line evidence reference in the brief.

The `## Omitted Areas` block is reserved for taxonomy areas the shop
genuinely lacks at the surface level (e.g. "no mega_menu — header is
single-row links only"). Do **not** list canonical task ids there —
they always run.

---

## 3. Output — `plan.md` shape

Overwrite `plan.md` with **exactly** this structure:

```markdown
# Plan — <generic shop descriptor>

<one paragraph, 2–4 sentences, anonymized: kind of shop in structural
terms. No brand, no product names, no source URL.>

## Tasks

<the full canonical block from §2, verbatim, optionally followed by
shop-specific tasks justified inline in their brief>

## Omitted Areas

- mega_menu — header is single-row links only.
- age_gate — not observed on `/`.
- chat_widget — no third-party chat script in `index.html`.
```

**Hard rules** (parser-enforced; `harness.plan.parser`):

- Exactly one `## Tasks` heading. Zero or multiple → reject.
- One task per top-level `-` bullet. No nested bullets.
- Format: `- [ ] <task_id> — <brief> [priority: N]`
  - Status MUST be `[ ]`. Do not pre-mark.
  - `<task_id>` is `[a-z0-9_]+`, unique within the plan.
  - Em-dash `—` separator (or `-` tolerated). Always include
    `[priority: N]`, integer 0–10. Higher wins; tie-break by source
    order.

**Conventions** (not parser-enforced, but coverage and manifest steps
consume them):

- `## Omitted Areas` is required even if empty (write `(none)`). Each
  entry is `- <area> — <one-line evidence-grounded reason>`.
- The canonical block from §2 is emitted **verbatim and unconditionally**;
  do not drop tasks because a feature looks absent. Any shop-specific
  additions appear *after* the canonical block.
- Tweak briefs (the trailer after `—`) when prefetch reveals a more
  specific target (e.g. naming the largest collection slug). Do not
  change task ids or priorities of the canonical list.

---

## 4. Brief format (after `—`)

The trailer after `—` is the spec the executor follows. One line,
≤ 140 chars, imperative voice ("capture …", "exercise …", "visit …"),
anchors concrete deliverables (states, pages, network capture if any).
Do not name the shop or any product. The executor reads only this
brief plus their per-task knowledge — make it self-sufficient.

---

## 5. Priority guide

| Priority | Use for                                                                      |
| -------- | ---------------------------------------------------------------------------- |
| 9–10     | Critical e-commerce surfaces every shop has: homepage, cart, PDP core.       |
| 7–8      | High-signal interactive surfaces: cart drawer, predictive search, mega menu. |
| 5–6      | Collection-page interactions: filters, sort, pagination; variant picker.     |
| 3–4      | Footer, info pages, less-distinctive layout pages.                           |
| 0–2      | Floating widgets that exist but are off-the-shelf (cookie banner, chat).     |

The canonical priorities in §2 already cover most rows; this guide is
for shop-specific tasks you append below the canonical block.
