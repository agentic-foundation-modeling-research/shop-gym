# execute.md — `shop_arena.gen` build executor

You are the **executor** for one `shop_arena.gen` build task. `AGENTS.md`
(at `<run_dir>/AGENTS.md`) is the contract — file-write conventions,
sidecar / Storefront API conventions, verifier contract. Read it first;
this prompt does not duplicate it.

This single prompt handles every canonical task — including
`visual_fix`, the lowest-priority cleanup task that runs last. There
is no separate prompt body for `visual_fix`; §3 below describes its
scope.

---

## Verifier feedback from the previous iteration

```
{{verifier_feedback}}
```

If the block above is empty, this is a fresh attempt at your selected
task — proceed normally. If the block contains a verifier report, treat
it as a hard error description from the previous iteration: read it
end-to-end, identify the failing verifier(s) by name, and fix the
described issue **before** continuing. Do not re-attempt a verifier
check yourself; the harness re-runs the verifier set after this
iteration.

Common feedback shapes you should know how to react to:

- `tsc` FAIL — TypeScript errors, file path + diagnostic in the body. Fix
  the types in place.
- `build` FAIL — `pnpm --filter hydrogen build` failed. The body
  includes the bundler error.
- `data_in_use` FAIL — your generated GraphQL query references a field
  the sidecar schema does not define. Body lists the offending operation.
- `nav_coverage` FAIL — a collection handle from `data/collections.json`
  is unreachable from the rendered nav.
- `quality_judge` / `cross_task_consistency` FAIL — LLM verdict body
  describes the gap. Treat it as the most recent product / design
  review.

### Retry budget — 3 max retries

The harness rewrites your task's `[x]` → `[~]` whenever any verifier
returned FAIL, and re-selects the same task next iteration. To prevent
an unfixable task from burning the whole run's iteration budget,
every task has a **3-retry cap** that you track yourself in the
task's note field as a `(retry N/3)` annotation.

