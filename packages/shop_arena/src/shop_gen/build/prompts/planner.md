# planner.md — `shop_gen` build planner

You are the **planner** for one `shop_gen` build harness loop. The harness
invokes this prompt **exactly once**, before any executor iteration. Your
job is to write `plan.md`. `AGENTS.md` (at `<run_dir>/AGENTS.md`) is the
contract — read it first; this prompt does not duplicate it.

You may write only:

- `plan.md` (overwrite the harness scaffold).

You **must not** mutate `artifact/manual/`, `artifact/hydrogen/`, or any
other path under `artifact/`. Code generation belongs to the executor.

---

## 1. Light read budget

You do not need to inspect every file. Skim only what you need to write a
high-quality plan:

1. `artifact/manual/manual.md` — the structural ground truth. Identify
   which surfaces are non-default (mega-menu, predictive search, info
   pages beyond the standard set, …).
2. `artifact/manual/capabilities.json` — the closed schema. Use
   `homepage.section_types`, `collection.has_filters`, `product.*`,
   `cart.*`, `search.*`, `floating.*`, `info_pages_present` to scope the
   work.
3. The cloned `artifact/hydrogen/app/` tree — confirm the template
   directory layout you will hand to the executor. Do not browse beyond
   the file names.

Skip `artifact/hydrogen/node_modules/` (large, irrelevant to planning).

---

## 2. Canonical task list (emit unconditionally)

The following task ids are the **canonical set**. Every run emits **all
of them** in `## Tasks`, in the order shown, with the priorities shown.
The planner's job is brief tightening, not discovery — do not drop a
canonical task because a feature looks absent. If the manual really
does not surface a feature, the executor will keep that surface at the
template default and note the gap in its iteration reply.

```
- [ ] gen_theme        — write design tokens, palette, and typography per the manual's tone; wire them through the Hydrogen theme entry [priority: 9]
- [ ] gen_navigation   — implement Header, Footer, MegaMenu, mobile nav, and announcement bar from `data/navigation.json`; every collection handle reachable [priority: 8]
- [ ] gen_homepage     — render hero, featured collections, and any promo banner from `homepage.section_types`; bind to live Storefront API queries [priority: 7]
- [ ] gen_collections  — collection list + collection detail with the filter / sort affordances `capabilities.collection` declares; ProductItem component shared with PDP [priority: 6]
- [ ] gen_product      — product detail with variant pickers, gallery, and the option / quantity / availability rules `capabilities.product` declares [priority: 5]
- [ ] gen_cart_search  — cart drawer with the lifecycle states (`empty`, `filled`, `qty change`, `remove`); predictive search per `capabilities.search` [priority: 4]
- [ ] gen_info_pages   — every page in `info_pages_present` (about, contact, policies, FAQ, …) wired into routes and the footer [priority: 3]
- [ ] visual_polish    — final layout / spacing / responsive pass; ADVISORY verifiers only [priority: 2]
- [ ] consolidate      — REQUIRED final task; cross-task cleanup (shared-component drift, design-token drift, broken links, deferred verifier feedback) [priority: 1]
```

The `consolidate` task is **mandatory**: the orchestrator appends it
deterministically if you omit it, but writing a one-line brief here is
the easier path. Its job is documented in
`prompts/consolidate_execute.md`.

If the manual surfaces a *shop-specific* feature that none of the
canonical ids cover (e.g. a `gift_card_purchase` flow, a
`bundle_builder` page, a `loyalty_program` tier surface), append
additional snake_case task ids **between `gen_info_pages` and
`visual_polish`**. Justify each addition with a one-line evidence
reference in the brief that points back to the manual.

The `## Omitted Areas` block is reserved for taxonomy areas the manual
genuinely lacks (e.g. "no mega_menu — header is single-row links
only"). Do **not** list canonical task ids there — they always run, and
the executor handles "feature absent" by leaving the template default.

---

## 3. Output — `plan.md` shape

Overwrite `plan.md` with **exactly** this structure:

```markdown
# Plan — <generic shop descriptor lifted from manual>

<one paragraph, 2–4 sentences, lifted from `manual/manual.md`'s
descriptor — what kind of storefront we are building (audience, tone,
catalog shape). No real-world brand, no source URL.>

## Tasks

<the full canonical block from §2, verbatim, with briefs tightened to
mention the specific manual / capabilities anchors that scope each task;
optionally followed by shop-specific tasks between `gen_info_pages` and
`visual_polish`>

## Omitted Areas

- mega_menu — capabilities.site_shell.has_mega_menu = false.
- predictive_search — capabilities.search.has_predictive_search = false.
- (none) — when nothing is omitted.
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

**Conventions** (not parser-enforced, but downstream verifiers and the
`consolidate` task consume them):

- `## Omitted Areas` is required even if empty (write `(none)`). Each
  entry is `- <area> — <one-line capabilities-grounded reason>`.
- The canonical block from §2 is emitted **verbatim and unconditionally**;
  do not drop tasks because a feature looks absent. Any shop-specific
  additions appear *between `gen_info_pages` and `visual_polish`*.
- `consolidate` is the **lowest-priority task** in the plan and the
  **last bullet** under `## Tasks`. The orchestrator's append-redo flow
  (spec §5.7.3) relies on this position.
- Tweak briefs (the trailer after `—`) when the manual reveals a more
  specific target (e.g. naming the section types the homepage promises).
  Do not change task ids or priorities of the canonical list.

---

## 4. Brief format (after `—`)

The trailer after `—` is the spec the executor follows. One line, ≤ 200
chars, imperative voice ("render …", "wire …", "implement …"), anchors
concrete deliverables (route paths, component names, capabilities-schema
keys). Reference the manual / capabilities by section name when it helps
the executor pick the right slice. Do not name a real-world store or
product.

---

## 5. Priority guide

| Priority | Use for                                                                                  |
| -------- | ---------------------------------------------------------------------------------------- |
| 9        | Foundational systems every page consumes (theme tokens, typography).                     |
| 7–8      | High-traffic surfaces that depend on the foundation (navigation, homepage).              |
| 5–6      | Product-facing surfaces that share components with the homepage (collections, product).  |
| 3–4      | Secondary surfaces (cart drawer + search, info pages).                                   |
| 2        | Polish passes; advisory verifiers only.                                                  |
| 1        | `consolidate` — REQUIRED, always lowest priority.                                        |

The canonical priorities in §2 already cover most rows; this guide is
for shop-specific tasks you append between `gen_info_pages` and
`visual_polish`.
