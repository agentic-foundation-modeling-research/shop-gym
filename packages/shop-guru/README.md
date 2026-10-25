# @shop-gym/shop-guru

Benchmark pipeline for shopping agents over a SandboxShop: generate tasks,
discover more with an explorer agent, run any agent in isolated browser
episodes, grade, and aggregate. Tasks and results use the schemas in
`@shop-gym/core`; the dataset is read with `@shop-gym/shop-backend`'s loader.

## Layout

- `src/seed/` - deterministic generators, one per skill: `exact`,
  `substitute`, `browse`, `filter`, `shipping`, `returns`, `e2e`,
  `account`, `checkout`, `order_history`. Same dataset + same `seed`
  string = same tasks.
- `src/validate.ts` - reference checks (handles, personas, variant ids,
  gids in `state_check`), selector presence, goal dedupe, per-skill caps.
- `src/benchmarks.ts` - `benchmarks/<skill>.json` IO, merged by task id.
- `src/explore/` - explorer run (`prompts/explore.md`, `propose_task` and
  `probe` tools) and per-proposal verification on a fresh browser.
- `src/solve/` - `AgentUnderTest`, `RuntimeBrowserAgent` (pi by default),
  storefront-driven `setup`, episode runner with timeout and concurrency.
- `src/grade/` - matchers and `grade()` for `string_match`, `url_match`,
  `locator_probe`, `state_check`, `llm_judge` (`prompts/judge.md`).
- `src/aggregate.ts` - `aggregate.json`.
- `src/config.ts`, `src/pipeline.ts` - `GuruConfig` and the stage
  functions `build`, `explore`, `solve`, `evaluate`.
- `src/pi.ts` - `createPiBrowserAgent`, `createPiJudge` from
  `loadCredentials()`.

## Config

`configs/default.json` points at the backend fixture; copy it per shop.

```json
{
  "shop": "my_shop",
  "shopUrl": "http://127.0.0.1:3000",
  "backendUrl": "http://127.0.0.1:4000",
  "dataDir": "../../../outputs/shops/my_shop",
  "outDir": "../../../outputs/shop_guru",
  "model": { "provider": "anthropic", "id": "claude-sonnet-4-5" },
  "caps": { "exact": 5, "account": 3, "checkout": 3 }
}
```

Relative paths resolve against the config file. Skills missing from `caps`
are not generated. See `docs/specs/shop_guru/benchmark_v2.md` for every
field and the mapping from the v1 YAML.

## How to run

The storefront must be served over the backend with `x-shopgym-episode`
forwarding (the template in `packages/shop-arena/templates/storefront/`).
There is no CLI yet (M10); call the stage functions:

```ts
import { loadCredentials } from '@shop-gym/core';
import { build, createPiBrowserAgent, createPiJudge, evaluate, loadGuruConfig } from '@shop-gym/shop-guru';

const config = await loadGuruConfig('packages/shop-guru/configs/default.json');
const credentials = loadCredentials(process.cwd(), process.env);

await build(config);
const { aggregate, runDir } = await evaluate(config, {
  agent: createPiBrowserAgent(config, credentials),
  judge: createPiJudge(config, credentials),
});
console.log(runDir, aggregate.passRate);
```

Any agent can be measured by implementing `AgentUnderTest`:
`run({ task, baseUrl, session, tools, logDir, signal })` returns a
`Trajectory` and status; call `finish` (or set `session.finished`) to end
the episode with an answer or mark it infeasible.

## Outputs

```
<outDir>/<shop>/
  benchmarks/<skill>.json
  explore/<runId>/{trajectory.json, tasks.json, rejected.json, evidence/<taskId>.png}
  runs/<runId>/{results.json, aggregate.json, episodes/<taskId>/{trajectory.json, final.png, result.json}}
```

`aggregate.json` keeps v1's `by_skill` / `by_shop` keys; everything else
this package writes is camelCase.

## Tests

```bash
pnpm --filter @shop-gym/shop-guru test
SHOPGYM_SLOW_TESTS=1 pnpm --filter @shop-gym/shop-guru test   # boots the storefront template
SHOPGYM_SLOW_TESTS=1 SHOPGYM_LIVE=1 pnpm --filter @shop-gym/shop-guru test   # plus one pi episode
```

Fast tests use the backend fixture in-process, a node:http storefront
stand-in, and a real Chromium `BrowserSession`. The slow suite installs and
builds the storefront template in a temp dir; the live test reads
credentials from `.env` through `loadCredentials()` and takes
`SHOPGYM_LIVE_MODEL=<provider>/<id>`.
