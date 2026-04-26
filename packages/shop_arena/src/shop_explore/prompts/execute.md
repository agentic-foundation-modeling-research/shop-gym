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
   - `artifact/parts/<task_id>.md` — prose describing the *role* and
     *shape* of each element. H2 headings under the task name (no H1).
     Reference evidence inline by relative path.
   - `artifact/parts/<task_id>.caps.json` — single JSON object with
     top-level keys from the closed schema for the surface in your
     brief. The schema rejects unknowns at merge time; if you observe
     a feature it cannot express, describe it in the markdown and
     skip the key.

4. **Mark `plan.md`.** Flip your task line to `[x]` on success or
   `[!] <one-line reason>` if blocked / partial. Edit only your line.
   Leaving it `[ ]` aborts the run.

---

## Self-check before exit

- Both `parts/<task_id>.md` and `parts/<task_id>.caps.json` exist;
  the caps file parses as one JSON object (no envelope, no array).
- ≥ 1 screenshot, paired snapshot at the same `NN`.
- No store / brand / product names; no verbatim on-page copy.
- `plan.md` changed exactly one line: yours.
