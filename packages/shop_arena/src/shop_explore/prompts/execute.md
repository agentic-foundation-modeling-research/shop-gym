# execute.md — `shop_explore` executor

You are the **executor** for one `shop_explore` task. `AGENTS.md`
(at `<run_dir>/AGENTS.md`) is the contract — anonymization rules,
playwright skill usage, file-write conventions, capabilities-schema
reference. Read it first; this prompt does not duplicate it.

---

## Selecting your task

The harness prepends:

```
<<<harness-control>>>
selected_task_id: <task_id>
<<<end>>>
```

Work only on `<task_id>`. Find its line in `plan.md`; the brief after
the `—` is your spec (states, pages, network capture if any). Do not
edit any other task's checkbox.

---

## What to do

1. **Resolve in prefetch first.** Start at
   `artifact/prefetch/prefetch.json` — it indexes every URL that was
   fetched (path, status, content_type, bytes, saved_to). Use it to
   decide which saved bodies are worth opening (e.g. `products.json`
   for a PDP with > 1 variant, `collections.json` for the largest
   collection). The whole `artifact/prefetch/` tree is read-only;
   pick the largest / most-varied sample so the capture generalizes.

2. **Drive the browser via the playwright skill** (AGENTS.md §3) for
   anything HTML can't show. Snapshot before clicking. Capture under
   `artifact/evidence/<task_id>/`:
   - `snapshots/NN-<state>.md` — a11y snapshot per distinct state.
   - `screenshots/NN-<state>.png` — full-page PNG, paired by `NN`.
   - `network.jsonl` — only when the request *itself* is the evidence
     (predictive search, cart updates, filter responses).

3. **Write the part files.** Anonymize at write time per AGENTS.md §2.
   - `artifact/parts/<task_id>.md` — markdown describing the *role* and
     *shape* of each element. Use the template in §"Per-element
     template" below; reference evidence inline by relative path.
   - `artifact/parts/<task_id>.caps.json` — single JSON object with
     top-level keys from the closed schema for the surface in your
     brief. The schema rejects unknowns at merge time; if you observe
     a feature it cannot express, describe it in the markdown and
     skip the key.

4. **Mark `plan.md`.** Flip your task line to `[x]` on success or
   `[!] <one-line reason>` if blocked / partial. Edit only your line.
   Leaving it `[ ]` aborts the run.

---

## Tool-use efficiency

Each tool call costs ~3 s of fixed overhead plus LLM streaming time;
wasted calls add up to several minutes over a run. Two rules to keep
the per-task budget tight:

1. **Do not re-read screenshots / snapshots after capturing them.**
   A successful `pw.js screenshot --output …` produces the file;
   trust the exit status. Verification re-reads cost ~5 s + ~120
   LLM tokens each, and a 16-section homepage burns ~100 s on this
   alone. Read a PNG only when you need to *interpret* an unexpected
   state (popup blocked the capture, layout looks wrong) — not as a
   sanity check.
2. **Batch playwright calls.** When capturing N states or measuring
   N elements, prefer one bash block over N tool calls:
   - **One** `pw.js eval "() => ({ hero: …, cart: …, footer: … })"`
     returning a dict beats N separate `eval` calls.
   - **One** bash loop that scrolls + screenshots every section in a
     single subprocess beats N separate `pw.js screenshot` calls.
   - Group `mkdir` + first `pw.js` call into the same bash block.

---

## Per-element template

`parts/<task_id>.md` is the *source of structural detail* the synthesis
pass relies on. Treat it as the long-form companion to your
`caps.json`: where caps captures booleans and enumerations, the
markdown captures *layout, behavior, and content shape* well enough
that a downstream sandbox generator can rebuild the surface without
seeing the live shop.

Required structure:

- One `## <Surface name>` heading at the top (H2 under the implicit
  task title — e.g. `## Homepage Sections`, `## Cart Drawer`,
  `## Search`). Do not repeat the task title at H1.
- Optional 1–2 sentence orientation paragraph after the H2 plus inline
  evidence references (full-page screenshot, key snapshots).
- One `### <Element name>` block per distinct UX element observed
  (e.g. each homepage section, each cart state, each variant axis).
  Number them `Section 1 — …`, `Section 2 — …` when ordering matters.

For every `### <Element name>` block, fill the bullet template below.
Mark a field `N/A` rather than skipping it — the schema makes gaps
visible to the synthesis pass instead of letting them disappear.

```markdown
### <Element name>

- **Type:** <one-line classification — e.g. "promotional banner",
  "sticky two-row header", "horizontal product carousel">
- **Layout:** <how it is structured visually — column count, grid vs
  carousel, asymmetric splits, mobile vs desktop differences>
- **Content:** <what fields and data the element shows — image, title,
  price block, savings badge, star rating, etc.>
- **Behavior:** <interactivity — scroll, hover, click, expand, modal
  open, autoplay, sticky-on-scroll, ajax updates, popup triggers>
- **Styling:** <visual cues — full-bleed, dark/light, sticky, dismissible,
  badge color, typography role; only structural facts, no brand colors>
- **UX Notes:** <quirks, edge cases, accessibility cues, anonymization
  flags — anything a generator would otherwise miss>
```

Close every part file with one `### Edge cases & gaps` block (use the
same bullet template) summarizing surfaces you tried but could not
exercise (popup didn't fire, variant out of stock, etc.). This is
where the synthesis pass learns what is *absent* in addition to what
is present.

Keep prose factual and structural — no marketing tone, no verbatim
on-page copy, no brand or product names. The point is fidelity, not
brevity: a richer part is fine as long as every line is structural.

---

## Self-check before exit

- Both `parts/<task_id>.md` and `parts/<task_id>.caps.json` exist;
  the caps file parses as one JSON object (no envelope, no array).
- ≥ 1 screenshot, paired snapshot at the same `NN`.
- No store / brand / product names; no verbatim on-page copy.
