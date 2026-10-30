# @shop-gym/shop-arena

TypeScript ShopArena: storefront exploration (`src/explore/`), SandboxShop
generation (`src/gen/`), and the storefront template under `templates/`.
The `shopgym explore` and `shopgym gen` commands in `packages/cli` drive
it; see `docs/specs/v1_1_typescript_redesign.md`.

Layout:

```
src/
  explore/      explore pipeline: prefetch, harness tasks, capability merge, manual synthesis
  gen/
    build/      build loop: template seeding, backend sidecar, owned-file rules, verifiers, prompts
    ...         manual_merge, data_synth, data_validation, final_eval, publish (see Gen)
templates.ts  STOREFRONT_TEMPLATE_DIR: absolute path of templates/storefront
templates/
  storefront/   React Router 7 SSR storefront template seeded into every shop
                (catalog, cart, account/*, checkout; see its README.md)
```

The storefront template is standalone: it has its own `package.json` and
lockfile, is not a pnpm workspace member, and installs with
`pnpm install --ignore-workspace`. Every `pnpm test` (and so CI on every
PR) runs `src/templates.browser.test.ts`: it builds the template in a temp
dir, serves it over the in-process backend on the template fixture, and
walks one shopper in Chromium through sign up, log out, a taken email on
the register page, "Forgot your password?", log in, add to cart,
every Discount code in the announcement bar (on a fake clock it does not
move by itself), an unknown and a valid Discount code, check out, the
thank-you page, the account order page and the address book (add, edit,
set the default, see it prefilled at checkout, delete), with the browser
steps that the final eval uses (`src/gen/build/verifiers/browser_steps.ts`).
It checks the pages and the episode's StateSnapshot. It also serves the
same build over backends with one Discount code and with none, for the
plain announcement and the missing bar. `SHOPGYM_SLOW_TESTS=1
pnpm test` also runs `src/templates.test.ts`, which drives the account and
checkout flows over HTTP against `packages/shop_backend/dist/cli.js`. Build
the backend first for both.

## Explore

`exploreStorefront(options)` (also exported from `@shop-gym/shop-arena/explore`)
turns one live storefront into an anonymized Shop Manual. It runs four
steps on the `@shop-gym/core` pipeline runner:

| Step | Reads | Writes |
| --- | --- | --- |
| `prefetch` | the storefront over HTTP | `seed/prefetch/` (robots, homepage, sitemap, Shopify JSON endpoints, policy and info pages, merged `products.json`, `prefetch.json`) |
| `explore` | `seed/prefetch/` | `run/` (harness workspace: `plan.md`, `iters/`, `artifact/{prefetch,parts,evidence}`, `run.json`) and `explore.json` |
| `merge` | `explore.json`, `run/plan.md`, `run/artifact/parts/*.caps.json` | `capabilities.json`, `stats.json`, `manifest.json` |
| `synthesize` | `capabilities.json`, `run/artifact/parts/*.md` | `manual.md` |

The explore step drives `runPlanExecLoop` from `@shop-gym/harness` with
the pi runtime, one headless `BrowserSession` per harness run, the
`browserTools` from `@shop-gym/browser`, and three run-dir-scoped file
tools (`read_file`, `write_file`, `list_dir`) that let the agent write
`plan.md`, `artifact/parts/*`, and `artifact/evidence/*`. The planner
emits a fixed canonical task list (homepage, header, cart, product,
collection, search, checkout, account, footer, info pages, floating
widgets); each executor iteration writes `parts/<task_id>.md` and
`parts/<task_id>.caps.json`. An `anonymization` verifier scans the parts
after every iteration for the store domain, brand tokens from the
prefetched homepage, absolute store URLs, and email addresses, and
reopens the task with line-level feedback on a hit.

```ts
import { loadCredentials } from '@shop-gym/core';
import { exploreStorefront } from '@shop-gym/shop-arena/explore';

const result = await exploreStorefront({
  url: 'https://example-shop.com',
  credentials: loadCredentials(process.cwd(), process.env),
  model: 'anthropic/claude-opus-4-7', // default
  maxIters: 20, // default
  log: console.log,
});
console.log(result.manualPath, result.finalStatus);
```

