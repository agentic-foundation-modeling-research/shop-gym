# ShopGym v1.1: TypeScript Redesign

Status: **Implemented** (M0-M11 landed on the `v1_1-dev` branch; cutover
2026-10-01). Where a section says "today", it describes the Python/TS code
on `main` as of 2026-09-30, before the redesign; the execution table records
where each milestone landed.

## 1. Overview

ShopGym v1.0 is three Python packages (`harness`, `shop_arena`,
`shop_guru`) and one TypeScript package (`shop_backend`). Every LLM agent
interaction goes through a CLI subprocess (`pi`, `claude`) whose NDJSON
output is parsed back into a trajectory. The backend is a fixed, read-mostly
Storefront API mirror; only the storefront frontend is generated per shop.

v1.1 rebuilds the repo as a single TypeScript monorepo with:

1. **One agent-runtime seam** (`@shop-gym/agent`) backed in-process by the
   pi SDK, designed so another adapter (Claude Agent SDK, OpenAI Agents,
   OpenHands over RPC) is a new file, not a redesign.
2. **A simplified pipeline** derived from the four real use cases
   (build an environment, author a benchmark, evaluate an agent, measure an
   environment), with one browser-tool stack, one task contract, one
   dataset schema, and one CLI.
3. **A stateful backend** (customers, sessions, profile, addresses, payment
   methods, checkout, orders, returns) with episode-scoped state so many
   agents can run against one shop without interfering, shipped as a
   template that the build agent can modify per shop when asked.

This document is the umbrella plan. Per-package detail specs are listed in
the Execution Table and are written as their milestone starts.

## 2. Terminology

| Term | Meaning |
| --- | --- |
| **SandboxShop** | A hostable, deterministic shop: `data/` (dataset), `storefront/` (generated frontend), `backend/` (per-shop copy of the backend template, agent-modified when enabled), `manual/` (anonymized reference). |
| **Dataset** | The JSON files under `data/` that the backend loads. v1.1 adds `customers.json`, `orders.json`, `commerce.json` (shipping, tax, discounts). |
| **AgentRuntime** | The seam that runs one agentic episode (system prompt + prompt + tools + cwd) and returns a `Trajectory`. Adapters: `pi` (v1.1), others later. |
| **LlmClient** | Tool-less single-shot completion (text or JSON) used by data synthesis and judges. Backed by pi-ai in v1.1. |
| **Tool** | A runtime-neutral tool definition (name, description, JSON schema, `execute`). The browser tools are the main example. |
| **Harness** | The plan-then-execute loop that drives a coding agent across many fresh-context iterations against a workspace with a `plan.md`. |
| **Episode** | One agent attempt at one task against one shop. Episode state (cart, login, orders placed) is isolated from other episodes. |
| **Task** | A benchmark item: `goal` + `eval[]` checks + optional `setup` (persona login, pre-filled cart). |
| **Grader** | Code that turns an episode (final answer, visited URLs, final backend state) and a task's `eval[]` into pass/fail. |
| **Backend template** | `@shop-gym/shop-backend`: a complete, tested, standalone-installable backend. It is both the default backend and the starting point the build agent modifies when `--gen-backend` is on, exactly as the storefront template is for the frontend. |
| **Sandbox contract** | The part of the backend template the agent may not change: dataset loading, the Storefront-API operations the storefront uses, the control API, the `StateSnapshot` shape, and the contract test suite that checks all of it. |

## 3. Current Status

Numbers are hand-written source lines on `main`, excluding tests, vendored
templates, and generated files.

### 3.1 `harness` (Python, ~6.5k lines)

- One entry point, `run_plan_exec_loop`, synchronous and single-threaded.
  Plan grammar (`plan.md`, `[ ] [~] [x] [!]` markers, priorities), protocol
  checks, verifier dispatch, seed immutability, resume, and `run.json`
  telemetry are all solid and spec'd (`docs/specs/harness/*`).
- The `AgentRuntime` protocol is one method, `run_iteration`, returning a
  `Trajectory`. `LLMCompleter.complete` is an optional second method that
  `shop_arena` imports at about 15 sites.
- About 2.8k of the 6.5k lines exist only because pi and claude are
  subprocesses: argv builders, per-iteration `PI_CODING_AGENT_DIR`
  isolation, `models.json` synthesis from env, `.env` discovery, process
  group kill, NDJSON parsing of `native.log`, and a 1.2k-line log viewer.
- Trajectories carry no usage, cost, model, or real per-step timestamps.
- Spec drift exists (`protocol_violation_recovery.md` vs `loop.py`,
  `reconstruct()` still treats executor protocol failures as terminal).

### 3.2 `shop_arena` (Python, ~38k lines plus two vendored templates)

- `explore` (~3.4k): plain-HTTP prefetch (robots, sitemap,
  `products.json`, policies, rate limited), then a harness loop with the
  `pi-playwright` skill and fixed planner tasks, then a deterministic
  deep-merge of per-task `caps.json` into a closed `Capabilities` schema
  and one LLM call for `manual.md`. No verifiers; anonymization rules live
  only in the prompt.
