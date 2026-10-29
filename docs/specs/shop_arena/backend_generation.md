# Backend Generation (`packages/shop-arena/src/gen/build`)

Status: **Implemented** (v1.1 M5) · Version: **0.1**
Owners: ShopArena

> The v1.1 build loop: both templates seeded from `git ls-files`, the shop's
> own backend copy run as a sidecar, a `gen_backend` task that lets the agent
> extend the GraphQL API, owned-file rules, and the four backend verifiers
> (`backend_typecheck`, `backend_test`, `sandbox_contract`, `data_in_use`).

---

## 1. Overview

v1.0 generated storefronts against a shared, read-only `shop_backend`. Every
shop exposed the same schema, so an agent could only re-skin data it could
already query. v1.1 (`v1_1_typescript_redesign.md`, section 5.7.1) seeds a
private copy of `packages/shop_backend` into each build run, hosts the shop
from that copy forever after, and (with `--gen-backend`) lets the build agent
change the schema, resolvers and state as long as the sandbox contract holds.

This spec covers milestone M5: the TypeScript `runBuildLoop` under
`packages/shop-arena/src/gen/build/`, the prompts it ships, the owned-file
table, the seeding and sidecar helpers, and the backend verifier set. The
storefront verifiers (`routes_200`, `nav_coverage`, `visual_judge`) and the
`shop-arena gen` CLI wiring (`--gen-backend`) belong to M7.

## 2. Terminology

- **Template**: a git-tracked directory copied into a run. Two exist:
  `packages/shop-arena/templates/storefront` and `packages/shop_backend`.
- **Seeding**: copying exactly the template's `git ls-files` output into
  `<runDir>/artifact/{storefront,backend}/` and running
  `pnpm install --ignore-workspace` there.
- **Template fingerprint** (`template.json`): `{ name, commit, contentHash,
  files, seededAt }` written into every seeded copy; `files` maps each
  tracked path to its sha256.
- **Sidecar**: the run's `artifact/backend` started as a child process
  (`node --import tsx src/cli.ts artifact/data <port>`) for the whole loop.
- **Owned files**: the paths a task may change. Backend tasks own the
  backend copy and every other task owns the storefront copy. Protected
  paths may never change; an edit in the other copy is reported as not
  owned.
- **Read-only backend paths**: `src/data/schema.ts`, `src/sandbox/**`,
  `tests/contract/**` in the backend copy. They define the sandbox contract
  (dataset shape, episode isolation, cart and checkout behaviour) and must
  match the template byte for byte.
- **Verifier**: a harness `Verifier { name, appliesTo, run }` executed after
  each executor iteration; `fail` reopens the task, `advisory` only adds
  feedback.

## 3. Current Status

Implemented on 2026-09-30 (branch `v1_1-m5`). Deviations from section 5.7.1
of `v1_1_typescript_redesign.md`, recorded here rather than silently:

- **Owned-file enforcement is split by severity.** Edits to protected paths
  (read-only backend paths, `template.json`, `storefront/.env`, anything
  outside `artifact/{storefront,backend}`, and all of `backend/` when
  `genBackend` is off) make `owned_files` `fail`. Edits in the other copy
  (a storefront task editing `backend/`, a backend task editing
  `storefront/`) are `advisory`. Python only enforced the table through the
  prompt.
- **No per-task storefront slices (2026-10-28).** The Python slice table
  named files the TypeScript template does not have, and the template keeps
  most of its UI in shared files (`root.tsx`, `app/components/storefront.tsx`,
  `app/lib/queries.ts`), so slices could not be kept. Every storefront task
  owns `storefront/`, and `routes_200` requests every page after each
  storefront task instead of only the task's pages, so a shared-file edit
  that breaks another page fails the task that made it. `visual_judge`
  still judges only the task's page buckets.
