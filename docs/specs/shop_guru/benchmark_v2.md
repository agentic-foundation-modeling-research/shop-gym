# ShopGuru Benchmark v2 (`packages/shop-guru`)

Status: **Implemented** (v1.1 M9) - Version: **0.1**
Owners: ShopGuru

> The TypeScript benchmark pipeline: deterministic seed tasks plus
> agent-discovered tasks over a SandboxShop, solved by any `AgentUnderTest`
> in isolated browser episodes, graded by programmatic checks against the
> page and the backend's episode state, and rolled up into `aggregate.json`.

---

## Overview

v1 `shop_guru` (Python) generated six skills of tasks from dataset JSON,
explored storefronts with an MCP-driven Claude session that wrote task
files by hand, and evaluated agents through AgentLab / BrowserGym on Ray.
Its checks (`url_contains`, `program_evaluation` with JavaScript locators,
a free-form judge format) did not match the v1.1 task schema in
`@shop-gym/core`, and the stateful backend (customers, checkout, orders)
had no tasks at all.

This spec covers milestone M9 of `v1_1_typescript_redesign.md`:
`@shop-gym/shop-guru` replaces the Python package with four stages
(`build`, `explore`, `solve`, `eval`) as plain functions over a
zod-validated JSON config, the `AgentUnderTest` seam, episode isolation
through `BrowserSession` and the backend control API, and graders for
every `Check` kind in `core/schema/task.ts`.

## Terminology

- **Task**: `core` `taskSchema` object: `id`, `shop`, `skill`, `goal`,
  optional `setup` (`login` persona id, `cart` lines), `eval` checks,
  `source` (`seed` | `explore`), optional `evidence`.
- **Seed task**: produced by a pure generator from the dataset; same
  output for the same dataset and seed string.
- **Explore task**: proposed by an agent browsing the storefront, kept only
  after independent verification on a fresh browser.
- **Episode**: one task attempt: a backend episode branch (reset through
  `/__shopgym/episodes/<id>/reset`), one fresh `BrowserSession` sending
  `x-shopgym-episode`, the task's `setup` applied, then the agent.
- **AgentUnderTest**: `{ name, model, run(episode) }`; receives the task,
  the session, UI-only browser tools, a log dir, and an abort signal.
- **Check**: one of `string_match`, `url_match`, `locator_probe`,
  `state_check`, `llm_judge` (see Appendix A for grading semantics).
- **StateSnapshot**: the backend's grader-facing export of an episode
  (`customers`, `sessions`, `carts`, `orders`, `inventory`).

## Current Status

Implemented in `packages/shop-guru/src/`:

| Module | Responsibility |
| --- | --- |
| `seed/` | Ten generators: `exact`, `substitute`, `browse`, `filter`, `shipping`, `returns`, `e2e` (ported from v1, `e2e` now deterministic) and `account`, `checkout`, `order_history` (new, from `customers.json` / `orders.json`). Seeded RNG (`rng.ts`), shared filters, `generateSeedTasks(ctx, caps)`. |
| `validate.ts` | Schema parse, reference checks (product / collection / page / policy handles in URLs, persona ids, variant ids, variant and customer gids inside `state_check` values), empty-selector probes, goal dedupe, per-skill caps. Returns kept tasks and dropped `{taskId, reason}`. |
| `benchmarks.ts` | `benchmarks/<skill>.json` read / write, merged by id so seed and explore output coexist. |
| `explore/` | Explorer prompt (`prompts/explore.md`), `propose_task` + `probe` tools, verification of each proposal on a fresh session (`url_match` targets must answer 2xx, `locator_probe` selectors must match and satisfy `required`), evidence `{url, probes, screenshotPath}`. |
| `solve/` | `AgentUnderTest`, `RuntimeBrowserAgent` (any `AgentRuntime`; `PiRuntime` gives the reference `pi-browser` agent via `createPiBrowserAgent`), storefront-driven `setup` (`addToCartThroughStorefront`, `loginThroughStorefront`), `runEpisode` / `runEpisodes` with a concurrency pool, per-episode `trajectory.json`, `final.png`, `result.json`. |
| `grade/` | Pure matchers (deep equality, injective array subset, RFC 6901 pointers, URL rules, text rules), `grade()` running programmatic checks then `llm_judge` through `LlmClient` with the final screenshot. |
| `aggregate.ts` | `aggregate.json`: `total`, `passed`, `failed`, `errors`, `passRate`, `by_skill`, `by_shop`, `usage`. |
| `config.ts`, `pipeline.ts` | `GuruConfig` (zod) and the four stage functions. |
| `backend.ts` | Episode-scoped GraphQL and control API client. |