- `gen` (~24k): a step DAG with six staleness triggers and a fingerprint
  cascade over five phases (`manual_merge`, `data_synth`,
  `data_validation`, `build`, `final_eval`). Every LLM call, including
  single-shot data synthesis, spawns a `pi --print` subprocess through
  `LLMCompleter`. The build phase seeds a template into
  `runs/build/artifact/`, starts a `shop_backend` sidecar, and runs the
  harness loop with eleven verifiers (tsc, build, routes_200,
  data_in_use, nav_coverage, cart conformance, three LLM judges, and two
  that are disabled or Hydrogen-only).
- Known gaps: the finished storefront is never copied out of
  `runs/build/artifact/`; the `final_eval` smoke driver raises
  `NotImplementedError`; the brand-leak scanners are disabled; `--only` is
  implemented by appending `_redo_N` tasks to `plan.md`; retry counting is
  delegated to the agent through the prompt; `clone_template` copies
  untracked files (`.env`, `dist/`) from the template source.
- Two templates: Hydrogen (real `@shopify/hydrogen` client, account pages
  bound to Shopify's Customer Account API, 8k-line lockfile) and
  `react-vite` (hand-written fetch client, 9 routes, read-only checkout).
  Build prompts are Hydrogen-worded with a react-vite override shim.
- `env_eval` (~10k src, ~11k tests) measures environment quality through
  BrowserGym. Its only coupling to the rest is `util/_llm.py`, a direct
  Anthropic/OpenAI client with forced JSON output.
- `shop_gen.md` already proposes a v2 orchestration redesign (uniform node
  DAG, filesystem-derived completion, `plan.json`); it was never built.

### 3.3 `shop_guru` (Python, ~9k lines)

- Two systems that do not share code or schemas. v1 (`build` / `eval`)
  fills deterministic templates from `data/` and evaluates with AgentLab
  `GenericAgent` on BrowserGym plus an OpenAI screenshot judge. v2
  (`url_crawler.py` → `explore.py` → `solver.py`) drives the `pi` CLI with
  Playwright MCP and emits WebArena-style tasks (`goal` + `eval[]`).
- Nothing grades v2 answers yet. v1 has no ground truth beyond
  `url_contains`.
- Heavy Python-only dependencies: `agentlab`, `browsergym`, `ray`,
  `gradio`, `litellm`. Roughly 1.5k lines exist to smuggle task specs into
  Ray workers through env vars, temp files, and pickle subclasses.

### 3.4 `shop_backend` (TypeScript, ~5.6k lines)

- graphql-yoga on `node:http`, one process per dataset, Storefront-API
  shaped SDL in a single 835-line string, codegen with drift check, good
  in-process test harness (219 cases on one fixture).
- Read-only catalog, search, content, metafields; cart mutations with an
  in-memory `CartStore` (optional whole-file JSON persistence).
- No customers, auth, checkout, orders, tax, shipping, or real discounts.
  `checkoutUrl` is `'#'`. No reset or state inspection endpoint, so
  episode isolation relies on process restarts.
- The dataset contract is duplicated between `loader.ts` type guards and
  the pydantic `schema.py` in `shop_arena`.

### 3.5 Cross-cutting

- Three browser stacks: `pi-playwright` skill (arena explore, visual
  judge), Playwright MCP via `pnpm dlx` (guru v2), BrowserGym (guru v1,
  env_eval).
- Two coding-agent invocation styles: the isolated harness runtime and the
  inline `pi -nc -p` calls in guru v2 that depend on the user's global pi
  config.
- Two task formats, two output trees, two config systems (`uv` + `pnpm`).

## 4. Desired Status

1. **Single language and toolchain.** `pnpm` workspace, `tsc` strict,
   `biome`, `vitest`. No Python in the build or runtime path.
2. **One agent seam.** All agentic work (build loop, explore, solve,
   judges, data synth) goes through `@shop-gym/agent`. Switching the
   adapter is a config value. Trajectories are uniform and carry usage and
   cost.
3. **One browser stack.** `@shop-gym/browser` wraps Playwright for Node
   and exposes the same tool set to every agent, plus snapshot and
   screenshot helpers for graders and judges.
4. **One dataset schema** (owned by the backend template, imported by
   arena), one task contract, one result contract (`@shop-gym/core`),
   shared by arena and guru.
5. **Stateful, episode-scoped backend** with customers, checkout, and
   orders, a sandbox control surface (`reset`, `state`), and deterministic
   ids and clocks.
6. **Backend generation is a switch.** Every shop gets its own copy of
   the backend template. With `--gen-backend` the build agent modifies
   and extends that copy under the same plan-exec loop as the storefront;
   a sandbox contract plus verifiers keep it gradable.
7. **Benchmarks are gradable without an LLM** where possible: locator
   probes, URL checks, and backend state checks; the LLM judge is the
   fallback, not the default.
8. **Smaller.** Target under 30k hand-written TS lines for everything that
   is in scope, versus about 54k Python plus 5.6k TS today (about 44k
   Python once `env_eval` is excluded).

## 5. Proposal

### 5.1 Repository layout

```
shop-gym/
├── packages/
│   ├── core/          @shop-gym/core      dataset / task / result schemas (zod), step pipeline, env + config loading
│   ├── agent/         @shop-gym/agent     AgentRuntime, LlmClient, Tool, Trajectory; adapters/pi
│   ├── browser/       @shop-gym/browser   Playwright session, agent tools, snapshot + screenshot helpers
│   ├── harness/       @shop-gym/harness   plan-exec loop, workspace, seed immutability, verifiers, resume
│   ├── shop-backend/  @shop-gym/shop-backend  backend template: Storefront-API server, state store, sandbox control API, dataset schema
│   ├── shop-arena/    @shop-gym/shop-arena    explore, gen (data synth, build loop, final eval), templates/
│   ├── shop-guru/     @shop-gym/shop-guru     task generation, validation, solving, grading, aggregation
│   └── cli/           shopgym             one binary: explore | gen | host | guru | doctor
├── docs/specs/
├── outputs/
└── scripts/           thin shell shims only
```

Dependency direction is strictly downward: `cli → {arena, guru} →
{backend, harness, browser} → agent → core`. The backend template has no
workspace dependencies at all, so a seeded copy installs with
`pnpm install --ignore-workspace` like the storefront template. No
package imports another's internals; each exposes `src/index.ts`.

Prompts stay as plain, self-contained `.md` files next to the code that
uses them (no templating engine); the only substitution is a small set of
`{{name}}` placeholders resolved by a 20-line helper.

### 5.2 `@shop-gym/core`

- `schema/task.ts`, `schema/result.ts`: the benchmark contract (§5.8).
  The dataset schema is not here: it lives in the backend template
  (§5.6.1) because the template must install standalone.
- `pipeline/`: the step DAG. A `Step` declares `id`, `inputs`, `outputs`,
  `run(ctx)`. Completion is derived from the filesystem (declared outputs
  exist and the recorded input fingerprint matches). `--from <id>` cleans
  that step's outputs and everything downstream. This is the `shop_gen.md`
  v2 orchestration, reduced to one module of about 300 lines and shared by
  arena and guru.
- `env.ts`: loads the project `.env` once, explicitly, and returns a typed
  `Credentials` object. No module reads `process.env` at import time.

### 5.3 `@shop-gym/agent`: the swappable runtime seam

```ts
interface AgentRuntime {
  readonly name: string;
  run(req: AgentRunRequest): Promise<AgentRunResult>;
}

interface AgentRunRequest {
  cwd: string;                     // working dir for file tools
  systemPrompt: string;            // fully composed by the caller (AGENTS.md etc.)
  prompt: string | PromptContent;  // text, or text + images
  tools: ToolSet;                  // builtin selection + custom Tool[]
  model: ModelRef;                 // { provider, id, thinking? }
  signal: AbortSignal;             // timeout and cancellation
  logDir?: string;                 // where the adapter writes its raw event log
  onEvent?: (e: AgentEvent) => void;
}

interface AgentRunResult {
  trajectory: Trajectory;          // steps + usage + model + stopReason + timestamps
  status: 'completed' | 'aborted' | 'error';
  error?: string;
}

interface LlmClient {
  complete(req: CompleteRequest): Promise<Completion>;   // text or JSON-schema-constrained
}

interface Tool<P> {
  name: string;
  description: string;
  parameters: TSchema;             // TypeBox, i.e. JSON Schema
  execute(params: P, ctx: ToolContext): Promise<ToolResult>;
}
```

- **`adapters/pi/`** implements both interfaces with
  `@earendil-works/pi-coding-agent` and `@earendil-works/pi-ai`:
  - `createAgentSession` with `SessionManager.inMemory(cwd)`,
    `SettingsManager.inMemory({compaction, retry})`, and a
    `DefaultResourceLoader` constructed with `noExtensions`, `noSkills`,
    `noPromptTemplates`, `noThemes`, `noContextFiles` and
    `systemPrompt` set to the caller's prompt. Nothing under `~/.pi` is
    read.
  - Custom tools are registered through one inline extension factory
    (`pi.registerTool`) that maps `Tool` to pi's tool shape; the same
    extension subscribes to `tool_call` / `tool_result` / `message_end`
    to build the `Trajectory` incrementally and to append raw events to
    `logDir/events.jsonl`.
  - `ModelRuntime.create({authPath, modelsPath})` points at a per-run
    generated `models.json` when `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`
    are set, otherwise `setRuntimeApiKey` from `Credentials`.
  - Timeout is `signal.abort()` → `session.abort()`; the adapter also kills
    any child processes it started.
  - `LlmClient` is `models.complete(model, context)` from pi-ai with a
    JSON-schema response check done on our side.
- **Trajectory** keeps today's step kinds (`thought`, `message`,
  `tool_call`, `tool_result`, `error`) and adds `usage {input, output,
  cacheRead, cacheWrite, costUsd}` per assistant message, `model`,
  `stopReason`, and real timestamps. The JSON file name and location
  (`iters/<id>/trajectory.json`) are unchanged so existing tooling keeps
  working.
