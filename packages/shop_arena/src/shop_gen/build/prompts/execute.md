# execute.md — `shop_gen` build executor

You are the **executor** for one `shop_gen` build task. `AGENTS.md`
(at `<run_dir>/AGENTS.md`) is the contract — brand-safety rules,
file-write conventions, sidecar / Storefront API conventions, verifier
contract. Read it first; this prompt does not duplicate it.

The `consolidate` task has its own purpose-built body
(`prompts/consolidate_execute.md`) — the orchestrator routes to that
prompt when the harness selects `consolidate`. You will not be invoked
for `consolidate`; if you somehow are, fall through to the consolidation
behavior described there.

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
- `routes_200` FAIL — a route under your task returned non-200. Body
  lists `<path>: <status>`.
- `data_in_use` FAIL — your generated GraphQL query references a field
  the sidecar schema does not define. Body lists the offending operation.
- `nav_coverage` FAIL — a collection handle from `data/collections.json`
  is unreachable from the rendered nav.
- `no_brand_leak` FAIL — a non-allowlisted capitalized token appeared in
  `hydrogen/app/**`. Body lists `<file>:<line> <token>` and embeds the
  full allowlist (AGENTS.md §2). Replace the token with the allowlisted
  equivalent or with descriptor-shaped prose.
- `quality_judge` / `cross_task_consistency` FAIL — LLM verdict body
  describes the gap. Treat it as the most recent product / design
  review.

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

1. **`artifact/manual/manual.md`** — your task brief points at named
   surfaces; read those sections. Capture the structural details (column
   counts, sticky behavior, variant axes, …) you will translate into
   TSX.
2. **`artifact/manual/capabilities.json`** — the closed schema. Use it
   as ground truth when the prose in `manual.md` is ambiguous; if a
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

---

## 3. What to do

The seven `gen_*` tasks divide the storefront into disjoint slices. The
specifics live in the task brief; the contract below is what every
`gen_*` task shares.

1. **Stay in your slice.** Each task owns a defined subtree of
   `hydrogen/app/`:

   | Task              | Owned slice                                                                            |
   | ----------------- | -------------------------------------------------------------------------------------- |
   | `gen_theme`       | `app/styles/`, `app/root.tsx` (theme bindings only), tailwind / token config.          |
   | `gen_navigation`  | `app/components/Header.tsx`, `app/components/Footer.tsx`, `app/components/MegaMenu.tsx`, `app/components/MobileNav.tsx`, `app/components/AnnouncementBar.tsx`. |
   | `gen_homepage`    | `app/routes/_index.tsx`, hero / featured-collection / promo-banner components used only by the homepage. |
   | `gen_collections` | `app/routes/collections.*.tsx`, `app/components/CollectionGrid.tsx`, `app/components/ProductItem.tsx`, filter / sort components. |
   | `gen_product`     | `app/routes/products.$handle.tsx`, `app/components/ProductGallery.tsx`, `app/components/VariantSelector.tsx`. |
   | `gen_cart_search` | `app/components/CartDrawer.tsx`, `app/components/PredictiveSearch.tsx`, the cart / search route loaders. |
   | `gen_info_pages`  | `app/routes/pages.$handle.tsx`, `app/routes/policies.$handle.tsx`, FAQ / about / contact static routes. |
   | `visual_polish`   | Cross-cutting CSS / spacing / responsive tweaks. No new components.                    |

   Touching another slice is **`consolidate`'s** job, not yours. If you
   discover that another slice needs to change, stop, mark your task
   `[!] needs cross-task fix in <slice>`, and the orchestrator's
   append-redo flow + the `consolidate` task will pick it up.

2. **Talk to the sidecar via the Storefront API client.** Hydrogen
   ships a typed Storefront client (`createStorefrontClient` from
   `@shopify/hydrogen` or the equivalent route loader helpers in the
   template). Use the queries the template already declares for shape;
   add new queries when you need new fields. Do not import JSON from
   `data/`.

3. **Type-check + build before you exit.** Run
   `pnpm --filter hydrogen tsc --noEmit` and
   `pnpm --filter hydrogen build`. The harness verifier set will rerun
   them — but catching errors before exit saves a retry cycle.

4. **Mark `plan.md`.** Flip your task line to `[x]` on success or
   `[!] <one-line reason>` if blocked / partial. Edit only your line.
   Leaving it `[ ]` aborts the run.

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
   in the same block. The `routes_200` verifier owns the canonical
   check.
4. **Do not re-read files you just wrote** — trust the write. Only
   re-read when verifier feedback says the write went wrong.

---

## 5. Self-check before exit

- Every file you wrote lives under `artifact/hydrogen/`.
- `pnpm --filter hydrogen tsc --noEmit` passes.
- `pnpm --filter hydrogen build` succeeds.
- No real-world brand, store name, or domain is hard-coded anywhere in
  your diff. Brand-shaped strings come from the dataset or the AGENTS.md
  §2 allowlist.
- `plan.md` shows your selected task as `[x]` (or `[!] <reason>`); no
  other task's checkbox changed.
