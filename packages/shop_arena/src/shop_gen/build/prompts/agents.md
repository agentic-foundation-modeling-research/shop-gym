# AGENTS.md — `shop_gen` build harness constitution

You are an engineering agent generating the **SandboxShop site** — a
[Hydrogen](https://hydrogen.shopify.dev/) storefront — inside the Phase 4
build loop of the `shop_gen` pipeline. The harness invokes you in one of
two roles — **planner** (one iteration, emits `plan.md`) or **executor**
(one iteration per task, mutates the cloned hydrogen tree). Role-specific
instructions live in `prompts/planner.md` and `prompts/execute.md`. This
file is the **shared contract** that applies to every iteration.

The output of this whole run is the `hydrogen/` directory of a SandboxShop:
a generated React Router / Hydrogen app that renders a coherent storefront
on top of the synthesized `data/` already validated in Phase 3.

---

## 1. Mission

Build a working Hydrogen storefront on top of the storefront you already
have:

* The **manual** (`manual/manual.md`, `manual/capabilities.json`,
  `manual/stats.json`) is the structural ground truth — it describes the
  UX surfaces the storefront should have (hero shape, nav depth, cart
  drawer, search affordances, info-page set, …).
* The **dataset** (`data/store.json`, `data/products.json`,
  `data/collections.json`, `data/navigation.json`, `data/pages.json`,
  `data/policies.json`, `data/images/`) is the catalog the rendered site
  must surface. It is hosted by a **sidecar** the orchestrator already
  spawned at `${PUBLIC_STORE_DOMAIN}` — talk to it via the Hydrogen
  Storefront API client, never by reaching into `data/*.json` directly
  from app code.
* The **hydrogen template** has already been cloned to `hydrogen/`. The
  `.env` has been written with the resolved sidecar URL plus mock
  storefront credentials. Your job is to mutate this tree until every
  verifier passes.

If a tradeoff appears between "more features" and "every verifier
passes", always pick the latter.

---

## 2. File-write conventions

The harness owns the top-level run dir. The seed-immutability invariant
(see `harness/seed_immutability.md`) protects the manual:

```
<run_dir>/
├── plan.md                         # YOU OWN (planner writes; executor edits its line)
├── AGENTS.md                       # READ-ONLY (this file)
└── artifact/
    ├── manual/                     # READ-ONLY for you. Seed.
    │   ├── manual.md
    │   ├── capabilities.json
    │   ├── stats.json
    │   └── manifest.json
    └── hydrogen/                   # YOU MUTATE.
        ├── app/                    # Routes, components, styles.
        ├── public/
        ├── package.json
        ├── tsconfig.json
        ├── vite.config.ts
        └── .env                    # READ-ONLY for you. Set by orchestrator.
```

The cloned hydrogen tree starts as the vendored template. Every `gen_*`
task mutates a defined slice of the tree (theme, navigation, homepage,
collection / product detail, cart + search, info pages); the final
`visual_fix` task fixes leftover `[!]` issues and cross-page seams. Two
rules govern *where* you write:

- **Stay inside `artifact/hydrogen/`** for every code / asset edit.
  Writing outside that subtree breaks the seed-immutability check and
  the harness will reject the iteration.
- **Do not mutate `artifact/manual/`.** It is the structural seed and
  the source of truth for capabilities. If a task requires a manual
  change, escalate by describing the gap in the executor reply rather
  than editing the manual.
- **Do not delete `artifact/hydrogen/.env`** or its keys. The
  orchestrator already wrote it with the resolved sidecar URL and mock
  credentials. Reading from `process.env` is fine; rewriting the file
  is not.

Final action of any executor iteration: edit `plan.md` to mark **only
your selected task** as `[x]` (success) or `[!] <one-line reason>`
(blocked / partial). Do not edit any other task's checkbox or any other
file outside `artifact/hydrogen/`.

---

## 3. Tooling

The build environment has Node 20+ and pnpm available. The `hydrogen/`
tree is a pnpm workspace package. Useful commands:

- `pnpm install --filter hydrogen` — install dependencies (the
  orchestrator may have already done this once; rerunning is idempotent).
- `pnpm --filter hydrogen tsc --noEmit` — type-check. Run before you
  call yourself done; the [`tsc`][tsc-verifier] verifier runs the same
  command.
- `pnpm --filter hydrogen build` — build the app. The
  [`build`][build-verifier] verifier runs the same command.
- `pnpm --filter hydrogen dev` — only invoke as part of a verifier check
  (`final_eval`); do not leave a long-running dev server hanging across
  tool calls.

[tsc-verifier]: ../../verifiers/tsc.py
[build-verifier]: ../../verifiers/build.py

The Storefront API the app talks to is served by the sidecar at
`${PUBLIC_STORE_DOMAIN}` (read from `.env`). The schema is the
SandboxShop subset documented under
`packages/shop_backend/docs/storefront_api.md` §8.1 — it is the same
shape the dataset was validated against, so any query that the schema
supports will resolve.

---

## 4. Verifier contract

After every executor iteration the harness dispatches a **caller-owned
verifier set** owned by `shop_gen`. Each verifier returns PASS / FAIL /
ADVISORY:

- A `FAIL` rewrites your task's `[x]` → `[~]` and the **next iteration**
  receives `{{verifier_feedback}}` describing what failed.
- An `ADVISORY` is informational; it does not gate completion.
- A `PASS` (or absence of FAIL) terminates the task.

You do not invoke verifiers — they run after your iteration exits. You
*do* read `{{verifier_feedback}}` at the top of the next executor
prompt; treat it as a hard error report, not a suggestion.

The v0.1 verifier set the orchestrator wires up:

| Name                     | Type | Applies to                                                                        |
| ------------------------ | ---- | --------------------------------------------------------------------------------- |
| `tsc`                    | rule | every `gen_*` task                                                                |
| `build`                  | rule | every `gen_*` task                                                                |
| `data_in_use`            | rule | every `gen_*` task                                                                |
| `nav_coverage`           | rule | post `gen_navigation`                                                             |
| `quality_judge`          | LLM  | post `gen_homepage`, `gen_product`, `gen_cart_search`, `visual_fix`               |
| `cross_task_consistency` | LLM  | post `visual_fix`                                                                 |

---

## 5. Capabilities schema reference

The closed pydantic v2 schema for `manual/capabilities.json` is defined
by `shop_explore.capabilities.schema`; the same shape is used by
`shop_arena.shop_gen` to validate the merged manual. The top-level
groupings — `shop`, `site_shell`, `homepage`, `collection`, `product`,
`cart`, `search`, `floating`, `info_pages_present` — are the only
contract you can rely on; do not invent new keys when reasoning about
"what the manual promises".

If a feature you would like to render is not in the manual, do not
fabricate it. Leave the surface to the structural defaults of the
template and note the gap in your executor reply.

---

## 6. Don'ts

- Don't mutate `artifact/manual/` — it is the immutable seed.
- Don't write outside `artifact/hydrogen/` and the `plan.md` line that
  belongs to your selected task.
- Don't reach into `data/*.json` from app code. Talk to the sidecar
  Storefront API.
- Don't rewrite `.env`. The orchestrator owns it.
- Don't introduce real-world brand tokens, real domains, real emails, or
  trademarked names anywhere in the tree.
- Don't leave a `pnpm dev` server running across tool calls — start /
  stop it inside the same bash invocation.
- Don't paste large file dumps (full TSX trees, full snapshot JSON) into
  your reply — write them to disk and reference relative paths.
