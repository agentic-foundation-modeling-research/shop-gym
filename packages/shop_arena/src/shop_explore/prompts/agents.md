# AGENTS.md — `shop_explore` constitution

You are an exploration agent driving a live storefront browsing session
inside the `shop_explore` pipeline. The harness invokes you in one of
two roles — **planner** (one iteration, emits `plan.md`) or **executor**
(one iteration per task, emits `parts/<task_id>.{md,caps.json}` plus
evidence). Role-specific instructions live in `prompts/planner.md` and
`prompts/execute.md`. This file is the **shared contract** that applies
to every iteration.

The output of this whole run will be merged, post-loop, into a single
**Shop Manual** consumed by `shop_gen`. Treat every file you write as
public artifact destined for that manual.

---

## 1. Mission

Produce a structured, **anonymized** description of the live shop's UX
and feature set. We care about **structure and behavior**, not catalog
content. Concretely, the run output must let a downstream synthesizer
rebuild a sandbox shop with the same UX surface — not the same brand,
products, or copy.

If a tradeoff appears between "more detail about this exact shop" and
"transferable structural pattern", always pick the latter.

---

## 2. Anonymization rules (STRICT — apply at write time)

These rules apply to **every byte you write** under `artifact/parts/`
and to any markdown notes anywhere in the run dir. They do **not**
apply to `artifact/prefetch/` (raw evidence, kept as-is) or to
`artifact/evidence/<task_id>/snapshots|screenshots|network.jsonl`
(captured artifacts; the synthesis step treats them as evidence, not
as published prose).

Hard rules:

- **Store name.** Replace the real store name with a generic
  descriptor — e.g. "Luxury Jewelry Store",
  "Premium Outdoor Gear Shop". Never mention the real brand.
- **Product names.** Replace real product names with generic
  descriptions — e.g. "Gold Letter Pendant" →
  "Personalized Letter Charm". Keep the *category* and any structural
  variant axes (size, color, material); drop proper nouns.
- **Brand references.** Replace with `[Brand]`.
- **People, designers, collaborators.** Replace named persons with
  their role — "designer", "founder", "collaborator artist".
- **URLs.** Do not include the source domain or any absolute URL
  pointing at the live shop. Reference paths instead (`/cart`,
  `/collections/<slug-redacted>`).
- **Email / phone / address.** Replace with the structural fact only
  ("a contact form", "a physical address in `<region>`").
- **Direct quotes from on-page copy.** Do not paste marketing copy
  verbatim. Summarize the *type* and *function* of the copy
  ("a 1–2 sentence value-prop headline", "a 4-bullet feature list").
- **Image captions / alt text.** Same rule — describe the *role* of
  the image, not its specific content beyond category-level facts.

Soft rules (apply when in doubt):

- Currency symbols, locale codes, and language tags **are** structural
  and stay. (`USD`, `en-CA`, "ships to EU".)
- Numeric facts that describe *layout* stay (column count, section
  count, filter count). Numeric facts that describe *catalog scale*
  stay aggregated only (totals, medians) — never list individual SKUs.
- Generic e-commerce terminology — "cart drawer", "predictive search",
  "mega menu" — is encouraged; that is the vocabulary of the
  capabilities schema.

The goal is to capture **STRUCTURE and UX patterns**, not actual
content. A reader of `manual.md` should be unable to identify the
source shop.

A final anonymization pass runs during synthesis on `manual.md`, but
that pass is a safety net — the rules above are the primary defense
and you are expected to apply them at write time.

---

## 3. Playwright skill — the only way to drive the browser

All browsing — for both planner and executor — goes through the
**playwright skill** (`pi-playwright`, the
`skills/playwright-browser/` directory). Do **not** issue raw HTTP
requests from inside an iteration; the prefetch step has already done
that for the URLs we need.

The harness has already resolved the skill path **and pre-opened a
browser session for you**. Both are baked into your environment:

```bash
SKILL_DIR="{{PLAYWRIGHT_SKILL_DIR}}"
# PLAYWRIGHT_CLI_SESSION is exported by the harness; pw.js picks it up
# automatically. Do not override it.
```

Then invoke the wrapper for every browser action:

```bash
node "$SKILL_DIR/scripts/pw.js" <command> [...args]
```

