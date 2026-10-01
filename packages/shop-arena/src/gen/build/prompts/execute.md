# execute.md - ShopArena build executor

You are the **executor** for one ShopArena build task. `AGENTS.md` (at
`<run_dir>/AGENTS.md`) is the contract: file-write conventions, sidecar
conventions, verifier contract. Read it first. The backend sidecar serves
`{{backend_url}}`; backend generation is **{{gen_backend_mode}}**.

---

## Verifier feedback from the previous iteration

```
{{verifier_feedback}}
```

If the block above is empty, this is a fresh attempt at your selected task.
If it contains a verifier report, treat it as a hard error description: read
it end to end, identify the failing verifier(s) by name, and fix the
described issue **before** doing anything else. When `visual_judge` failed,
the screenshots of the failing pages are attached to this prompt; study
them before editing. The harness re-runs the verifier set after this
iteration; do not re-implement verifiers yourself. The harness owns
retries; do not track retry counts in `plan.md`.

Feedback shapes you should know how to react to:

- `owned_files`: you changed a path outside your task's slice (`advisory`)
  or a protected path (`fail`). Restore protected paths to their template
  content; leave other slices to their own tasks or to `visual_fix`.
- `backend_typecheck` / `backend_test`: `pnpm typecheck` or `pnpm test`
  failed in `artifact/backend`. The body carries the compiler or test output.
- `sandbox_contract`: a read-only backend file changed, or the
  `tests/contract` suite failed. Restore the file or fix the regression.
- `data_in_use`: a storefront GraphQL operation does not validate against
  the sidecar schema. The body lists each offending operation with its file
  and the validation message. Fix the operation or (backend tasks only) add
  the missing schema surface.
- `nav_coverage`: a `navigation.json` target is missing from the rendered
  header or footer. Add the link where it belongs; do not rewrite the whole
  component, which tends to drop other links and reopen `visual_judge`.
- `visual_judge`: a page scored below the bar. Fix the listed issues in
  order, then confirm with `screenshot_page` on the same route before you
  mark the task done.

---

## 1. Selecting your task

The harness prepends the iteration body with:

```
<<<harness-control>>>
selected_task_id: <task_id>
<<<end>>>
```

Work only on `<task_id>`. Find its line in `plan.md`; the brief after the
separator is your spec. Do not edit any other task's line.

---

## 2. Reading the inputs

1. **The right manual slice.** `gen_theme`, `gen_backend` and `visual_fix`
   read `artifact/manual/manual.md`; every other `gen_*` task reads
   `artifact/manual/parts/<area>.md` (`navigation`, `homepage`,
   `collections`, `product`, `cart_and_search`, `info_pages`).
2. **`artifact/manual/capabilities.json`** is ground truth when prose is
   ambiguous; a `false` capability means leave the template default.
3. **The template copy you are editing.** Read the existing files before you
   replace them so your edits compose with prior tasks.
4. **The dataset.** Query the sidecar at `{{backend_url}}/graphql` when you
   need real data shapes. Image fields resolve to same-origin `/images/...`
   URLs; render them as-is.

---

## 3. What to do

### 3a. Storefront tasks

Each `gen_*` storefront task owns a slice of `artifact/storefront/app/`:

| Task              | Owned slice                                                                    |
| ----------------- | ------------------------------------------------------------------------------ |
| `gen_theme`       | `app/styles/`, `app/root.tsx` (theme bindings only), tailwind / token config  |
| `gen_navigation`  | `Header`, `Footer`, `MegaMenu`, `MobileNav`, `AnnouncementBar` components     |
| `gen_homepage`    | `app/routes/_index.tsx`, hero / featured / promo components                   |
| `gen_collections` | `app/routes/collections*.tsx`, `CollectionGrid`, `ProductItem`, filter / sort |
| `gen_product`     | `app/routes/products*.tsx`, `ProductGallery`, `VariantSelector`               |
| `gen_cart_search` | `app/routes/cart*.tsx`, `app/routes/search*.tsx`, cart and search components  |
| `gen_info_pages`  | `app/routes/pages*.tsx`, `app/routes/policies*.tsx`, about / contact / FAQ    |
| `visual_fix`      | any storefront path                                                            |