- **`FakeRuntime`** (test double) replaces `ReplayRuntime`: a scripted list
  of `{ writeFiles, trajectory }` per call. No cassette recording.
- **Adding a runtime** is one directory under `adapters/` implementing the
  two interfaces plus a conformance test suite that every adapter runs
  (tool round-trip, abort, trajectory shape, usage present).

### 5.4 `@shop-gym/browser`

- `BrowserSession`: one Playwright context per episode, with
  `extraHTTPHeaders: {'x-shopgym-episode': id}` (see §5.6.4), viewport,
  video and trace options, and `storageState()` export for graders.
- `browserTools(session): Tool[]`: `navigate`, `back`, `click`, `type`,
  `select`, `press`, `hover`, `scroll`, `wait`, `snapshot` (aria snapshot
  with stable refs, the same approach Playwright MCP uses), `screenshot`
  (returns an image block), `evaluate` (gated by a flag; off for solvers),
  `finish(answer | infeasible)`.
- `probe(session, locatorExpr)` for graders and task validation.
- Replaces `pi-playwright`, Playwright MCP, and BrowserGym observation
  code. BrowserGym `bid` attributes are not reproduced; refs come from the
  aria snapshot.

### 5.5 `@shop-gym/harness`

A faithful port with the subprocess layer removed.