Options: `outDir` (defaults to `outputs/shop_manuals/<domain>/<run_id>/`),
`model`, `maxIters`, `timeoutMs`, `rateLimitMs`, `from` (force a step and
its dependents: `prefetch` | `explore` | `merge` | `synthesize`),
`forceResume` (resume a harness run that ended in a refused status),
`runtime` / `llm` (inject an `AgentRuntime` / `LlmClient`, used by tests),
`onEvent`, `log`, `signal`.

Calling again with the same `outDir` skips complete steps and resumes
an unfinished harness run; the pipeline never deletes `run/`, so
`from: 'explore'` continues the same exploration with a fresh iteration
budget. Prompts live in `src/explore/prompts/*.md` and are copied into
`dist/` by the build; `{{CAPABILITIES_SCHEMA}}` in `agents.md` is
rendered from the zod schema at run time. Credentials come from
`loadCredentials()` and are never written to disk. `shopgym explore <url>`
wraps this function.

## Gen

`generateShop(config, deps)` (also under the `gen` namespace export)
turns one or more Shop Manuals into a SandboxShop under
`outputs/shops/<name>/`. It runs six steps on the `@shop-gym/core`
pipeline runner; `GEN_STEPS` lists them in order:

| Step | Reads | Writes |
| --- | --- | --- |
| `manual_merge` | each manual dir's `manual.md`, `capabilities.json`, `stats.json`; the checked-in Standard sub-manual `src/gen/manual_merge/standard_sub_manual.md` | `manual/` (`manual.md`, `capabilities.json`, `stats.json`, `parts/*.md`, `manifest.json`); one manual is copied, several are merged (deterministic capability rules, LLM tiebreak for the descriptor and tied layout enums, LLM prose merge per H2 section); `parts/` holds the six Sub-manuals cut from `manual.md` and the shop's copy of the Standard sub-manual as `parts/standard.md`. Fusion: for each observed `## Account` or `## Checkout` section in `manual.md`, one LLM call fuses the notes into the copy. Observed labels and layout win. Unsupported behavior and the labels that the browser steps check keep the standard text. With no observed notes, the copy is unchanged and there is no LLM call |
| `data_synth` | `manual/` | `data/` (`store`, `products`, `collections`, `navigation`, `pages`, `policies`, `inventory`, `customers`, `orders`, `commerce`, `reviews` `.json` and `images/`), `identity.json`, `.shop_gen/stage_cache/` |
| `data_validation` | `data/` | `data_validation.json` (backend zod schema, referential integrity, including the product and variant of each Review; valid Discount codes, seeded order totals and discounts that follow the backend pricing rules, hosting smoke on the pristine backend template: shop, products, collection, search, image, cart create / add / `checkoutComplete` as the first seeded customer) |
| `build` | `data/`, `manual/`, `data_validation.json` | `runs/build/` via `build.runBuildLoop` (seed staged in `.shop_gen/build_seed/`); a final status other than `completed` fails the step so the next run resumes it |
| `final_eval` | `runs/build/run.json`, `runs/build/build.json` | `final_eval/` via `finalEval.runFinalEval` against the build artifacts booted on the recorded backend port (sidecar logs in `final_eval/{backend,storefront}.log`); advisory, never fails the step |
| `publish` | `runs/build/run.json`, `runs/build/build.json` | `storefront/`, `backend/`, `shop.json` via `publish.publishShop` |

`data_synth` runs its sub-steps in order (`identity`, `store`, `pages`,
`policies`, `commerce`, `collections`, `skeletons`, `details` per
collection, `alt_text`, `images`, `navigation`, `customers`, `reviews`,
then assembly with deterministic ids, inventory, and orders). `commerce`
also makes three to five Discount codes, at least one of each kind and
one percent or fixed code with no minimum, and four seeded orders use
one. `reviews` plans every Review by code from a fixed seed. 15% of
the products get no Reviews and each other product gets one to eight.
The ratings average 4.3. Each Review gets a reviewer (first name and
last initial), a date before the Episode clock starts, the variant
bought, a Verified Buyer flag and a helpful count. The LLM writes only
the title and text. It gets the product facts and the rating, in
batches of whole products with at most 20 Reviews. `navigation`
reads the manual's `parts/navigation.md` so the footer mirrors the manual's
footer link list and the in-loop judges agree on it. Every LLM call
asks for one JSON value against a zod-derived JSON Schema and retries
once with the validation error. Prompts are plain Markdown under
`src/gen/data_synth/prompts/` with `{{name}}` placeholders, and every
prompt carries the fake-brand allowlist from
`src/gen/brands/fake_brands.json`; vendors must come from it and titles
and descriptions may not mention it.

