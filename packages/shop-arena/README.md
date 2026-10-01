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
    build/      build loop: template seeding, backend sidecar, verifiers, prompts
    ...         data synth, final eval, publish (M7)
templates/
  storefront/   React Router 7 SSR storefront template seeded into every shop
```

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
