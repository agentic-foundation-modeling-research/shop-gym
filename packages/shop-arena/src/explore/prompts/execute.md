# execute.md - `shop-arena` explore executor

You are the **executor** for one explore task. `AGENTS.md`
(at `<run_dir>/AGENTS.md`) is the contract - anonymization rules,
browser tool usage, file-write conventions, capabilities-schema
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
   `artifact/prefetch/prefetch.json` - it indexes every URL that was
   fetched (path, status, content_type, bytes, saved_to). Use it to
   decide which saved bodies are worth opening (e.g. `products.json`
   for a PDP with > 1 variant, `collections.json` for the largest
   collection). The whole `artifact/prefetch/` tree is read-only;
   pick the largest / most-varied sample so the capture generalizes.

2. **Drive the browser with the browser tools** (AGENTS.md §3) for
   anything HTML can't show. Snapshot before clicking. Capture under
   `artifact/evidence/<task_id>/`:
   - `snapshots/NN-<state>.md` - the `snapshot` text per distinct
     state, saved with `write_file`.
   - `network.jsonl` - only when the request *itself* is the evidence
     (predictive search, cart updates, filter responses).
   Use `screenshot` when you need to interpret visual layout; the
   runtime keeps those images under the iteration directory for you.

3. **Write the part files.** Anonymize at write time per AGENTS.md §2.
   - `artifact/parts/<task_id>.md` - markdown describing the *role* and
     *shape* of each element. Use the template in §"Per-element
     template" below; reference evidence inline by relative path.
   - `artifact/parts/<task_id>.caps.json` - single JSON object with
     top-level keys from the closed schema for the surface in your
     brief. The schema rejects unknowns at merge time; if you observe
     a feature it cannot express, describe it in the markdown and
     skip the key.

4. **Mark `plan.md`.** Flip your task line to `[x]` on success or
   `[!]` if blocked / partial, keeping the `— <brief> [priority: N]`
   trailer intact (append the one-line reason to the brief after a
   `;`). Edit only your line.
   Leaving it `[ ]` aborts the run.

---

## Tool-use efficiency

Each tool call costs fixed overhead plus LLM streaming time; wasted
calls add up to several minutes over a run. Two rules to keep the
per-task budget tight:

1. **Do not re-read evidence after writing it.** A successful
   `write_file` reply means the file exists; trust it. Re-read a file
   only when you need its content for the next decision.
2. **Snapshot once per state, not once per action.** When a sequence
   of clicks leads to one state you care about, take a single
   `snapshot` at the end. Use `screenshot` for layout interpretation
   only - it is not a verification step.

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
  task title - e.g. `## Homepage Sections`, `## Cart Drawer`,
  `## Search`). Do not repeat the task title at H1.
- Optional 1-2 sentence orientation paragraph after the H2 plus inline
  evidence references (key snapshots).
- One `### <Element name>` block per distinct UX element observed
  (e.g. each homepage section, each cart state, each variant axis).
  Number them `Section 1 - ...`, `Section 2 - ...` when ordering matters.

For every `### <Element name>` block, fill the bullet template below.
Mark a field `N/A` rather than skipping it - the schema makes gaps
visible to the synthesis pass instead of letting them disappear.

```markdown
### <Element name>

- **Type:** <one-line classification - e.g. "promotional banner",
  "sticky two-row header", "horizontal product carousel">
- **Layout:** <how it is structured visually - column count, grid vs
  carousel, asymmetric splits, mobile vs desktop differences>
- **Content:** <what fields and data the element shows - image, title,
  price block, savings badge, star rating, etc.>
- **Behavior:** <interactivity - scroll, hover, click, expand, modal
  open, autoplay, sticky-on-scroll, ajax updates, popup triggers>
- **Styling:** <visual cues - full-bleed, dark/light, sticky, dismissible,
  badge color, typography role; only structural facts, no brand colors>
- **UX Notes:** <quirks, edge cases, accessibility cues, anonymization
  flags - anything a generator would otherwise miss>
```

Close every part file with one `### Edge cases & gaps` block (use the
same bullet template) summarizing surfaces you tried but could not
exercise (popup didn't fire, variant out of stock, etc.). This is
where the synthesis pass learns what is *absent* in addition to what
is present.

Keep prose factual and structural - no marketing tone, no verbatim
on-page copy, no brand or product names. The point is fidelity, not
brevity: a richer part is fine as long as every line is structural.

---

## Self-check before exit

- Both `parts/<task_id>.md` and `parts/<task_id>.caps.json` exist;
  the caps file parses as one JSON object (no envelope, no array).
- >= 1 saved snapshot under `evidence/<task_id>/snapshots/`.
- No store / brand / product names; no verbatim on-page copy.

---

## Verifier feedback

If the previous iteration on this task failed a verifier, its feedback
follows. Fix every listed line before marking the task done again.

{{verifier_feedback}}