```ts
import { PiLlmClient, PiRuntime } from '@shop-gym/agent';
import { loadCredentials } from '@shop-gym/core';
import { generateShop } from '@shop-gym/shop-arena';

const credentials = loadCredentials(process.cwd(), process.env);
const result = await generateShop(
  {
    name: 'demo',
    manualDirs: ['outputs/shop_manuals/seed-a', 'outputs/shop_manuals/seed-b'],
    model: 'anthropic/claude-opus-4-7',
    imageBackend: 'placeholder', // or 'openai' (OPENAI_API_KEY / OPENAI_BASE_URL)
    catalog: { collections: 10, productsPerCollection: 20, imagesPerProduct: 2 },
    genBackend: false,
    maxIters: 30,
    from: undefined, // e.g. 'data_synth' forces that step and everything after it
  },
  { llm: new PiLlmClient({ credentials }), runtime: new PiRuntime({ credentials }), credentials },
);
console.log(result.dataDir, result.reports);
```

Cache and resume: a step is complete when `<shopDir>/.pipeline/<step>.json`
records the current fingerprint of its inputs and all of its outputs
exist. Changing an input (or passing `from`) removes that step's declared
outputs before it reruns, which for `data_synth` includes
`.shop_gen/stage_cache/` and `identity.json`; a step that never
completed keeps them, so an interrupted `data_synth` resumes at the
first missing draft (`details/<collection>.json` and image files are
per item). `.shop_gen/image_cache/` (OpenAI responses keyed by prompt
hash) is not a step output and survives reruns. `SHOPGYM_LIVE=1 pnpm
test` runs `src/gen/data_synth/data_synth.live.test.ts` against a real
model (`SHOPGYM_LIVE_MODEL=<provider>/<id>` overrides the default).
`shopgym gen <manual_dir>... --name <name>` wraps this function.

## Build

`build.runBuildLoop(options)` (namespace export `build` from
`@shop-gym/shop-arena`) runs the verifier-gated build loop for one shop.
It seeds both templates into `<runDir>/artifact/`, starts the shop's own
backend copy as a sidecar, and drives `runPlanExecLoop` from
`@shop-gym/harness`:

