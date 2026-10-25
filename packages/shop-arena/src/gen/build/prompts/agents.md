# AGENTS.md - ShopArena build loop contract

You are an engineering agent generating a **SandboxShop** inside the ShopArena
build loop. The harness invokes you in one of two roles: **planner** (one
iteration, writes `plan.md`) or **executor** (one iteration per task, edits the
seeded template copies). Role-specific instructions live in
`prompts/planner.md` and `prompts/execute.md`. This file is the shared
contract that applies to every iteration.

The output of the run is `artifact/storefront/` (a React Router SSR
storefront) and `artifact/backend/` (the GraphQL backend copy that serves the
dataset). Backend generation is **{{gen_backend_mode}}** for this run.

---

## 1. Mission

Build a working storefront on top of the inputs you already have:

* The **manual** (`artifact/manual/manual.md`, `artifact/manual/capabilities.json`,
  `artifact/manual/stats.json`) is the structural ground truth: it describes
  the UX surfaces the storefront should have.
* The **dataset** (`artifact/data/*.json`, `artifact/data/images/`) is the
  catalog the rendered site must surface. It is served by the **backend
  sidecar** at `{{backend_url}}` (GraphQL endpoint `{{backend_url}}/graphql`,
  health check `{{backend_url}}/health`). Storefront code talks to the
  sidecar over GraphQL; it never reads `artifact/data/*.json` directly.
* The **templates** are already seeded: `artifact/storefront/` and
  `artifact/backend/` are copies of the tracked template files with
  dependencies installed. Your job is to edit these copies until every
  verifier passes.

When backend generation is enabled, the `gen_backend` task runs first and may
extend the backend's schema, resolvers and state so the storefront has the
operations it needs. The sidecar is restarted automatically after any
iteration that changes `artifact/backend/`.

If a tradeoff appears between "more features" and "every verifier passes",
pick the latter.

---

## 2. File-write conventions

```
<run_dir>/
  plan.md                 YOU OWN (planner writes; executor edits its own line)
  AGENTS.md               read-only (this file)
  artifact/
    manual/               read-only seed
    data/                 read-only seed
    storefront/           storefront template copy: storefront tasks edit it
      template.json       read-only fingerprint
    backend/              backend template copy: backend tasks edit it
      template.json       read-only fingerprint
      src/data/schema.ts  read-only (dataset contract)
      src/sandbox/**      read-only (episode isolation)
      tests/contract/**   read-only (sandbox contract suite)
```

- Every code or asset edit stays inside `artifact/storefront/` or
  `artifact/backend/`. Writing anywhere else under `artifact/` breaks the
  seed-immutability check and the harness rejects the iteration.
- Storefront tasks (`gen_theme`, `gen_navigation`, ...) edit
  `artifact/storefront/` only. Backend tasks (`gen_backend`, `backend_*`)
  edit `artifact/backend/` only. The `owned_files` verifier reports edits
  outside your task's slice.
- Inside `artifact/backend/`, the allowed paths are `src/schema/**`,
  `src/resolvers/**`, `src/state/**`, `src/__generated__/**` (via
  `pnpm codegen`), co-located `*.test.ts` files, `src/data/loader.ts` and
  `src/data/types.ts` (wiring only), `tests/fixtures/**`, and
  `package.json` dependencies. `src/data/schema.ts`, `src/sandbox/**` and
  `tests/contract/**` are the sandbox contract and must stay byte-identical
  to the template.
- Never edit `template.json` or `.env` files; the orchestrator owns them.

Final action of any executor iteration: edit `plan.md` to mark **only your
selected task** as `[x]` (success) or `[!] <one-line reason>` (blocked).
Do not touch any other task's line.

---

## 3. Tooling

Node 20+ and pnpm are available. Both template copies are standalone pnpm
projects (dependencies already installed; `pnpm install --ignore-workspace`
re-runs are idempotent). Run commands from inside the copy:

- Storefront: `cd artifact/storefront && pnpm typecheck` and `pnpm build`.
- Backend: `cd artifact/backend && pnpm typecheck`, `pnpm test`, and
  `pnpm codegen` after editing any SDL module under `src/schema/`.
- Query the sidecar with `curl -s {{backend_url}}/graphql -H 'content-type: application/json' -d '{"query":"{ shop { name } }"}'`
  when you need real data shapes.

Do not start long-running dev servers across tool calls; start and stop them
inside one bash invocation.

---

## 4. Verifier contract

After every executor iteration the harness dispatches the verifier set. Each
verifier returns `pass`, `fail` or `advisory`:

- A `fail` rewrites your task's `[x]` to `[~]` and the next iteration
  receives the report in `{{verifier_feedback}}`.
- An `advisory` is informational; it does not gate completion.
- `pass` (or no `fail`) lets the task stand.

You never invoke verifiers yourself; you read their feedback at the top of the
next executor prompt and treat it as a hard error report.

| Name                | Applies to                                  | Checks                                                              |
| ------------------- | ------------------------------------------- | ------------------------------------------------------------------- |
| `owned_files`       | every task                                  | edits stay in the task's slice; protected paths unchanged           |
| `backend_typecheck` | `gen_backend`, `backend_*`                  | `pnpm typecheck` in `artifact/backend`                              |
| `backend_test`      | `gen_backend`, `backend_*`                  | `pnpm test` in `artifact/backend`                                   |
| `sandbox_contract`  | `gen_backend`, `backend_*`                  | read-only backend paths unchanged; `tests/contract` suite passes    |
| `data_in_use`       | every task                                  | every storefront GraphQL operation validates against the live schema |

Storefront verifiers (`routes_200`, `nav_coverage`, `visual_judge`) are
added by the orchestrator when the storefront template is wired in.

---

## 5. Don'ts

- Don't edit `artifact/manual/` or `artifact/data/`; they are the seed.
- Don't read `artifact/data/*.json` from storefront code; query the sidecar.
- Don't edit `src/data/schema.ts`, `src/sandbox/**` or `tests/contract/**`
  in the backend copy.
- Don't introduce real-world brand tokens, real domains, real emails, or
  trademarked names anywhere in the tree.
- Don't paste large file dumps into your reply; write them to disk and
  reference relative paths.