- **`artifact/` is checkpointed in git.** `ArtifactCheckpoints` keeps a
  bare repository at `<runDir>/checkpoints.git` with `artifact/` as its
  work tree, so the agent's tools and the published shop never see it.
  The build loop commits after seeding and after each iteration the
  harness keeps, and rolls back to the last commit when the harness
  abandons one (timeout, unparseable plan, protocol violation, runtime
  error), through the harness `onIterationEnd` hook. `owned_files` checks
  the paths changed since the last commit, so a resumed run and the task
  after an abandoned one are not blamed for edits they did not make. The
  seed roots (`data/`, `manual/`, guarded by the harness seed check),
  `node_modules` and build outputs are not tracked; a rollback leaves
  them in place. On resume, what an interrupted iteration left is
  committed as is, matching the harness, which keeps it too.
- **`data_in_use` runs after every task**, not only backend tasks, because a
  schema change in `gen_backend` can break queries the storefront already
  ships. It is skipped (pass) only when no GraphQL document exists.
- **The sidecar restarts on backend changes, not on every iteration.**
  `BackendSidecar.ensureCurrent()` hashes `artifact/backend/src` plus
  `package.json` and restarts when the digest moved, or launches again when
  the last launch failed. It is awaited before every `run_command`, before
  `screenshot_page` and the storefront verifiers bring up the storefront,
  and before `data_in_use` introspects the schema. A failed launch is
  reported to the agent (a `Warning:` line above the `run_command` output,
  or a failing verifier), and the next call retries, so a fixed edit brings
  the sidecar back. Outside `start()` / `stop()` the call is a no-op.
- **`sandbox_contract` runs the template's contract suite on the backend
  fixture**, because `tests/contract/helpers.ts` hardcodes
  `tests/fixtures/sandbox_shop_v0`. Running it against the shop's own
  dataset needs a data-dir override in the suite (M4 / M7 follow-up); the
  read-only drift check already runs against the seeded copy.
- **`planner.md` contains the literal U+2014 character** in its canonical
  task list because the harness plan grammar accepts no other separator
  between task id and brief. This is the only place the repository keeps
  that character on purpose.
- **Run metadata.** `runBuildLoop` writes `<runDir>/build.json`
  (`genBackend`, `backendPort`, `backendUrl`, both template fingerprints)
  so a resumed run renders byte-identical prompts, and
  `artifact/storefront/.env` (`PUBLIC_STORE_DOMAIN`, `SHOP_BACKEND_URL`)
  so `pnpm dev` inside the copy talks to the sidecar. `build.json` is
  written last, so a seed that failed (for example in `pnpm install`) leaves
  none. When `build.json` is missing and `runDir` holds only the workspace
  layout with an empty `plan.md` and no iterations, `runBuildLoop` removes
  it and seeds again; any other non-empty `runDir` is refused by the
  harness as before.
- Dropped Python behaviour, on purpose: `quality_judge`, `_redo_N` task
  ids, retry-budget annotations, `prompts/fixes/`, the template override
  shim, and the Hydrogen template.

## 4. Desired Status

- `shop-arena gen build` (M7) calls `runBuildLoop` with the shop's manual
  and dataset, `genBackend` from `--gen-backend`, and the storefront
  verifiers appended to `buildVerifiers(...)`.
- `publish` (M7) copies `artifact/{storefront,backend}` out of the run and
  records both `template.json` fingerprints in `shop.json`.
- Every generated shop boots from its own `backend/` with the contract
  suite green, and every GraphQL document in its storefront validates
  against that backend's schema.

## 5. Proposal

### 5.1 Layout