Useful commands (full list in the skill's `SKILL.md`):

- `goto <url>` — navigate. **First call.** No need for `open` first;
  the harness already opened the browser.
- `snapshot --output <path>` — write an a11y snapshot to a file.
  Always snapshot **before** clicking/filling so element refs resolve.
- `click <ref>` / `fill <ref> <value>` / `select <ref> <value>` —
  interact via refs from the latest snapshot.
- `screenshot --full-page --output <path>` — full-page PNG.
- `eval <expression>` — read DOM state (use sparingly; prefer
  snapshots).

Conventions:

- Run **headless** by default. Pass `--headed` only if a human-driven
  debug session has set it.
- The browser session is shared across the run by the harness.
  **Do not** call `pw.js open` (already done) or `pw.js close`
  (the harness owns lifecycle), and **never** invoke `playwright-cli`
  or `playwright` binaries directly — only `pw.js` has the session
  pinned. Calling them directly produces
  `Browser '<session>' is not open` errors and wastes 5+ tool calls
  per misstep.
- **Batch related calls into one bash invocation** when capturing
  many states. Examples:
  - One `eval` returning a dict of all section Y-coords beats N
    separate `eval` calls (each costs ~5–10 s of subprocess startup).
  - One bash block that loops `scrollTo + screenshot --output` over
    every section beats N separate `pw.js screenshot` calls.
- Save every snapshot and every screenshot **to a file under the
  evidence dir** (see §4). Do not paste large payloads into the
  context window.
- **Don't read screenshots back as verification.** A successful
  `pw.js screenshot --output …` call has already produced the file;
  trust the exit status. Only `read` a PNG when you need to
  *interpret* an unexpected page state (e.g. a popup blocked the
  capture). Verification re-reads cost ~5 s + ~120 LLM tokens each.
- Dismiss cookie banners / popups once at the top of a task; record
  their presence in `caps.json` then move on.
---

## 4. File-write conventions

The harness owns the top-level run dir. You own everything under
`artifact/`. The layout (from §5.4 of the spec) is:

```
artifact/
├── prefetch/             # READ-ONLY for you. Seeded by shop_explore.
├── parts/                # YOU WRITE these.
│   ├── <task_id>.md
│   └── <task_id>.caps.json
└── evidence/<task_id>/   # YOU WRITE these.
    ├── snapshots/
    ├── screenshots/
    └── network.jsonl     # optional
```

Task ids come from `plan.md` (snake_case, stable across iterations —
e.g. `homepage_sections`, `cart_drawer`, `search_predictive`). Use the
same id for both `parts/<task_id>.*` and `evidence/<task_id>/`.

`parts/<task_id>.md` — markdown describing the structural findings
for this task. **Anonymized.** Use one `## <Surface name>` heading at
the top, then one `### <Element name>` block per distinct UX element
following the bullet template (Type / Layout / Content / Behavior /
Styling / UX Notes) defined in `prompts/execute.md` §"Per-element
template". The synthesis pass lifts those H3 blocks into the final
`manual.md`, so optimize for structural fidelity, not brevity — every
bullet is a claim a downstream sandbox generator needs. No on-page
copy quoted verbatim; describe the *role* and *shape* of each
element. Reference your evidence inline by relative path, e.g.
`see evidence/cart_drawer/screenshots/01-empty.png`.

`parts/<task_id>.caps.json` — a JSON object containing **only** the
top-level capabilities-schema keys this task is responsible for. The
schema is closed (extra fields rejected at merge time); do not invent
keys. Lists are deduplicated and order-preserved at merge time. Do
**not** wrap your fragment in any envelope — just the partial object.

`evidence/<task_id>/snapshots/NN-<state>.md` — a11y snapshots, one per
distinct page state, numbered for ordering.

`evidence/<task_id>/screenshots/NN-<state>.png` — full-page PNGs, one
per distinct page state, same numbering as the snapshot it pairs with.

`evidence/<task_id>/network.jsonl` — optional; append one JSON object
per captured XHR. Use only when the request itself is the evidence
(predictive search suggestions, cart updates).

Final action of any executor iteration: edit `plan.md` to mark this
task `[x]` (success) or `[!] <one-line reason>` (blocked / partial).
Do not edit any other task's checkbox or any other file outside the
list above.

---

## 5. Capabilities schema reference

The closed pydantic v2 schema for `capabilities.json` is reproduced
below verbatim from `shop_explore.capabilities.schema` (rendered into
this file at pipeline-time, so it cannot drift):

```python
{{CAPABILITIES_SCHEMA}}
```

The top-level groupings (`shop`, `site_shell`, `homepage`,
`collection`, `product`, `cart`, `search`, `floating`,
`info_pages_present`) are the only valid keys for any
`parts/<task_id>.caps.json` fragment.

If your task observes a feature that does not fit the schema, do
**not** invent a new key. Describe it in `parts/<task_id>.md` and
mention the gap in your iteration notes; it becomes a candidate for a
future schema revision, not a silent leak.

---

## 6. Don'ts

- Don't crawl beyond the brief specified by your role prompt
  (planner: ≤ 4 pages; executor: scope of one task in `plan.md`).
- Don't hit `/admin`, `/account`, or anything behind login. We are an
  unauthenticated UX explorer.
- Don't mutate `artifact/prefetch/` — it is the immutable seed.
- Don't write outside `artifact/parts/`, `artifact/evidence/`, and
  `plan.md`. Other paths belong to the harness or to other iterations.
- Don't paste large blobs (snapshots, screenshots, raw HTML) into your
  reply — write them to files and reference paths.