- Keep byte-for-byte: `plan.md` grammar, `selectNext`, `diff`, protocol
  violation strings, verifier dispatch semantics (FAIL rewrites to `[~]`,
  ERROR does not block), seed manifest and checks, workspace identity
  tuple on resume, quarantine of partial iterations, `run.json` shape and
  secret scrubbing, `reconstruct()`.
- Change: `AgentRuntime.run` replaces `run_iteration`; timeout is an
  `AbortSignal`; status comes from `AgentRunResult.status`, not exception
  types.
- Fix the recorded spec drift while porting: re-snapshot `plan.after.md`
  after a force-block, and make `reconstruct()` agree with
  block-and-continue.
- Drop: `native.log`, the `inspect` tool, `ReplayRuntime` record mode,
  `validate_model_grammar`, the `CLAUDE.md` symlink. A 100-line
  `shopgym trace <iter_dir>` subcommand renders `trajectory.json`.
- Tests: port the Python suites (loop signature, invariants, resume,
  verifiers, workspace, seed) against `FakeRuntime`.
- Port decisions (M2, 2026-09-30): all JSON the harness writes
  (`run.json`, `metadata.json`, `checks/*.json`, the seed manifest) uses
  camelCase keys; `VerifierContext` drops `runtime`; `config.agentsMd` is
  both written to `AGENTS.md` and passed as the runtime `systemPrompt`;
  the agent's `cwd` is the run dir and `logDir` is the iteration dir; no
  `trajectory.json` is written for `aborted` / `error` outcomes, so the raw
  `events.jsonl` stays in the quarantined dir; `config.onEvent(iterId,
  event)` forwards runtime events for CLI progress.

### 5.6 `@shop-gym/shop-backend` v2: the backend template

#### 5.6.1 One template, per-shop copy, agent-editable

Decision (2026-09-30): the backend is handled **like the frontend**. The
package is a complete, tested backend that works unmodified on any
dataset. Generation seeds a copy of it next to the storefront; with
`--gen-backend` the build agent may change and extend that copy. Without
the flag the copy is used as-is. Either way the shop ships and hosts its
own `backend/`.

What keeps an agent-modified backend gradable is the **sandbox
contract**: a small read-only subtree plus a contract test suite the
build loop runs as a verifier.

```
packages/shop-backend/
  src/
    data/        zod dataset schema (shared with arena), loader, pagination
    state/       ShopState store: fork/reset/snapshot, clock, id allocator
    schema/      per-domain SDL modules merged at startup
    domains/     catalog/ search/ content/ cart/ customer/ checkout/ order/
    sandbox/     READ-ONLY for agents: episode middleware, control API,
                 StateSnapshot schema + exporter, /health
    server.ts, cli.ts
  tests/
    contract/    READ-ONLY for agents: dataset loads, storefront operations
                 validate and resolve, control API, snapshot schema
    unit/        agent may add or change
  AGENTS.md      template rules (what may change, how to add a domain)
```

- **Agent-editable**: `src/domains/**`, `src/schema/**`, `src/state/**`
  (adding collections is fine, the snapshot exporter maps them),
  `tests/unit/**`, `package.json` dependencies.
- **Read-only** (enforced by the executor's owned-file table and by a
  `sandbox_contract` verifier that diffs those paths against the
  template): `src/data/schema.ts`, `src/sandbox/**`, `tests/contract/**`.
- **Dataset schema is fixed per generation.** The agent may add
  backend-owned seed data under `seed/*.json`, but may not change the
  `data/` schema, so data synthesis stays independent of backend
  generation.

Why a template instead of a core engine plus plugin API: it is one code
path with no loader, merge validation, or `ExtensionApi` to maintain, the
agent gets the full freedom of real code, and the storefront already
works this way. The cost, that generated bugs can break grading, is paid
by the contract suite and by `StateSnapshot` being the only thing graders
read.

#### 5.6.2 Domains and API surface
#### 5.6.2 Domains and API surface

Catalog, search, content, metafields, and cart keep their Storefront-API
shape. New, also Storefront-API shaped where Shopify has an equivalent:

