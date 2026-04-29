# consolidate_execute.md — `shop_gen` consolidation pass

You are the **consolidation pass**. Every other `gen_*` task has
completed (or has been marked `[!]` with a deferred reason). The harness
selected the mandatory final task `consolidate`; this prompt replaces
the generic executor body for that one task.

`AGENTS.md` (at `<run_dir>/AGENTS.md`) is the contract — file-write
conventions, sidecar / Storefront API conventions, verifier contract.
Read it first; this prompt does not duplicate it.

Your job is **cross-task cleanup**, not new features. Do not introduce
new pages, new components, or new visual treatments. Fix the seams the
slice-owned `gen_*` tasks could not fix on their own.

---

## Verifier feedback from the previous iteration

```
{{verifier_feedback}}
```

If the block above is empty, this is the first attempt at consolidation
— proceed normally. If the block contains a verifier report, treat it as
a hard error description from the previous consolidation iteration:

- For rule verifiers (`tsc`, `build`, `data_in_use`, `nav_coverage`) —
  the body lists the offending file:line + diagnostic. Fix in place.
- For `quality_judge` — the body is an LLM verdict scoped to the
  storefront's manual; treat it as a focused product review and fix
  the called-out gap.
- For `cross_task_consistency` — the body is the cross-task LLM judge.
  This is the verifier closest to your job; the named drift is exactly
  what consolidation must repair. Read the full body before editing.

### Retry budget — 3 max retries

The harness rewrites your task's `[x]` → `[~]` whenever any verifier
returned FAIL, and re-selects the same task next iteration. To prevent
an unfixable task from burning the whole run's iteration budget,
`consolidate` has a **3-retry cap** that you track yourself in the
task's note field as a `(retry N/3)` annotation.

Before doing any work, read the `consolidate` line
in `plan.md` and act on the note as follows:

1. **Note ends with `(retry 3/3)`.** You have already used all 3
   retries and the last one still FAILed. **Do not attempt a fourth
   fix.** Flip the marker to `[!] retry_exhausted: <last failing
   verifier name from the feedback above>` and exit. The task is
   permanently retired for this run.
2. **Note ends with `(retry N/3)` for N < 3.** You are entering retry
   attempt N+1. When you exit, update the annotation to `(retry N+1/3)`.
3. **Note has no `(retry …)` annotation but the verifier feedback above
   is non-empty.** You are entering retry attempt 1. When you exit, add
   `(retry 1/3)` to the note.
4. **No annotation and feedback is empty.** Fresh first attempt — no
   retry tracking needed yet.

Annotation format: append `(retry N/3)` to the existing brief,
separated by a single space. Keep the existing brief intact.

- before: `- [~] gen_homepage — render homepage hero + featured grid`
- after:  `- [~] gen_homepage — render homepage hero + featured grid (retry 2/3)`

The harness preserves the note across its own `[x]` → `[~]` rewrites,
so once you have written `(retry N/3)` it stays on the line until you
update it.

---

## 1. Selecting your task

The harness prepends the iteration body with:

```
<<<harness-control>>>
selected_task_id: consolidate
<<<end>>>
```

You are working on the `consolidate` task in `plan.md`. Edit only its
line when you finish.

If the planner failed to emit `consolidate` and the orchestrator
appended it deterministically, the brief after `—` will be the canonical
brief. Either way, your scope is the cleanup pass below.

---

## 2. Reading the inputs

The full `hydrogen/app/` tree is your scope, but read it surgically:

1. **`plan.md`** — every `[x]` task is your input; every `[!]` task is a
   deferral that may have logged a "needs cross-task fix in `<slice>`"
   reason for you to honour.
2. **`artifact/manual/capabilities.json`** — the closed schema. Use it
   as the ground truth when checking that a slice still honours the
   manual.