Removed, not ported: AgentLab, BrowserGym, Ray, pickle results, the
`models.py` proxy shims, v1 `url_contains` and the v1 judge format, the
dual `outputs/shop_guru` + `outputs/shop_guru_evals` trees, YAML config.

## Desired Status

- One task vocabulary (`@shop-gym/core`) shared by generators, explorer,
  graders, and future dashboards; every check gradable from the page or
  the backend snapshot without agent cooperation.
- Episodes isolated by construction: a reset episode branch, a fresh
  browser profile, and `setup` applied through the storefront so cookies
  and headers match a human shopper.
- The agent under test is a value, not a framework: the pi browser agent
  ships as the default, any other runtime or external agent implements
  `AgentUnderTest`.
- Stage functions are the whole API; M10 wires them to
  `shopgym guru build|explore|solve|eval`.

## Proposal

### Stages

```
build(config)                    -> seed + validate -> benchmarks/<skill>.json
explore(config, {runtime})       -> agent proposals -> verify -> validate -> merge into benchmarks/
solve(config, {agent, skills?})  -> runs/<runId>/episodes/<taskId>/, results.json (no grading)
evaluate(config, {agent, judge?})-> solve + grade + aggregate.json
```

Output layout under `<outDir>/<shop>/`:

```
benchmarks/<skill>.json
explore/<runId>/{trajectory.json, tasks.json, rejected.json, evidence/<taskId>.png, agent/}
runs/<runId>/{results.json, aggregate.json, episodes/<taskId>/{trajectory.json, final.png, result.json, agent/}}
```

### Config

`configs/default.json` (zod `guruConfigSchema`; paths resolve against the
config file):

| Field | Meaning | Default |
| --- | --- | --- |
| `shop` | identifier used in task ids and paths | required |
| `shopUrl` | storefront origin | required |
| `backendUrl` | sandbox backend origin | required |
| `dataDir` | SandboxShop dataset directory | required |
| `outDir` | root receiving `<shop>/...` | required |
| `model` | `{provider, id, thinking?}` for solver and explorer | required |
| `judgeModel` | model for `llm_judge` / `fuzzyMatch` | `model` |
| `seed` | generator seed string | `shopgym` |
| `caps` | tasks per skill; skills absent are not generated | ten-skill defaults |
| `concurrency` | episodes in flight | `1` |
| `episodeTimeoutMs` | per-episode budget | `600000` |
| `exploreMaxTasks` | proposals accepted per explore run | `10` |
| `headless` | browser mode | `true` |

Mapping from the v1 YAML (`configs/default.yaml`, one list of shops):

| v1 YAML | v2 JSON |
| --- | --- |
| `shops[].slug` | `shop` (one config per shop; a multi-shop run is a loop over configs) |
| `shops[].shop_url` | `shopUrl` |
| `shops[].data_dir` | `dataDir` |
| `shops[].name`, `country`, `currency`, `language`, `image_tag` | dropped; `store.json` in `dataDir` is the source of truth |
| CLI `--skills` | `SolveDeps.skills` / caps |
| CLI `--model`, `--judge-model` | `model`, `judgeModel` |
| `outputs/shop_guru/<slug>` + `outputs/shop_guru_evals/<slug>` | `outDir/<shop>/{benchmarks,explore,runs}` |

### Episode lifecycle

1. `POST /__shopgym/episodes/<id>/reset` (id = `<taskId>-<base36 time>`).
2. `BrowserSession.launch({episodeId, baseUrl})`; `evaluate` tool disabled.
3. `setup.cart` lines: `POST /cart` (`intent=add`) through the session's
   request context; `setup.login`: `POST /account/login` with the persona's
   email and password. Cart first, then login, so the storefront attaches
   the guest cart to the customer.
4. Navigate to `shopUrl`; hand the agent the task goal, the session, the
   browser tools (with `finish` wrapped to abort the run), and the signal.