```
packages/shop-arena/src/gen/build/
  build_loop.ts        runBuildLoop(options): seed, sidecar, verifiers, runPlanExecLoop
  checkpoints.ts       ArtifactCheckpoints (open, commit, rollback, changedPaths)
  seed.ts              seedTemplate / seedBackend / templateFingerprint / template.json
  sidecar.ts           BackendSidecar (start, stop, ensureCurrent), freePort
  owned_files.ts       protected globs + ownedFileViolations(taskId, changedPaths, { genBackend })
  prompts.ts           loadBuildPrompts({ backendUrl, genBackend }), renderPlaceholders
  prompts/             agents.md, planner.md, execute.md (plain markdown)
  tree.ts              snapshotTree / diffTrees / hashSnapshot (sha256 per file)
  verifiers/
    index.ts           buildVerifiers({ genBackend, sidecar, ownedFiles })
    owned_files.ts     OwnedFilesVerifier (paths changed since the last checkpoint)
    backend_commands.ts backend_typecheck (pnpm typecheck), backend_test (pnpm test)
    sandbox_contract.ts read-only drift vs template.json + tests/contract suite
    data_in_use.ts     GraphQL documents validated against the live schema
    subprocess.ts      runCommand, truncateStream, renderCommandFailure
    tasks.ts           isBackendTask
```

### 5.2 Run layout

```
<runDir>/
  AGENTS.md, plan.md, run.json, iters/        harness-owned
  build.json                                  genBackend, port, template fingerprints
  sidecar.log                                 backend stdout/stderr
  checkpoints.git/                            bare repo; work tree artifact/
  artifact/
    data/, manual/                            seed roots (immutable, from artifactSeedDir)
    storefront/                               seeded template + .env + template.json
    backend/                                  seeded shop_backend + template.json
```

### 5.3 Seeding

`seedTemplate({ templateDir, destDir })`:

1. `git ls-files -z` in the template; refuse if `destDir/template.json`
   exists.
2. Copy the listed files only (no untracked scratch, no `node_modules`).
3. If `tsconfig.json` extends a `..`-relative base, copy the base next to it
   and rewrite `extends` to `./tsconfig.base.json` so the copy compiles
   outside the monorepo.
4. Write `template.json`.
5. `pnpm install --ignore-workspace --prefer-offline`, plus
   `--frozen-lockfile` when the template tracks `pnpm-lock.yaml`.

`seedBackend` defaults `templateDir` to `packages/shop_backend` resolved
from the workspace root.

### 5.4 Sidecar

`BackendSidecar` serialises `start`, `stop` and `ensureCurrent` through
one promise chain. The default launcher spawns
`node --import tsx src/cli.ts <dataDir> <port>` with cwd `artifact/backend`,
pipes both streams into `sidecar.log`, and polls `/health` every 100 ms
(15 s budget). Stop sends SIGTERM and SIGKILLs after 3 s. Tests inject a
launcher that runs `createSandboxServer` in-process.

### 5.5 Tasks and owned files

With `genBackend`, the planner emits `gen_backend` at priority 10 ahead of
`gen_theme` (9) and may add further `backend_*` tasks. Owned paths:

| Task | May change (under `artifact/`) |
| --- | --- |
| `gen_backend`, `backend_*` | `backend/**` when `genBackend`; nothing otherwise |
| every other task | `storefront/**` |
| nobody | `backend/src/data/schema.ts`, `backend/src/sandbox/**`, `backend/tests/contract/**`, both `template.json`, `storefront/.env`, anything outside the two copies |

`ownedFileViolations` is pure; `OwnedFilesVerifier` feeds it
`ArtifactCheckpoints.changedPaths()`, the paths changed since the last
kept iteration.

### 5.6 Verifiers

| Name | Applies to | Pass condition |
| --- | --- | --- |
| `owned_files` | all | no protected edits (`fail`); edits in the other copy are `advisory` |
| `backend_typecheck` | backend tasks | `pnpm typecheck` exits 0 in `artifact/backend` (180 s) |
| `backend_test` | backend tasks | `pnpm test` exits 0 (300 s) |
| `sandbox_contract` | backend tasks | read-only paths match `template.json`, then `pnpm exec vitest run tests/contract` exits 0 |
| `data_in_use` | all | every `#graphql`, `graphql\`\``, `gql\`\`` document under `storefront/app` passes `graphql.validate` against the sidecar's introspected schema |