| Domain | Queries | Mutations |
| --- | --- | --- |
| customer | `customer(customerAccessToken)` with `addresses`, `defaultAddress`, `orders`, `paymentMethods` (sandbox) | `customerCreate`, `customerAccessTokenCreate`, `customerAccessTokenDelete`, `customerUpdate`, `customerAddressCreate/Update/Delete`, `customerDefaultAddressUpdate`, `customerPaymentMethodCreate/Delete` (sandbox) |
| checkout | `cart.deliveryGroups`, `cart.cost` with real tax, shipping, discounts | `cartBuyerIdentityUpdate` (resolves the token to a customer), `cartDeliveryAddressesAdd`, `cartSelectedDeliveryOptionsUpdate`, `cartDiscountCodesUpdate` (applied for real), `checkoutComplete(cartId, payment)` (sandbox) |
| order | `order(id)`, `customer.orders(first, sortKey, query)` | `orderCancel`, `orderReturnRequest`, `orderReorder` (creates a cart) (sandbox) |

Sandbox-only operations carry a `@sandbox` directive in the SDL and live
in their own SDL module so the Shopify-compatible subset stays obvious.
`src/data/schema.ts` adds `customers.json`, `orders.json`, and
`commerce.json`, all optional so v1.0 datasets still load.
Rules such as tax rates, shipping zones and rates, free-shipping
threshold, return window, cancellation window, and discount definitions
come from `commerce.json`.

#### 5.6.3 State store

One `ShopState` document (`customers`, `sessions`, `addresses`,
`paymentMethods`, `carts`, `orders`, `inventory` deltas, `counters`) with:

- injectable `clock` and sequential id allocator, so every output is
  deterministic for a given action sequence;
- `fork(parentId)`, `reset(episodeId)`, `snapshot(episodeId)`;
- seed from `customers.json` and `orders.json` at startup;
- optional JSON persistence of the base branch only.

This replaces the bespoke `CartStore` and its hand-written snapshot
parser.

#### 5.6.4 Episode scoping

Parallel evaluation needs isolation without one storefront and backend
per episode. Proposal: every request may carry `x-shopgym-episode: <id>`.
The storefront SSR forwards the header on its backend calls; the browser
session sets it on every request. The backend keeps one state branch per
episode, created copy-on-write from the base branch on first use.
Requests without the header use the `default` branch. Control API:

```
POST /__shopgym/episodes/<id>/reset
GET  /__shopgym/episodes/<id>/state         # full ShopState branch, for graders
DELETE /__shopgym/episodes/<id>
GET  /health
```

Cart ids already isolate carts; this extends isolation to login, profile,
and orders.

#### 5.6.5 StateSnapshot and graders

`GET /__shopgym/episodes/<id>/state` returns a `StateSnapshot`: a
normalized view (`customer`, `addresses`, `paymentMethods`, `carts`,
`orders` with line items, totals, status, shipping address) defined by a
zod schema in `src/sandbox/`. Graders in `shop-guru` import that schema
from the pristine package and only ever read this shape, never raw store
internals, so an agent that adds a loyalty-points table or renames an
internal collection cannot break grading as long as the contract suite
passes.

#### 5.6.6 Compatibility

Existing `data/` directories host unchanged. The SDL for existing types is
unchanged, so the v1.0 react-vite template still renders.

### 5.7 `@shop-gym/shop-arena` v2

#### 5.7.1 Pipeline

Same five phases, run through the shared `core/pipeline`:

```
manual_merge  →  data_synth  →  data_validation  →  build  →  final_eval  →  publish
```