5. Record `finalUrl`, `final.png`; map outcome: `finish` -> `completed` or
   `infeasible`; runtime `error` -> `error`; timeout or external abort ->
   `aborted`.
6. Grade while the page is still open; `passed` requires `completed`.
7. Close the browser; write `trajectory.json`, `result.json`.

### Decisions

- **`locator_probe.locator` is a Playwright selector** (CSS, `text=`,
  `role=`), matching `@shop-gym/browser` `probe`. The core schema comment
  and test were updated; v1 JavaScript locator expressions are not
  accepted.
- `aggregateSchema` keeps `by_skill` / `by_shop` from v1; every other key
  written by this package is camelCase.
- Skill names: v1's seven are kept; `account`, `checkout`, `order_history`
  are added. Task ids stay `<shop>-<skill>-<n>`; explore ids are
  `<shop>-explore-<n>`. Persona id is `String(customer.id)`.
- `substitute` and `browse` keep an `llm_judge` check: "a similar product"
  and "a product from this collection" are not expressible as one
  `state_check`. `filter` asks for a count so `string_match` grades it.
- `e2e` is a deterministic composition of two products from one collection
  with a quantity change; v1 asked an LLM to write it.
- Login reuses the storefront's `/account/login` instead of calling
  `customerAccessTokenCreate` from the pipeline: the storefront creates
  the token and owns the signed `__shop_gym_session` cookie, so a token
  minted elsewhere would be unused.
- Prompts live in `packages/shop-guru/prompts/*.md` (plain markdown,
  `{{name}}` placeholders only) because `tsc` does not copy `.md` files
  into `dist`; the same relative path resolves from `src/` and `dist/`.
- `grade` after `solve` is coupled inside the episode: `locator_probe`
  with `url: 'last'` needs the page as the agent left it.

## Alternative (optional)

- Grading from saved artifacts (HTML dump, storage state) would decouple
  solve and grade but loses live DOM probing and the backend snapshot
  timing; rejected for now.
- A `customerAccessToken` cookie injected directly into the browser
  context would avoid the storefront login route but has to track the
  storefront's cookie signing; rejected while the storefront owns login.

## Execution Table

| Item | Status |
| --- | --- |
| Package `@shop-gym/shop-guru` registered in workspace and lint | Done |
| Seed generators (10 skills) with deterministic RNG | Done |
| `validateTasks`, benchmark IO | Done |
| Explore stage with proposal verification and evidence | Done |
| `AgentUnderTest`, `RuntimeBrowserAgent`, pi default | Done |
| Episode runner with storefront `setup`, timeout, concurrency | Done |
| Graders for all five check kinds, judge with screenshot | Done |
| `aggregate.json` | Done |
| Config + stage functions, `configs/default.json` | Done |
| Tests: unit, in-process backend, real browser, storefront (slow), live pi | Done |
| CLI `shopgym guru build|explore|solve|eval` | M10 |
| Multi-shop orchestration, dashboards | Out of scope |

## Appendix

### A. Grading semantics

| Check | Passes when |
| --- | --- |
| `string_match` | answer present; `exactMatch` equals the trimmed answer; every `mustInclude` string appears (case-insensitive); then `fuzzyMatch`, if set, is confirmed by the judge |
| `url_match` | final URL resolved against `shopUrl`: `exact` (trailing slash ignored), `prefix`, or `contains` on the raw string |
| `locator_probe` | `url: 'last'` probes the current page, else navigates first; selector matches at least one element; `exactMatch` equals one element's trimmed text; `mustInclude` strings appear in the joined texts |
| `state_check` | value at the JSON pointer in `GET /__shopgym/episodes/<id>/state`: `equals` deep equality; `subset` partial match where arrays match injectively; `some` an array element matches as `subset` |
| `llm_judge` | judge returns `{passed: true}` given goal, rubric, answer, final URL, prior check results, and the final screenshot |

### B. What changes with the storefront

The storefront template (`packages/shop-arena/templates/storefront/`)
provides `/account/login`, `/cart` (`intent=add|update|remove|discount`),
`/checkout`, `/account/orders/:n`, and forwards `x-shopgym-episode`. If a
later template renames those routes or the cookie, only
`solve/setup.ts` (`LOGIN_PATH`, `CART_PATH`) and the seed generators' URL
targets (`/policies/...`, `/pages/...`, `/collections/...`) need to follow.