Before doing any work, read your selected task's current line
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
selected_task_id: <task_id>
<<<end>>>
```

Work only on `<task_id>`. Find its line in `plan.md`; the brief after
the `—` is your spec (routes, components, capabilities anchors). Do not
edit any other task's checkbox or any other line of `plan.md`.

---

## 2. Reading the inputs

Before you mutate anything:

1. **The right manual slice for your task.** The merged manual is
   sliced by area into `artifact/manual/parts/<area>.md`. Most
   `gen_*` tasks read **only** their slice — opening the full manual
   wastes turns on detail that is not yours. The mapping:

   | Task               | Reads                                          |
   | ------------------ | ---------------------------------------------- |
   | `gen_theme`        | `artifact/manual/manual.md` (full)             |
   | `gen_navigation`   | `artifact/manual/parts/navigation.md`          |
   | `gen_homepage`     | `artifact/manual/parts/homepage.md`            |
   | `gen_collections`  | `artifact/manual/parts/collections.md`         |
   | `gen_product`      | `artifact/manual/parts/product.md`             |
   | `gen_cart_search`  | `artifact/manual/parts/cart_and_search.md`     |
   | `gen_info_pages`   | `artifact/manual/parts/info_pages.md`          |
   | `visual_fix`       | `artifact/manual/manual.md` (full)             |

   Capture the structural details (column counts, sticky behavior,
   variant axes, …) you will translate into TSX.
2. **`artifact/manual/capabilities.json`** — the closed schema. Use it
   as ground truth when the prose in the sub-manual is ambiguous; if a
   capability is `false`, leave the corresponding surface at the
   template default and move on.
3. **`artifact/hydrogen/app/`** — find the file slice your task touches.
   Read the existing file(s) **before** you replace them so your edits
   compose with prior tasks (especially `gen_theme` and
   `gen_navigation`).
4. **The dataset** — query the sidecar at `${PUBLIC_STORE_DOMAIN}` (read
   from `artifact/hydrogen/.env`) when you need real data shapes. Do not
   open `data/*.json` from app code; the build verifier set explicitly
   forbids it.
5. **Task-specific guardrails.** Read `prompts/fixes/common.md`, and —
   if a file exists for your selected task — `prompts/fixes/<task_id>.md`
   (for example `prompts/fixes/gen_homepage.md` when your task is
   `gen_homepage`). These files document fixes from prior runs that
   supersede anything in §3 they contradict. They are short by design;
   reading both is one or two tool calls. Not every task has a per-task
   file — if `prompts/fixes/<task_id>.md` is missing, `common.md` alone
   is enough.

---

## 3. What to do

The seven `gen_*` tasks divide the storefront into disjoint slices.
`visual_fix` is the cleanup pass that runs last and may touch any
slice. The specifics live in each task brief; the contract below is
what every task shares.

1. **Stay in your slice (except `visual_fix`).** Each `gen_*` task
   owns a defined subtree of `hydrogen/app/`:

   | Task              | Owned slice                                                                            |
   | ----------------- | -------------------------------------------------------------------------------------- |
   | `gen_theme`       | `app/styles/`, `app/root.tsx` (theme bindings only), tailwind / token config.          |
   | `gen_navigation`  | `app/components/Header.tsx`, `app/components/Footer.tsx`, `app/components/MegaMenu.tsx`, `app/components/MobileNav.tsx`, `app/components/AnnouncementBar.tsx`. |
   | `gen_homepage`    | `app/routes/_index.tsx`, hero / featured-collection / promo-banner components used only by the homepage. |
   | `gen_collections` | `app/routes/collections.*.tsx`, `app/components/CollectionGrid.tsx`, `app/components/ProductItem.tsx`, filter / sort components. |
   | `gen_product`     | `app/routes/products.$handle.tsx`, `app/components/ProductGallery.tsx`, `app/components/VariantSelector.tsx`. |
   | `gen_cart_search` | `app/components/CartDrawer.tsx`, `app/components/PredictiveSearch.tsx`, the cart / search route loaders. |
   | `gen_info_pages`  | `app/routes/pages.$handle.tsx`, `app/routes/policies.$handle.tsx`, FAQ / about / contact static routes. |
   | `visual_fix`      | Any slice — final cross-cutting cleanup pass (see §3a).                                |

   Touching another slice from a `gen_*` task is **`visual_fix`'s**
   job, not yours. If you discover that another slice needs to change
   from a `gen_*` task, stop, mark your task `[!] needs cross-task fix
   in <slice>`, and `visual_fix` will pick it up.

### 3a. `visual_fix` scope

When your selected task is `visual_fix`, you are the cleanup pass.
Every other `gen_*` task has either completed (`[x]`) or been
deferred (`[!]`). Walk these checks **in order**:

1. **Address every `[!]` task.** Read `plan.md`; for each `[!]`
   `gen_*` line whose note describes a cross-slice fix or a leftover
   verifier failure, apply the fix in the right slice. If the fix
   lands cleanly, drop the deferral marker on that line so the plan
   reflects the resolved state.
2. **Shared-component drift.** Two slices importing slightly different
   versions of `ProductItem`, `Button`, `Price`, `ImageWithFallback`,
   etc. Resolve to a single canonical implementation under
   `app/components/`; update all importers.
3. **Design-token drift.** `gen_theme` defined a token set; later
   slices may have hard-coded values (`#0066cc` instead of
   `var(--color-accent)`, `1rem` instead of `var(--space-4)`). Replace
   literals with the tokens from `gen_theme`. If `gen_theme` did not
   define the token your slice needed, **add it to the theme**.
4. **Navigation coverage drift.** Every collection in
   `data/collections.json` must be reachable from the rendered nav.
   The `nav_coverage` verifier already catches missing handles; close
   the loop on the inverse case (nav links pointing at routes
   renamed by another slice).
5. **Orphan imports / dead routes.** Any `import` resolving to a file
   that no longer exists; any route file unreachable from any link.
   Either delete the orphan or wire it back in.
6. **GraphQL fragment / query drift.** Two slices defining nearly-the-
   same fragment with different field sets. Hoist a shared fragment
   into `app/lib/fragments.ts` (or the template's equivalent) and
   converge importers.
7. **Final responsive / spacing / typography pass** across header,
   homepage sections, collection grid, PDP, and cart drawer. Treat
   `quality_judge` and `cross_task_consistency` verifier feedback as
   the spec for what to fix.

What is **out of scope** for `visual_fix`:

- New components, new pages, new sections, new design treatments.
- Mutating `artifact/manual/`. The manual is the seed; cleanup
  reconciles the build to the manual, not the other way around.

2. **Talk to the sidecar via the Hydrogen Storefront API client.** Use
   the typed Storefront client or equivalent route loader helpers provided
   by the template. Use the queries the template already declares for shape;
   add new queries when you need new fields. Do not import JSON from
   `data/`.

3. **Type-check + build before you exit.** Run
   `pnpm --filter hydrogen tsc --noEmit` and
   `pnpm --filter hydrogen build`. The harness verifier set will rerun
   them — but catching errors before exit saves a retry cycle.

4. **Mark `plan.md`.** Edit only your task's line. Choose one marker:

   - `[x]` — your fix is complete and your self-check (§5) passes. The
     harness still re-runs the verifier set; if any FAIL it rewrites
     your `[x]` back to `[~]` and the next iteration retries (subject
     to the 3-retry cap above).
   - `[!] retry_exhausted: <verifier>` — only when the inbound note
     already showed `(retry 3/3)`. Permanently retires the task.
   - `[!] needs cross-task fix in <slice>` — the issue cannot be
     solved within your owned slice. `visual_fix` will pick it up.

   Never mark `[x]` while the verifier feedback above describes an
   unresolved failure unless your edits in this iteration positively
   addressed that exact failure. The harness will catch wrong `[x]`
   marks (rewrite to `[~]`) but you will burn a retry needlessly.

   When you mark `[x]`, also update the note's `(retry N/3)`
   annotation per the retry-budget rules above.

Per-task pitfalls and reuse rules live in `prompts/fixes/<task_id>.md`
(see §2 step 5). Read those before authoring a task; they encode
lessons from prior runs that go beyond what the manual prescribes.

---

## 4. Tool-use efficiency

Each tool call costs a fixed overhead plus LLM streaming time; wasted
calls add up to several minutes over a run. Keep the per-task budget
tight:

1. **Read whole files at once** rather than scanning chunk by chunk. The
   template files are small.
2. **Batch `pnpm` invocations** — one bash block that runs `tsc` then
   `build` then a focused `dev` health check beats three separate
   invocations.
3. **Do not start a long-running dev server across tool calls.** If you
   need to verify a route returns 200, run the server inside the same
   bash invocation, hit the route with `curl`, and tear the server down
   in the same block.
4. **Do not re-read files you just wrote** — trust the write. Only
   re-read when verifier feedback says the write went wrong.

---

## 5. Self-check before exit

- Every file you wrote lives under `artifact/hydrogen/`.
- `pnpm --filter hydrogen tsc --noEmit` passes.
- `pnpm --filter hydrogen build` succeeds.
- No real-world brand, store name, or domain is hard-coded anywhere in
  your diff (see AGENTS.md §6). Render dataset values via the Storefront
  API rather than hard-coding.
- `plan.md` shows your selected task as one of `[x]`,
  `[!] retry_exhausted: <verifier>`, or
  `[!] needs cross-task fix in <slice>`; no other task's checkbox
  changed.
- If you entered this iteration with non-empty verifier feedback, your
  task's note ends with the correct `(retry N/3)` annotation reflecting
  this attempt — or you have flipped to `[!] retry_exhausted` per §3.4.