- `data_synth` gains `synth_customers`, `synth_orders`, and
  `synth_commerce` (tax, shipping, discounts, return policy parameters
  derived from the manual's policies). Personas get known credentials so
  tasks can start logged in.
- All LLM-backed steps call `LlmClient.complete` with a JSON schema;
  per-item caching semantics (one file per collection or product) are
  kept.
- `data_validation` = zod validation + hosting smoke (boot the pristine
  backend template on the dataset, run its contract suite).
- `build` = seed both templates into `runs/build/artifact/{storefront,
  backend}/` (from `git ls-files`, then `pnpm install`), start the
  shop's backend copy as a sidecar process, run the harness loop.
  Storefront verifiers: `typecheck`, `build`, `routes_200`,
  `data_in_use`, `nav_coverage`, `cart_conformance`, `visual_judge`.
  With `--gen-backend` the planner gets a `gen_backend` task (priority
  10, before `gen_theme`, since the storefront builds on the API) and
  may add more backend tasks; the executor's owned-file table grants
  backend paths to those tasks; the sidecar restarts whenever an
  iteration changed files under `backend/`; and four backend verifiers
  apply: `backend_typecheck`, `backend_test`, `sandbox_contract`
  (read-only paths unchanged, contract suite passes against the running
  sidecar), and `data_in_use` extended to validate every storefront
  GraphQL operation against the shop's actual schema.
- `final_eval` = visual sweep over the canonical pages plus a functional
  sweep: sign up, log in, add to cart, checkout, view order, request
  return, all driven by `@shop-gym/browser` with fixed scripts, no agent.
  This replaces the stubbed smoke driver.
- `publish` (new) copies the built storefront and backend out of
  `runs/build/artifact/` into `outputs/shops/<name>/{storefront,backend}`
  and writes `shop.json` (template versions, `genBackend` flag). `host`
  reads only the published layout and always runs the shop's own
  `backend/`.
- Build-loop cleanups folded into the port: one visual judge instead of
  `quality_judge` + `visual_judge` + a separate final sweep rubric (the
  final sweep reuses the same judge over more pages); `--only` and
  retries are owned by the harness instead of `_redo_N` plan edits and
  prompt-side counters; `clone_template` copies from `git ls-files` so
  local `.env` and `dist/` never leak into the seed; prompts are written
  for the single storefront template with no override shim; the
  `start_sidecar` preflight step is folded into `build`.
- Image generation keeps the two backends (placeholder, OpenAI) behind
  one `ImageBackend` interface with the content-hash cache.

#### 5.7.2 Template

One storefront template, the React Router 7 SSR app (`react-vite`),
extended with `account/*` (login, signup, profile, addresses, payment
methods, orders, order detail, return request) and a real `checkout`
flow. Hydrogen is removed from v1.1: its account routes speak Shopify's
hosted Customer Account API, which has no local equivalent, and the
engine would have to emulate OAuth to keep them working.

The template remains Storefront-API shaped on the wire so the build agent
can lean on its training data, and keeps a hand-written typed client
(`storefrontQuery`) rather than a vendor SDK.

#### 5.7.3 Explore

Port of today's explore pipeline on the new harness and browser tools:
HTTP prefetch, fixed planner tasks, per-task `parts/*.md` +
`caps.json` + evidence, deterministic capability merge, one `LlmClient`
call for the manual. Output contract (`manual.md`, `capabilities.json`,
`stats.json`, evidence) is unchanged, with `capabilities.json` extended
to record account and checkout features observed on the reference store.
Two additions: an `anonymization` verifier (deterministic scan of
`parts/*.md` for the store domain, brand tokens from prefetch, URLs,
emails) so the rules stop living only in the prompt, and a `--from`
switch on the shared pipeline replacing `--prefetch-only` /
`--synthesize-only`.

#### 5.7.4 `env_eval`

Dropped (decision 1, 2026-09-30). It is deleted with the rest of the
Python at M11 and its spec is marked superseded; nothing in v1.1 depends
on it.

### 5.8 `@shop-gym/shop-guru` v2

One task contract, one pipeline, no BrowserGym.

```
seed tasks (deterministic, from data/) ─┐
                                        ├→ validate → solve → grade → aggregate
crawl → explore (agent proposes tasks) ─┘
```

- **Task contract** (`core/schema/task.ts`):
  ```ts
  { id, shop, skill, goal, setup?: { login?: personaId, cart?: lineItems },
    eval: Check[], source: 'seed' | 'explore', evidence?: {...} }
  Check = string_match | url_match | locator_probe | state_check | llm_judge
  ```
  `state_check` compares the episode's backend state (via the control
  API) to an expectation, for example "an order exists with these two
  variants shipped to the default address". `llm_judge` is explicit and
  opt-in per task.
- **Seed tasks**: the six deterministic v1 generators ported as pure
  functions over the dataset, plus new generators for account, checkout,
  and order-history skills that read `customers.json` / `orders.json`.
- **Explore**: the v2 explorer prompt, run through `AgentRuntime` with
  browser tools; the agent proposes tasks and the pipeline (not the
  agent) verifies every `locator_probe` and records evidence.
- **Solve**: `AgentUnderTest` interface with one built-in implementation
  (pi runtime + browser tools, `evaluate` disabled). Each episode gets a
  fresh browser context and backend episode branch; `setup` runs through
  the control API before the agent starts.
- **Grade**: programmatic checks first; `llm_judge` through `LlmClient`
  with screenshots. Results and `aggregate.json` keep today's fields
  (`by_skill`, `by_shop`, counts) plus cost and token totals from the
  trajectory.
- **Removed**: AgentLab, BrowserGym, Ray, pickle episode reconstruction,
  `models.py` proxy shims, the v1 `url_contains` + judge format, two
  output trees.

### 5.9 `shopgym` CLI and hosting

One binary with subcommands mirroring the pipeline:

```
shopgym explore <url>
shopgym gen <manual_dir> --name <shop> [--gen-backend] [--from <step>]
shopgym host start|stop|list|restart <shop> [port]
shopgym guru build|explore|solve|eval <shop> [...]
shopgym trace <iter_dir>
shopgym doctor
```

`host` replaces `run-shop.sh` with a Node implementation: starts the
shop's own `backend/` on the dataset and the storefront, writes pid and
log files under `.run/`, polls `/health`.

### 5.10 Testing and CI

- Unit tests with `vitest` per package; adapter conformance suite in
  `agent`; harness parity suite ported from Python; backend contract
  suite reused as a build verifier.
- Live tests behind `SHOPGYM_LIVE=1` (pi adapter smoke, one gen step).
- CI: `pnpm install --frozen-lockfile`, Playwright Chromium, then
  `pnpm -r build && pnpm -r typecheck && pnpm -r test && pnpm lint && pnpm codegen:check`
  (the root `codegen:check` script forwards to `@shop-gym/shop-backend`).

## 6. Alternatives

