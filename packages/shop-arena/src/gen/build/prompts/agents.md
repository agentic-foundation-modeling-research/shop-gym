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
operations it needs. When `artifact/backend/` changed, the sidecar restarts
automatically before your next `run_command` or `screenshot_page` and before
the verifiers run. If it cannot start, the `run_command` output begins with a
`Warning:` line that names `sidecar.log`; fix the backend before you continue.

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
                          (read-only when backend generation is disabled)
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
  edit `artifact/backend/` only. When backend generation is disabled,
  `artifact/backend/` is read-only for every task. The `owned_files`
  verifier fails an edit to a read-only path and reports an edit in the
  other copy.
- Inside `artifact/backend/`, `src/data/schema.ts`, `src/sandbox/**` and
  `tests/contract/**` are the sandbox contract and must stay byte-identical
  to the template.
- Never edit `template.json` or `.env` files; the orchestrator owns them.

Final action of any executor iteration: edit `plan.md` to mark **only your
selected task** as `[x]` (success) or `[!]` (blocked). The task line keeps
its exact shape `- [<marker>] <task_id> — <brief> [priority: N]`; a
blocked reason goes into the brief after the separator, never after the
priority. Do not touch any other task's line. An iteration that times out,
leaves `plan.md` unparseable or breaks this protocol is discarded: the
harness restores `artifact/` to its state before the iteration.

---

## 3. Tooling

You have five tools. Every path is relative to `<run_dir>`.

| Tool              | Use                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------ |
| `read_file`       | read a text file (`offset` continues a long one)                                     |
| `write_file`      | create or replace a file                                                             |
| `list_dir`        | list a directory                                                                     |
| `run_command`     | run a shell line with `sh -c` (`cwd` picks the directory); returns exit code + output |
| `screenshot_page` | render a storefront route at the judge's desktop and mobile viewports                |

Node 20+ and pnpm are available. Both template copies are standalone pnpm
projects (dependencies already installed; `pnpm install --ignore-workspace`
re-runs are idempotent). Run scripts from inside the copy via `run_command`:

- Storefront: `pnpm typecheck && pnpm build` with `cwd: artifact/storefront`.
- Backend: `pnpm typecheck`, `pnpm test`, and `pnpm codegen` after editing
  any SDL module under `src/schema/`, with `cwd: artifact/backend`.
- Query the sidecar with `curl -s {{backend_url}}/graphql -H 'content-type: application/json' -d '{"query":"{ shop { name } }"}'`
  when you need real data shapes.

`screenshot_page` rebuilds and serves the storefront copy on demand and
returns exactly the captures the `visual_judge` verifier scores. Look at
every page you styled before you mark the task done; the judge will.

When the command of a `run_command` call exits or times out, every process
it started is killed, also the processes you put in the background. To try
a server, start it, query it and stop it inside one call.

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

"Storefront tasks" are all tasks other than `gen_backend` and `backend_*`.
The backend rows run only when backend generation is enabled.

| Name                | Applies to                                     | Checks                                                                       |
| ------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------- |
| `owned_files`       | every task                                     | edits stay in the task's template copy; read-only paths unchanged            |
| `typecheck`         | storefront tasks                               | `pnpm typecheck` in `artifact/storefront`                                    |
| `build`             | storefront tasks                               | `pnpm build` in `artifact/storefront`; the verifiers below serve this build  |
| `routes_200`        | storefront tasks                               | the static routes and the dataset routes of every page return 200            |
| `backend_typecheck` | `gen_backend`, `backend_*`                     | `pnpm typecheck` in `artifact/backend`                                       |
| `backend_test`      | `gen_backend`, `backend_*`                     | `pnpm test` in `artifact/backend`                                            |
| `sandbox_contract`  | `gen_backend`, `backend_*`                     | read-only backend paths unchanged; `tests/contract` suite passes             |
| `data_in_use`       | every task                                     | every storefront GraphQL operation validates against the live schema         |
| `nav_coverage`      | `gen_theme`, `gen_navigation`, `visual_fix`    | every `navigation.json` target returns 200 and is a header or footer link    |
| `cart_conformance`  | `gen_product`, `gen_cart_search`, `visual_fix` | cart and checkout forms add, update, remove and order as the backend records |
| `visual_judge`      | page tasks (below), `visual_fix`               | a model judges the task's pages at desktop and mobile size                   |

A storefront that does not build or start fails every verifier that serves it
(`routes_200` and the rows after `data_in_use`) with the same error, so fix
`build` first. The page tasks are `gen_homepage`, `gen_navigation`,
`gen_collections`, `gen_product`, `gen_cart_search` and `gen_info_pages`;
`visual_judge` judges the pages each one builds and every page for
`visual_fix`. After a task fails `visual_judge` a fixed number of times, its
`visual_judge` result becomes `advisory`.

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