3. **`artifact/hydrogen/app/`** — read the slices `gen_theme`,
   `gen_navigation`, `gen_homepage`, `gen_collections`, `gen_product`,
   `gen_cart_search`, `gen_info_pages`, and `visual_polish` mutated.
   The owned-slice table in `prompts/execute.md` §3 is the map.

---

## 3. What to fix (the six seams)

Walk these checks **in order**. Each is a deliberate cross-task seam the
slice-owned `gen_*` tasks could not own on their own:

1. **Shared-component drift.** Two slices import slightly different
   versions of `ProductItem`, `Button`, `Price`, `ImageWithFallback`,
   etc. Resolve to a single canonical implementation. Move the shared
   component into `app/components/` if it is not already there; update
   all importers.
2. **Design-token drift.** `gen_theme` defined a token set; later slices
   may have hard-coded values (a `#0066cc` instead of `var(--color-accent)`,
   a `1rem` instead of `var(--space-4)`). Replace literals with the
   tokens from `gen_theme`. If `gen_theme` did not define the token your
   slice needed, **add it to the theme** rather than letting the
   literal stand.
3. **Navigation coverage drift.** Every collection in
   `data/collections.json` must be reachable from the rendered nav. If
   `gen_collections` introduced a new collection slice that
   `gen_navigation` predates, update the nav builder to include it.
   The `nav_coverage` verifier already catches missing handles; this
   step closes the loop on the inverse case (nav links pointing at a
   route that was renamed by `gen_collections` or `gen_product`).
4. **Orphan imports / dead routes.** Any `import` that resolves to a
   file that no longer exists. Any route file that is not reachable
   from any link. Either delete the orphan or wire it back in — never
   leave a TS error or a dead-link warning.
5. **GraphQL fragment / query drift.** Two slices defining nearly-the-
   same fragment with different field sets. Hoist a shared fragment
   into `app/lib/fragments.ts` (or the template's equivalent) and
   converge the importers.
6. **Deferred verifier feedback from prior tasks.** Any earlier
   iteration that left a `[!] needs cross-task fix in <slice>` reason
   on a `gen_*` task is your responsibility. Read the iteration's
   `feedback.md`, apply the fix to the right slice, and tighten the
   `plan.md` line to drop the deferral marker if the fix is now in
   place.

What is **out of scope**:

- New components, new pages, new sections, new design treatments.
- Visual polish that is not a direct symptom of one of the seven seams
  above — that was `visual_polish`'s job.
- Mutating `artifact/manual/`. The manual is the seed; consolidation
  reconciles the build to the manual, not the other way around.

---

## 4. Tool-use efficiency

Consolidation is read-heavy. Keep iteration count down:

1. **One repository scan up front** beats N targeted greps. Use
   `rg` / `grep -rn` to enumerate all importers of `Button`,
   `ProductItem`, etc. in one bash block.
2. **Batch token-drift fixes** into the smallest set of file edits —
   one edit per file per drift class.
3. **Run `pnpm --filter hydrogen tsc --noEmit` + `pnpm --filter hydrogen build`
   once at the end** to confirm the cleanup did not regress anything.
   The harness verifier set will rerun them; catching here saves a retry.
4. **Do not start a dev server** during consolidation.

---

## 5. Self-check before exit

- Every change is a fix to one of the six seams in §3 — no new
  features.
- Every modified file lives under `artifact/hydrogen/`.
- `pnpm --filter hydrogen tsc --noEmit` passes.
- `pnpm --filter hydrogen build` succeeds.
- `plan.md` shows `consolidate` as `[x]` or
  `[!] retry_exhausted: <verifier>`; no other task's checkbox changed
  (apart from `[!]` `gen_*` deferrals you legitimately resolved — see
  next bullet).
- If you entered this iteration with non-empty verifier feedback, the
  `consolidate` note ends with the correct `(retry N/3)` annotation
  reflecting this attempt — or you have flipped to
  `[!] retry_exhausted` per the retry-budget rules above.
- For any deferred `[!]` `gen_*` task whose reason you fixed, the line
  is updated to drop the deferral marker.