| Area | Alternative | Why not |
| --- | --- | --- |
| Runtime seam | Depend on pi's `AgentSession` type directly everywhere | Locks every caller to pi; the user explicitly wants OpenAI / Claude SDK / OpenHands swappable. |
| Runtime seam | Keep subprocess runtimes behind the same interface | Possible later as an `adapters/cli` for tools without SDKs (OpenHands RPC); not the default. |
| Backend | Fixed core engine plus a typed per-shop extension plugin (`extend type` SDL + `ExtensionApi`) | Rejected 2026-09-30 as too complicated: plugin loader, merged-schema validation, and a second API to document, for less freedom than editing real code. The sandbox contract gives the same grading guarantee. |
| Backend | One fixed backend, never generated | Shop-specific business rules (loyalty, bundles, pickup, pre-orders) need code; realism suffers. Still available per shop by leaving `--gen-backend` off. |
| Backend | REST instead of GraphQL | Agents and templates already speak Storefront GraphQL; the SDL plus codegen is a cheap type-safety win. |
| Episode isolation | One backend + storefront process per episode | Simple but 2 processes and a Vite SSR boot per task; poor for RL throughput. |
| Episode isolation | Reset endpoint only, episodes run serially | Blocks parallel eval and shared hosted shops. |
| Template | Keep Hydrogen alongside react-vite | Doubles template maintenance; account routes need Shopify's hosted auth. |
| Task contract | Keep v1 `url_contains` tasks | No ground truth; every grade needs an LLM. |
| Pipeline | Keep the Python step registry with phases and fingerprints | Port cost about equal to the shared 300-line TS module; the v2 design was already specified. |
| Harness plan | Move `plan.md` to `plan.json` | Agents edit markdown reliably; existing prompts and tests assume it; no caller needs structured edits. |

## 7. Execution Table

Milestones are sized for one engineer plus coding agents. Columns B
(backend) and C (storefront) can run in parallel with A (agent + harness).