`data_in_use` strips `${...}` interpolations, pools fragment definitions
across files, re-attaches the transitive fragments each operation spreads,
and reports `path: query Name: message` per problem. Command output in
feedback is truncated to 1500 characters per stream.

### 5.7 Loop

`runBuildLoop` is thin: load prompts, create the workspace (fresh, after
removing an unfinished seed) or read `build.json` (resume), seed both templates, write `.env` and `build.json`,
open the `artifact/` checkpoints, start the sidecar, run
`runPlanExecLoop` with the verifier list and an `onIterationEnd` hook that
commits a kept iteration and rolls back an abandoned one, and stop the
sidecar in `finally`. The agent tools and the
storefront verifier targets await `ensureCurrent()` themselves.

## 6. Alternatives

- **Restart the sidecar on every iteration** (Python). Simpler but slow
  (tsx boot per turn) and it discards episode state for no reason.
- **Make `owned_files` edits in the other copy a hard fail.** Rejected: the
  agent would need to revert the file by hand, and the prompt already
  explains the rule; advisory feedback is enough to steer. With
  `genBackend` off, `backend/` is protected instead, because no backend
  verifier would check the edit.
- **Keep per-task storefront slices, mapped onto the template's files.**
  Rejected: the template's shared files serve every page, so most tasks
  would need them and the slices would mostly be advisory noise. A global
  `routes_200` catches the real risk, a task breaking a page it does not
  own.
- **Validate GraphQL by running the storefront's queries against the
  sidecar.** Static `validate()` catches the same schema errors without a
  storefront build and reports the exact offending field.

## 7. Execution Table

| # | Item | Status |
| --- | --- | --- |
| 1 | `seed.ts` (seedTemplate, seedBackend, templateFingerprint) | Done |
| 2 | `sidecar.ts` (BackendSidecar, ensureCurrent) | Done |
| 3 | Prompts with `gen_backend` + owned-file table, `prompts.ts` | Done |
| 4 | `owned_files.ts` + `OwnedFilesVerifier` | Done |
| 5 | `backend_typecheck`, `backend_test`, `sandbox_contract`, `data_in_use` | Done |
| 6 | `runBuildLoop` + `buildVerifiers` | Done |
| 7 | Unit tests (fast) and `SHOPGYM_SLOW_TESTS` end-to-end test | Done |
| 8 | Storefront verifiers (`routes_200`, `nav_coverage`, `visual_judge`) | M7 |
| 9 | CLI `--gen-backend`, `publish` recording `template.json` | M7 |
| 10 | Contract suite against the shop's own dataset | M4 / M7 follow-up |
| 11 | `artifact/` git checkpoints; rollback of abandoned iterations | Done |
| 12 | Two-copy ownership (no storefront slices); `routes_200` on every page | Done |
| 13 | Seed again after a seed that failed before `build.json` | Done |

## 8. Appendix

### 8.1 Running the loop

```ts
import { build, STOREFRONT_TEMPLATE_DIR } from '@shop-gym/shop-arena';

const result = await build.runBuildLoop({
  runDir: 'outputs/shops/demo/runs/build',
  seedDir: 'outputs/shops/demo/seed', // contains data/ and manual/
  storefrontTemplateDir: STOREFRONT_TEMPLATE_DIR,
  backendTemplateDir: build.defaultBackendTemplateDir(),
  genBackend: true,
  runtime,
  model: { provider: 'anthropic', id: 'claude-sonnet-4-5' },
  tools: ['read', 'write', 'edit', 'bash'],
  maxIters: 12,
});
```

### 8.2 Slow test

`SHOPGYM_SLOW_TESTS=1 pnpm --filter @shop-gym/shop-arena test` runs
`build_loop.test.ts` end to end with real `git`, `pnpm install`, a real
`tsx` sidecar, and the real backend typecheck, test and contract suites.