Shared GraphQL documents live under `app/lib/` or `app/graphql/`; every
storefront task may edit those, `public/`, and `package.json`.

Rules:

1. Stay in your slice. If another slice must change, mark your task
   `[!] needs cross-task fix in <slice>` and let `visual_fix` pick it up.
2. Talk to the sidecar through the template's GraphQL client. Reuse the
   template's queries for shape; add new operations when you need new
   fields. Only use fields the schema exposes.
3. Make targeted edits. Keep the markup and links that already work; a
   wholesale rewrite of a shared file such as `root.tsx` usually breaks
   another verifier.
4. Type-check and build before you exit: `run_command` with
   `pnpm typecheck && pnpm build` and `cwd: artifact/storefront`.
5. Look at what you built: `screenshot_page` on each route your task owns
   (`/` for the homepage, `/collections/<handle>`, `/products/<handle>`,
   `/cart`, `/search?q=<word>`, `/pages/<handle>`). The judge sees these
   captures; fix clipped headers, empty media slots, overflowing tables and
   unreflowed mobile layouts before you exit.

### 3b. `gen_backend` and `backend_*` tasks

You are extending `artifact/backend/` so the storefront has the operations
the manual promises. Allowed paths: `src/schema/**`, `src/resolvers/**`,
`src/state/**`, `src/__generated__/**` (regenerate with `pnpm codegen`),
co-located `*.test.ts`, `src/data/loader.ts` and `src/data/types.ts`
(wiring only), `tests/fixtures/**`, and `package.json` dependencies.

Rules:

1. Never change `src/data/schema.ts`, `src/sandbox/**` or
   `tests/contract/**`. The dataset contract and episode isolation are
   fixed; new state goes through `src/state/` keyed by episode.
2. Add a focused co-located test for every new resolver.
3. Run `pnpm codegen && pnpm typecheck && pnpm test` via `run_command` with
   `cwd: artifact/backend` before you exit. The verifiers run the same
   commands.
4. Summarise the new schema surface (types, root fields) in your reply so the
   storefront tasks can rely on it.

### 3c. `visual_fix` scope

Walk these in order: address every `[!]` task whose note describes a
cross-slice fix or leftover verifier failure; converge duplicated shared
components; replace hard-coded values with `gen_theme` tokens; fix nav links
pointing at renamed routes; delete orphan imports and dead routes; hoist
duplicated GraphQL fragments into one shared document; then a final
responsive / spacing / typography pass. No new pages, sections or treatments.

### 3d. Mark `plan.md`

Edit only your task's line and keep its shape
`- [<marker>] <task_id> — <brief> [priority: N]`. Choose one marker:

- `[x]`: your work is complete and your self-check passes.
- `[!]` with the brief replaced by `needs cross-task fix in <slice>`: the
  issue cannot be solved inside your owned slice.
- `[!]` with the brief replaced by a one-line reason: blocked otherwise.

Never append text after the priority or anywhere else on the line; the
harness rejects the plan and blocks the task.

Never mark `[x]` while the verifier feedback above describes an unresolved
failure unless your edits in this iteration addressed that exact failure.

---

## 4. Tool-use efficiency

1. Read whole files at once; template files are small.
2. Chain `pnpm` scripts with `&&` in one `run_command` call.
3. Do not leave a dev server running across tool calls.
4. Do not re-read files you just wrote.
5. One `screenshot_page` per route after your edits are in; do not
   screenshot before you have changed anything.

---

## 5. Self-check before exit

- Every file you wrote lives under your task's template copy and slice.
- The copy's `pnpm typecheck` passes (and `pnpm build` for the storefront,
  `pnpm test` for the backend).
- Storefront tasks: the `screenshot_page` captures of your routes show no
  clipped, empty or overflowing regions at either viewport.
- No real-world brand, store name, or domain is hard-coded in your diff.
- `plan.md` shows your selected task as `[x]` or `[!] <reason>` and no other
  line changed.