| # | Milestone | Scope | Depends on | Detail spec |
| --- | --- | --- | --- | --- |
| M0 | Workspace | pnpm workspace for all packages, `tsconfig.base`, biome, vitest, CI; `core` with task / result schemas, `pipeline`, `env`; zod dataset schema in `shop-backend/src/data/schema.ts` replacing `loader.ts` guards (parity tests against the two existing fixtures and `outputs/shops/*/data`) | - | this doc |
| M1 | Agent seam | `@shop-gym/agent` interfaces, `adapters/pi`, `FakeRuntime`, conformance suite, trajectory with usage | M0 | `agent/runtime.md` |
| M2 | Harness port | `@shop-gym/harness` with ported parity tests; fix recorded spec drift | M1 | update `harness/*.md` |
| M3 | Browser | `@shop-gym/browser` session, tools, probe, screenshot | M1 | `browser/tools.md` |
| M4 | Backend template v2 | `ShopState`, per-domain SDL, customer / checkout / order domains, `commerce.json`, control API, episode scoping, `StateSnapshot`, `src/sandbox` + `tests/contract` split, standalone install, template `AGENTS.md` | M0 | `shop_backend/stateful_commerce.md` |
| M5 | Backend generation | seeding the backend copy, `gen_backend` prompts and owned-file rules, sidecar restart on change, `backend_typecheck` / `backend_test` / `sandbox_contract` / extended `data_in_use` verifiers | M2, M4 | `shop_arena/backend_generation.md` |
| M6 | Storefront template v2 | account and checkout routes on the react-vite template, header forwarding, fixtures; remove Hydrogen | M4 | `shop_arena/storefront_template.md` |
| M7 | Arena gen port | pipeline steps on `core/pipeline`, data synth including customers / orders / commerce, build loop with consolidated verifiers, final eval functional sweep, `publish` step, `--gen-backend` flag wiring | M2, M3, M5, M6 | update `shop_arena/shop_gen.md` |
| M8 | Arena explore port | explore on harness + browser tools | M2, M3 | update `shop_arena/shop_explore.md` |
| M9 | Guru v2 | task contract, seed generators, explore, validate, solve, grade, aggregate | M3, M4, M6 | `shop_guru/benchmark_v2.md` |
| M10 | CLI + host | `shopgym` binary, Node host, `trace`, `doctor` | M7, M9 | implemented in `packages/cli` (`@shop-gym/cli`); host state under `.run/shops/<name>/` |
| M11 | Cutover | delete Python packages and `uv` files, migrate docs and README, mark old specs superseded, migrate `outputs/` layout notes | M10 | done 2026-10-01: `packages/shop_arena`, `packages/shop_guru`, the Python half of `packages/harness`, `pyproject.toml` and `scripts/run-shop.sh` deleted; CI is the pnpm chain of §5.10 plus Playwright Chromium; `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `.env.example` and `docs/specs/README.md` rewritten for the TS packages; superseded specs carry a dated note |

Each milestone lands as one or more PRs into `v1_1-dev`; `v1_1-dev`
merges to `main` after M11.

## 8. Decisions

Resolved with the user on 2026-09-30:

| # | Decision | Outcome |
| --- | --- | --- |
| 1 | `env_eval` | Dropped from v1.1; deleted at M11. |
| 2 | Hydrogen | Removed in v1.1. Already-generated Hydrogen shops stay hostable from their own artifact directories. |
| 3 | Backend generation model | Template approach (§5.6.1): one backend template, per-shop copy, agent edits it when `--gen-backend` is on. The core-plus-extension design is withdrawn. |
| 5 | pi SDK | Public `@earendil-works/pi-coding-agent` from the `earendil-works/pi` repository (SDK docs: `packages/coding-agent/docs/sdk.md`), pinned to the latest release at M1. Configured for the Shopify proxy: the adapter writes a per-run `models.json` whose providers use `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` as `baseUrl` and `PI_PROXY_API_KEY` as the key, from the project `.env`, matching today's env contract. |
| 6 | External agents under test | BrowserGym / AgentLab comparability is not required. v1.1 ships the built-in pi browser agent only. |
| 7 | Existing v1 guru outputs | Not migrated; v2 regenerates them. |

Still open, with the default the plan proceeds on:

4. **Episode isolation** (§5.6.4). Default: header-based episode branches
   inside one backend process. The alternative, one backend plus
   storefront process pair per episode, is simpler but costs two
   processes and a Vite SSR boot per task. The choice is internal to M4
   and M9 and can be revisited before M9 starts.

## 9. Appendix

### 9.1 pi SDK surfaces this plan relies on

Verified against the pi-mono `main` docs and source on 2026-09-30.

- `createAgentSession({ cwd, model, thinkingLevel, tools, customTools,
  settingsManager, sessionManager, resourceLoader, modelRuntime })`.
- `SessionManager.inMemory(cwd)`, `SettingsManager.inMemory(overrides)`.
- `DefaultResourceLoader({ cwd, agentDir, noExtensions, noSkills,
  noPromptTemplates, noThemes, noContextFiles, systemPrompt,
  appendSystemPrompt, extensionFactories, additionalSkillPaths,
  skillsOverride, agentsFilesOverride })`.
- Inline extension: `(pi) => { pi.registerTool({ name, label,
  description, parameters: Type.Object(...), execute(id, params, signal,
  onUpdate, ctx) }) ; pi.on('tool_call' | 'tool_result' | 'message_end'
  | 'agent_end', ...) }`.
- `session.prompt(text)`, `session.subscribe(handler)`, `session.abort()`,
  `session.messages`, `session.dispose()`; events `message_update`,
  `message_end`, `agent_end`, `agent_settled`.
- `ModelRuntime.create({ authPath, modelsPath })`,
  `modelRuntime.setRuntimeApiKey(provider, key)`; `models.json` supports
  `providers.<name>.baseUrl` and `$ENV` api keys. The adapter generates
  one such file per run under the run directory for the Shopify proxy
  (decision 5) and never touches `~/.pi`.
- pi-ai: `builtinModels().getModel(provider, id)`, `models.complete(model,
  context, { apiKey, signal })`; `AssistantMessage.usage.{input, output,
  cacheRead, cacheWrite, cost.total}`, `stopReason`.

### 9.2 Mapping from v1.0 modules to v1.1 homes

| v1.0 | v1.1 |
| --- | --- |
| `harness/runtimes/{pi,claude_code,replay}.py` | `agent/adapters/pi`, `agent/testing/fake-runtime.ts` |
| `harness/loop.py`, `workspace.py`, `seed.py`, `plan/`, `verifiers/`, `telemetry/` | `harness/src/*` (same module names) |
| `harness/tools/inspect_native_log.py` | `cli trace` |
| `shop_arena/util/_llm.py` | `agent` `LlmClient` |
| `shop_arena/gen/steps*` (registry, fingerprints) | `core/pipeline` |
| `shop_arena/gen/data_synth/schema.py` + `shop_backend/data/loader.ts` | `shop-backend/src/data/schema.ts` |
| `shop_arena/gen/templates/react-vite` | `shop-arena/templates/storefront` |
| `shop_arena/gen/templates/hydrogen` | removed |
| `shop_arena/gen/build/sidecar.py`, `scripts/run-shop.sh` | `shop-arena/gen/build/sidecar.ts` (shop backend copy as sidecar), `cli host` |
| `shop_arena/gen/build/redo.py` (`_redo_N`) | harness `--only` support |
| `shop_arena/gen/build/verifiers/{quality_judge,visual_judge}`, `final_eval/visual_sweep.py` | `shop-arena/gen/judge` (one judge) |
| `shop_arena/gen/data_synth/images/*` | `shop-arena/gen/images` (`ImageBackend`) |
| `shop_arena/explore/prefetch`, `capabilities`, `synthesize` | `shop-arena/explore/*` (same module names) |
| `shop_arena/doctor` | `cli doctor` |
| `shop_arena/env_eval` | removed (decision 1) |
| `shop_guru/generators/*` | `shop-guru/seed/*` |
| `shop_guru/{explorer,solver}.py`, `explore.py`, `solver.py`, `url_crawler.py` | `shop-guru/{crawl,explore,solve}` |
| `shop_guru/eval/*` (AgentLab, BrowserGym, Ray, judge, score, aggregate) | `shop-guru/{grade,aggregate}` + `browser` |
| `shop_guru/bgym_task/ax_crawler.py` | `shop-guru/crawl` on `browser` |
| `shop_backend/resolvers/cart.ts` `CartStore` | `shop-backend/state` |

### 9.3 Size estimate (hand-written TS, excluding tests and templates)

| Package | Estimate |
| --- | --- |
| core | 1k |
| agent | 1.5k |
| browser | 1.2k |
| harness | 3k |
| shop-backend | 8k (5.6k today + customer, checkout, order, state, sandbox) |
| shop-arena | 9k (explore 2k, data synth 3k, build + verifiers 3k, judge + final eval 1k) |
| shop-guru | 4k |
| cli | 0.8k |
| **Total** | **~28.5k** |
