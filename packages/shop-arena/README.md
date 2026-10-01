# @shop-gym/shop-arena

TypeScript ShopArena: storefront exploration (`src/explore/`), SandboxShop
generation (`src/gen/`), and the storefront template under `templates/`.
This package replaces the Python `packages/shop_arena` during the v1.1
migration; see `docs/specs/v1_1_typescript_redesign.md`.

Layout:

```
src/
  explore/      explore pipeline: prefetch, harness tasks, capability merge, manual synthesis
  gen/
    build/      build loop: template seeding, backend sidecar, owned-file rules, verifiers, prompts
    ...         data synth, final eval, publish (M7)
templates.ts  STOREFRONT_TEMPLATE_DIR: absolute path of templates/storefront
templates/
  storefront/   React Router 7 SSR storefront template seeded into every shop
                (catalog, cart, account/*, checkout; see its README.md)
```

The storefront template is standalone: it has its own `package.json` and
lockfile, is not a pnpm workspace member, and installs with
`pnpm install --ignore-workspace`. `SHOPGYM_SLOW_TESTS=1 pnpm test` runs
`src/templates.test.ts`, which builds the template in a temp dir and drives
the account and checkout flows against `packages/shop_backend/dist/cli.js`
(build the backend first).

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
`loadCredentials()` and are never written to disk. The `shopgym explore`
CLI arrives in M10.

## Gen

`generateShop(config, deps)` (also under the `gen` namespace export)
turns one or more Shop Manuals into a SandboxShop under
`outputs/shops/<name>/`. It runs four steps on the `@shop-gym/core`
pipeline runner; `GEN_STEPS` lists them in order:

| Step | Reads | Writes |
| --- | --- | --- |
| `manual_merge` | each manual dir's `manual.md`, `capabilities.json`, `stats.json` | `manual/` (`manual.md`, `capabilities.json`, `stats.json`, `parts/*.md`, `manifest.json`); one manual is copied, several are merged (deterministic capability rules, LLM tiebreak for the descriptor and tied layout enums, LLM prose merge per H2 section) |
| `data_synth` | `manual/` | `data/` (`store`, `products`, `collections`, `navigation`, `pages`, `policies`, `inventory`, `customers`, `orders`, `commerce` `.json` and `images/`), `identity.json`, `.shop_gen/stage_cache/` |
| `data_validation` | `data/` | `data_validation.json` (backend zod schema, referential integrity, hosting smoke on the pristine backend template: shop, products, collection, search, image, cart create / add / `checkoutComplete` as the first seeded customer) |
| `build` | `data/`, `manual/`, `data_validation.json` | `runs/build/` via `build.runBuildLoop` (seed staged in `.shop_gen/build_seed/`); a final status other than `completed` fails the step so the next run resumes it |

`data_synth` runs its sub-steps in order (`identity`, `store`, `pages`,
`policies`, `commerce`, `collections`, `skeletons`, `details` per
collection, `alt_text`, `images`, `navigation`, `customers`, then
assembly with deterministic ids, inventory, and orders). Every LLM call
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
The `shopgym gen` CLI arrives in M10.

## Build

`build.runBuildLoop(options)` (namespace export `build` from
`@shop-gym/shop-arena`) runs the verifier-gated build loop for one shop.
It seeds both templates into `<runDir>/artifact/`, starts the shop's own
backend copy as a sidecar, and drives `runPlanExecLoop` from
`@shop-gym/harness`:

| Piece | Module | Role |
| --- | --- | --- |
| seeding | `src/gen/build/seed.ts` | copies each template's `git ls-files` output into `artifact/{storefront,backend}/`, writes `template.json` (commit + content hash), runs `pnpm install --ignore-workspace` |
| sidecar | `src/gen/build/sidecar.ts` | `node --import tsx src/cli.ts artifact/data <port>` in `artifact/backend/`, `/health` wait, `restartIfChanged()` after every assistant turn (hash of `src/` + `package.json`), logs in `<runDir>/sidecar.log` |
| prompts | `src/gen/build/prompts/*.md` | `agents.md`, `planner.md`, `execute.md`; `{{backend_url}}` and `{{gen_backend_mode}}` are substituted, `{{verifier_feedback}}` is left for the harness |
| owned files | `src/gen/build/owned_files.ts` | glob table per task id; `gen_backend` / `backend_*` tasks own `backend/src/{schema,resolvers,state}/**` and co-located tests, nobody may touch `backend/src/data/schema.ts`, `backend/src/sandbox/**`, `backend/tests/contract/**` |
| verifiers | `src/gen/build/verifiers/` | `owned_files` (all tasks), `backend_typecheck`, `backend_test`, `sandbox_contract` (backend tasks), `data_in_use` (all tasks: every GraphQL document under `storefront/app` validated against the sidecar's introspected schema) |

```ts
import { build, STOREFRONT_TEMPLATE_DIR } from '@shop-gym/shop-arena';

const result = await build.runBuildLoop({
  runDir: 'outputs/shops/demo/runs/build',
  seedDir: 'outputs/shops/demo/seed', // data/ and manual/ become artifact/data, artifact/manual
  storefrontTemplateDir: STOREFRONT_TEMPLATE_DIR,
  backendTemplateDir: build.defaultBackendTemplateDir(),
  genBackend: true, // adds the gen_backend task and the backend verifiers
  runtime, // any AgentRuntime, e.g. the pi adapter
  model: { provider: 'anthropic', id: 'claude-sonnet-4-5' },
  tools: ['read', 'write', 'edit', 'bash'],
  maxIters: 12,
});
console.log(result.finalStatus, result.build.backendUrl);
```

A run records `build.json` (`genBackend`, `backendPort`, both template
fingerprints) so resuming with the same `runDir` renders identical
prompts, and writes `artifact/storefront/.env` pointing
`PUBLIC_STORE_DOMAIN` at the sidecar. The `sandbox_contract` suite runs
on the backend fixture (its helpers hardcode the fixture path); the
read-only drift check runs on the seeded copy. `SHOPGYM_SLOW_TESTS=1
pnpm test` additionally runs `src/gen/build/build_loop.test.ts` with
real `pnpm install`, a real `tsx` sidecar, and the real backend suites.
The storefront verifiers and the `--gen-backend` CLI flag arrive in M7;
see `docs/specs/shop_arena/backend_generation.md`.