| Piece | Module | Role |
| --- | --- | --- |
| seeding | `src/gen/build/seed.ts` | copies each template's `git ls-files` output into `artifact/{storefront,backend}/`, writes `template.json` (commit, a `dirty` flag for uncommitted template edits, content hash), runs `pnpm install --ignore-workspace` |
| sidecar | `src/gen/build/sidecar.ts` | `node --import tsx src/cli.ts artifact/data <port>` in `artifact/backend/`, `/health` wait, `ensureCurrent()` before every `run_command`, `screenshot_page` and verifier that talks to it (restarts when the hash of `src/` + `package.json` moved, launches again after a failed launch), logs in `<runDir>/sidecar.log` |
| prompts | `src/gen/build/prompts/*.md` | `agents.md`, `planner.md`, `execute.md`; `{{backend_url}}` and `{{gen_backend_mode}}` are substituted, `{{verifier_feedback}}` is left for the harness |
| agent tools | `src/gen/build/agent_tools.ts` | added to the caller's `tools`: `run_command` (a shell line via `sh -c` inside the run dir, exit code plus head-and-tail of the output; `runCommand` kills the line's whole process group when it exits or times out; it and both sidecars pass only `commandEnv()`, the toolchain, locale, proxy and CA variables, so no API key or token in your shell reaches the agent) and `screenshot_page` (rebuilds the storefront if needed and returns the judge's desktop and mobile captures of one route) |
| checkpoints | `src/gen/build/checkpoints.ts` | bare git repo `<runDir>/checkpoints.git` with work tree `artifact/` (seed roots, `node_modules` and build output untracked); commits after seeding and after each kept iteration, rolls an abandoned iteration (timeout, unparseable plan, protocol violation, runtime error) back through the harness `onIterationEnd` hook |
| owned files | `src/gen/build/owned_files.ts` | `gen_backend` / `backend_*` tasks own `backend/` (only with `genBackend`; otherwise it is protected), every other task owns `storefront/`; nobody may touch `backend/src/data/schema.ts`, `backend/src/sandbox/**`, `backend/tests/contract/**`, either `template.json`, `storefront/.env`, or anything outside the two copies |
| verifiers | `src/gen/build/verifiers/` | `owned_files` (all tasks: the paths changed since the last checkpoint), `backend_typecheck`, `backend_test`, `sandbox_contract` (backend tasks), `data_in_use` (all tasks: every GraphQL document under `storefront/app` validated against the sidecar's introspected schema) |

```ts
import { build, STOREFRONT_TEMPLATE_DIR } from '@shop-gym/shop-arena';
import { fileTools } from '@shop-gym/shop-arena/explore';

const result = await build.runBuildLoop({
  runDir: 'outputs/shops/demo/runs/build',
  seedDir: 'outputs/shops/demo/seed', // data/ and manual/ become artifact/data, artifact/manual
  storefrontTemplateDir: STOREFRONT_TEMPLATE_DIR,
  backendTemplateDir: build.defaultBackendTemplateDir(),
  genBackend: true, // adds the gen_backend task and the backend verifiers
  runtime, // any AgentRuntime, e.g. the pi adapter
  model: { provider: 'anthropic', id: 'claude-sonnet-4-5' },
  tools: fileTools(), // read_file / write_file / list_dir; run_command and screenshot_page are added
  maxIters: 12,
});
console.log(result.finalStatus, result.build.backendUrl);
```

A run records `build.json` (`genBackend`, `backendPort`, both template
fingerprints) so resuming with the same `runDir` renders identical
prompts; a `runDir` whose seeding failed before `build.json` was written
is removed and seeded again. The run also writes
`artifact/storefront/.env` pointing `PUBLIC_STORE_DOMAIN` at the
sidecar. The `sandbox_contract` suite runs
on the backend fixture (its helpers hardcode the fixture path); the
read-only drift check runs on the seeded copy. `SHOPGYM_SLOW_TESTS=1
pnpm test` additionally runs `src/gen/build/build_loop.test.ts` with
real `pnpm install`, a real `tsx` sidecar, and the real backend suites.
`shopgym gen --gen-backend` turns `genBackend` on; see
`docs/specs/shop_arena/backend_generation.md`.

### Verifiers

`build.buildVerifiers({ genBackend, sidecar, ownedFiles, storefront? })`
returns the ordered verifier list. Without `storefront` it is the M5 set
above. With `storefront: { sidecar, dataDir, manualDir?, judge? }` (a
`build.StorefrontSidecar` plus the shop data directory, optionally the
manual directory and `{ llm, model }` for the judge) the order becomes
`owned_files`, `typecheck`, `build`, `routes_200`, the backend verifiers
(backend tasks), `data_in_use`, `nav_coverage`, `cart_conformance`,
`account_flow`, `discount_flow`, `visual_judge`:

| Verifier | Applies to | Checks |
| --- | --- | --- |
| `typecheck`, `build` | storefront tasks | `pnpm typecheck` in `artifact/storefront`; `build` asks the storefront sidecar for its `pnpm build`, so the HTTP verifiers that follow serve that build |
| `routes_200` | storefront tasks | static routes and the routes of every page bucket return 200, whatever the task; `/account*` redirect to `/account/login` logged out and return 200 after logging in as the first seeded customer; `/checkout` returns 200 with a line in the cart; internal links from rendered pages resolve. Failures list status, redirect target and a body excerpt |
| `nav_coverage` | `gen_navigation`, `gen_theme`, `visual_fix` | every `navigation.json` target returns 200 and is linked from the rendered header or footer |
| `cart_conformance` | `gen_cart_search`, `gen_product`, `gen_checkout`, `visual_fix` | add, update quantity, cart page totals equal the backend cart cost, remove, guest checkout, confirmation page shows the order |
| `account_flow` | `gen_account`, `visual_fix` | in one `BrowserSession` episode with the browser steps of the Final eval: sign up, log out, "Forgot your password?" shows the sent message, log in, add an address, edit it; stops at the first failed step and names it |
| `discount_flow` | `gen_checkout`, `visual_fix` | in one `BrowserSession` episode: add the first sampled product, apply the Discount code from the Dataset that `readApplicableDiscountCode` picks (the checkout "Total" changes; skipped when no code surely applies), then an unknown code shows "Enter a valid discount code" and the "Total" stays |
| `visual_judge` | every page task (`gen_theme` has no page) | desktop and mobile screenshots per route through `BrowserSession`, with a product added to the cart first for `cart_search` and `checkout` routes and the first seeded customer logged in before `/account` (`gen_account` gets the `account` bucket, `gen_checkout` the `checkout` bucket with `/checkout`); one `LlmClient` call per page with the rubric in `src/gen/build/verifiers/prompts/visual_judge.md`; failing pages' screenshots are returned as `images` so the next executor prompt carries them; three failures per task, then advisory (`<runDir>/checks/visual_judge_budget.json`) |

`runBuildLoop` always passes `storefront` (its `judge` option supplies
the visual judge; `generateShop` sets it to the synthesis model) and
`storefrontLaunch` (the serve step) and `commandRunner` (the build) are
the matching test seams. `build.StorefrontSidecar` mirrors the backend
sidecar for `artifact/storefront` and builds each version of the copy
once: `build()` (the `build` verifier) runs `pnpm build` alone, and
`ensureCurrent()`, which every HTTP verifier calls first, builds when
the storefront's source hash changed, then starts `node server.mjs` in
production mode with `PUBLIC_STORE_DOMAIN` pointed at the backend
sidecar and waits for `/health`. Both log to `<runDir>/storefront.log`.
A failed build is kept for its source hash and reported again, without
a new build, until the copy changes. A run with no storefront task never
builds it. `SHOPGYM_SLOW_TESTS=1` also runs
`src/gen/build/verifiers/storefront_slow.test.ts` (real template, real
build); `SHOPGYM_LIVE=1` sends one real judge call from
`visual_judge.test.ts`.

### Final eval

`finalEval.runFinalEval({ dataDir, manualDir?, backendUrl, storefrontUrl,
llm, model, outDir, log?, signal? })` evaluates an already-running shop;
the `final_eval` pipeline step boots the build artifacts and calls it
with `outDir = <shopDir>/final_eval`.
The visual sweep screenshots fourteen canonical pages (home, a collection,
a product, search, cart, checkout, the thank-you page of a guest order,
account login, account register, account profile, the order list, an order
detail, the address book, a policy page) at both viewports and judges each
with the same rubric as `visual_judge`; the functional sweep is a fixed
browser script: sign up, log out, "Forgot your password?", log in, add an
address, edit it, add to cart,
apply a Discount code, checkout, view order, and
`requestReturn`
recorded as `skipped: not supported by backend`. The sweep's code is a
Dataset code with no minimum subtotal: a percent or fixed-amount code
first, else a free-shipping code.
Pages and steps the dataset cannot set up (no product, no seeded customer,
no order, no such code) are recorded as `skipped` with a reason. Output under `outDir`:
`report.json` (counts, `visual.pages[]`, `functional.steps[]`),
`summary.md`, `pages/<name>.json`, `screenshots/<name>__<viewport>.png`.
The result carries `passed`, `failed`, `skipped`, `reportPath` and the
report.

### Publish

`publish.publishShop({ runDir, shopDir })` (the `publish` pipeline step
calls it with the shop directory itself) copies
`<runDir>/artifact/storefront` and `.../backend` into
`<shopDir>/storefront` and `<shopDir>/backend`, skipping `node_modules`,
`dist`, `build`, `.react-router`, `.vite`, `.cache`, `*.log` and the
storefront `.env` the build loop wrote for the sidecar (the host step
passes `PUBLIC_STORE_DOMAIN`, `PORT` and `SESSION_SECRET` through the
environment). Nothing is copied from `artifact/data`; the published
backend serves its own `data/`. It writes `<shopDir>/shop.json`:

```json
{
  "name": "<basename of shopDir>",
  "templates": { "storefront": { "name": "storefront", "commit": "...", "dirty": false, "contentHash": "...", "files": {}, "seededAt": "..." }, "backend": { "...": "..." } },
  "genBackend": true,
  "publishedAt": "2026-09-30T00:00:00.000Z",
  "finalStatus": "completed"
}
```

Calling it again replaces both component directories and rewrites the
manifest. `publish.readShopManifest(shopDir)` parses and validates it;
`dirty` may be absent in manifests written before the flag existed.
