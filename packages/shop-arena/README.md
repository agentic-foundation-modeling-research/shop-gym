# @shop-gym/shop-arena

TypeScript ShopArena: storefront exploration (`src/explore/`), SandboxShop
generation (`src/gen/`), and the storefront template under `templates/`.
The `shopgym explore` and `shopgym gen` commands in `packages/cli` drive
it; see `docs/specs/v1_1_typescript_redesign.md`.

Layout:

```
src/
  explore/      explore pipeline: prefetch, harness tasks, capability merge, manual synthesis, Site state graph
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
move by itself), an unknown and a valid Discount code, `/cart.js` with
that code (and the empty cart from another episode), check out, the
thank-you page, the account order page and the address book (add, edit,
set the default, see it prefilled at checkout, delete), with the browser
steps that the final eval uses (`src/gen/build/verifiers/browser_steps.ts`).
It checks the pages and the episode's StateSnapshot. It also serves the
same build over backends with one Discount code and with none, for the
plain announcement and the missing bar. `SHOPGYM_SLOW_TESTS=1
pnpm test` also runs `src/templates.test.ts`, which drives the account,
checkout and `/cart.js` flows over HTTP against
`packages/shop_backend/dist/cli.js`. Build the backend first for both.

## Explore

`exploreStorefront(options)` (also exported from `@shop-gym/shop-arena/explore`)
turns one live storefront into an anonymized Shop Manual. It runs five
steps on the `@shop-gym/core` pipeline runner:

| Step | Reads | Writes |
| --- | --- | --- |
| `prefetch` | the storefront over HTTP | `seed/prefetch/` (robots, homepage, sitemap, `prefetch.json`; on a Shopify shop also the Shopify JSON endpoints, policy and info pages, merged `products.json`) |
| `explore` | `seed/prefetch/` | `run/` (harness workspace: `plan.md`, `iters/`, `artifact/{prefetch,parts,evidence}`, `run.json`) and `explore.json` |
| `merge` | `explore.json`, `run/plan.md`, `run/artifact/parts/*.caps.json`; on a generic site also `run/artifact/parts/*.product-<key>.json` | `capabilities.json`, `stats.json`, `manifest.json` |
| `synthesize` | `capabilities.json`, `stats.json`, `brand_terms.json`, `seed/prefetch/`, `run/artifact/parts/*.md` | `manual.md`, only when the final Anonymization scan is clean |
| `graph` | `capabilities.json`, `manifest.json` (only to run again after each merge), `brand_terms.json`, `seed/prefetch/`, `run/plan.md`, `run/artifact/parts/*.md`, `run/iters/*/` (trajectory, metadata and start state of each Iteration) | `site_graph.json`, only when the reply passes the graph checks and the final Anonymization scan is clean |

The `graph` step writes the Site state graph (`src/explore/graph.ts`,
prompt `prompts/site_graph.md`). A finished part is the
`run/artifact/parts/<task_id>.md` of a Plan task that `run/plan.md`
marks done. The prompt gets the closed lists of `@shop-gym/core` and the
merged Capabilities. It gets each finished part with no Styling lines,
under the Plan task id. After each part come the browser actions of each
executor Iteration that selected its Plan task, in run order
(`src/explore/trajectory-digest.ts`). A line names the action and its
element, and the URL path after the action. The element is its role and
name from the latest snapshot that showed its ref. Each query value is
`{value}`. The prompt has no refs, hosts, query values, typed text or
selected values. A Plan task with no Iteration, for example one whose
part was written outside the harness, has only its part. The
trajectories are not step inputs, because the merge after each explore
step makes the graph stale. The completion must be one JSON object, bare
or in one fenced block. The object must pass `parseSiteGraph`, and the
`source` of each transition must name a finished part. When a check
fails, the step logs the problems and makes one repair completion: the
graph prompt, then `prompts/site_graph_repair.md` with the reply and its
problems. If the repair reply also fails a check, the step fails with
`SiteGraphReplyError` or `SiteGraphValidationError` and writes no file.
A leak in the Anonymization scan gets no repair. `manifest.json` is an
input because merge writes it again on each run, so `from: 'merge'`
writes the graph again. `from: 'graph'` writes the graph from the files
on disk with no site traffic. It does not write the manifest again. On a
manual from before the graph step, use `from: 'merge'` to add
`site_graph` to the manifest `paths`.

`parseSiteGraph` applies the closed schema and these graph rules. The
graph prompt states the same rules.

- A URL pattern is a path that starts with one `/` and has no `://`. It
  has snake_case `{name}` placeholders, and each query value is a
  placeholder.
- No two page states have one URL pattern. Placeholder names do not
  count, so `/products/{id}` and `/products/{handle}` are one pattern.
- No two page states of one page type have one path, the part of the
  pattern before `?`. So a filter or a sort query does not make a
  second state.
- An overlay opens on one or more page states.
- Each state is the `from` or `to` of a transition.
- `params` and `needs` have no repeated items.
- Each effect has a rule for its two ends. `navigate` ends on a page.
  `open_overlay` goes from a host page to the overlay. `swap_overlay`
  goes from one overlay to a different overlay. `close_overlay` goes
  from the overlay to one of its host pages. `update_in_place` has the
  same `from` and `to`.
- No two transitions have the same `from`, `action` and `to`.

The prompt adds rules that no check can apply, for example that the
header and footer controls get one transition from `home`. See
`prompts/site_graph.md`.

Prefetch decides the platform before it fetches the rest. First it
fetches `robots.txt`, the homepage, `sitemap.xml` and one `/products.json`
page as the probe. It skips `sitemap.xml` when robots.txt forbids it. It
keeps a sitemap index as fetched and does not open the child sitemaps. It
cuts a sitemap at 1 MiB.

The platform is `shopify` when the homepage has a Shopify marker
(`cdn.shopify.com`, `myshopify.com`, `Shopify.theme`, `shopify-section`)
or the probe returns a product list. Then prefetch fetches the other
product pages, the Shopify JSON endpoints, and the policy and info pages.
Otherwise the platform is `generic`, and prefetch fetches nothing more.

The robots gate, the homepage status gate, the Cloudflare markers and the
rate limit apply on both paths. `prefetch.json` and `manifest.json` record
`platform`. On the generic path the planner uses `prompts/planner_generic.md`
in place of `prompts/planner.md`. That prompt tells the planner to pick
same-origin start URLs from the homepage links and the sitemap.

On the generic path the executors use `prompts/execute_generic.md` in place
of `prompts/execute.md`, and they get one more tool,
`record_product_observation`. The prompt tells each executor to call it for
each product page that it opens, while the page is open. The executor gives
only the price, the currency, `has_variants` and `variant_axes` (schema in
`src/explore/observations.ts`, shown in `AGENTS.md`), with the axes named as
short generic nouns. The tool checks the facts against the schema, takes
the page key from the open page, and writes the fragment
`parts/<task_id>.product-<key>.json`. The key is the first 12 hex digits of
the SHA-256 of the page URL without its query and fragment, and the URL is
the `<link rel="canonical">` target when the page has one. So the key tells
product pages apart without naming them, and two paths to one product page
give one key. A `product_observations` verifier fails an executor iteration
whose fragments do not match the schema.

`stats.json` records its `source` and `sample_size`. On a Shopify shop
`computeStats` reads the prefetched catalog: `source` is `catalog_endpoint`
and `sample_size` is the number of products read. On a generic site
`computeObservedStats` reads the fragments: `source` is `observed_sample`,
`sample_size` is the number of distinct product pages, and the price and
variant stats come from one fragment for each page. When more than one task
recorded the same page, the first fragment in filename order counts. The
prices use the most frequent currency, and the observed axes are sorted. The
product and collection totals and the products per collection stay 0.

With a `focus` (for example `"Video Games"`), the explore step adds
`prompts/planner_focus.md` after the planner prompt of either platform,
with `{{FOCUS}}` replaced by the focus text. That hint tells the planner
to pick start URLs, product pages and search queries in the focus, to
keep every canonical task, and to write the focus into the task briefs,
which is how the executors get it. Navigation outside the focus is not
blocked. With no focus the planner prompt is unchanged. `manifest.json`
records `focus`, or `null`. The explore step writes the focus to
`focus.json` before the harness runs. A later call on that `outDir` with
another focus fails, because a resumed harness run keeps the plan of its
first planner.

The explore step drives `runPlanExecLoop` from `@shop-gym/harness` with
the pi runtime, a new headless `BrowserSession` for every iteration
(`src/explore/browser.ts`; it opens the homepage, reads `/cart.js` when the
shop serves it, and writes `run/iters/<id>/start_state.json`), the
`browserTools` from `@shop-gym/browser`, and three run-dir-scoped file
tools (`read_file`, `write_file`, `list_dir`) that let the agent write
`plan.md`, `artifact/parts/*`, and `artifact/evidence/*`. Every iteration
browser has the storefront origin as its base URL, so `navigate` opens a
site path such as `/cart`. `src/explore/browser.ts` also gives the agent
its own `snapshot` tool. It shows at most 50,000 characters of the
accessibility tree. A longer tree comes in parts. A part ends at a line
end; only a line longer than the limit is cut inside the line. The note
after a part gives the `offset` of the next part. `@shop-gym/browser`
itself keeps the whole snapshot. The planner
emits the same 14 canonical Plan tasks, the fixed areas
(`FIXED_AREAS`), in every run on every platform: 11 for the surfaces
that every storefront has (homepage, header and departments, cart,
product, collection, predictive search, checkout, account, footer, info
pages, floating widgets) and three marketplace ones (`product_reviews`,
`related_products`, `search_results`). Their
briefs use platform-neutral words (for example, `cart_drawer` covers
any cart surface) and name the Capabilities that each task fills;
`homepage_sections` fills the `shop` block. The briefs keep the executor
on the storefront pages that a visitor sees: `collection_filters` starts
on a department or category landing page, not a search results page;
`product_reviews` scrolls a product page to its review block and skips
an all-reviews page behind a sign-in; `search_predictive` snapshots the
suggestion dropdown and captures no network or API request. A brief
that the planner makes more specific keeps these rules.
Each executor iteration writes `parts/<task_id>.md` and
`parts/<task_id>.caps.json`. An `anonymization` verifier scans the
current task's `parts/<task_id>.md` after every iteration for the store
domain, brand tokens from the prefetched homepage, absolute store URLs,
and email addresses, and reopens the task with line-level feedback on a
hit. A task gets at most two such reopens; the next hit blocks it with a
note that names the fragment.

Brand tokens come from the brand segment of the homepage `<title>` and
from `og:site_name`. The title splits at ` | `, ` - `, ` : ` and similar
separators, and after `.`, `!` or `?` that a space follows. The brand
segment is the one that matches a hostname label when spaces and
punctuation are removed; when no segment matches, every segment counts.
A segment that is only a stop word, such as "Home", gives no token.
The `brandTerms` option adds words or phrases, such as sub-brands, to
the markers. A term of more than one word matches as a phrase. The terms
are kept in `brand_terms.json` in `outDir`, outside the published files,
and a later call without `brandTerms` uses them again. After synthesis,
the final Anonymization scan (`publishedLeaks`) checks `manual.md`,
`capabilities.json` and `stats.json` (only the values of the JSON files)
for the same markers. A hit fails the `synthesize` step with an
`AnonymizationLeakError` that lists each `file:line`, and `manual.md` is
not written. The `graph` step scans `site_graph.json` the same way, and
a hit fails it with the same error before the file is written.

The scan matches only these markers. The prompts carry the other rules:
the executors write only what they saw and leave the rest `null` or
"unknown"; the synthesis prompt keeps only what the parts show and does
not contradict `capabilities.json`; and both put site-specific lists,
internal request names and the site's own feature names into generic
words.

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
its dependents: `prefetch` | `explore` | `merge` | `synthesize` | `graph`),
`forceResume` (resume a harness run that ended in a refused status),
`focus` (a hint that keeps the planner in one part of the site),
`brandTerms` (extra brand words or phrases for the Anonymization checks),
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

The merge step writes `coverage_gaps` in `manifest.json`. It lists each
area that the prefetch shows on the storefront and that nothing covers. A
done (`[x]`) Plan task or an entry in the `## Omitted Areas` block of
`plan.md` covers an area. A Plan task that is pending, in progress or
blocked when the run ends does not cover its area, so an unfinished,
failed or skipped area is a gap. When the plan has a Plan task with the
area's own name (for example `header_navigation`), only that task can
cover the area.

The merge step also writes `fixed_area_gaps`: one `{ area, reason }`
entry for each fixed area whose Plan task did not end done, whatever the
prefetch shows. The reason is one line: `not in the plan`, `not started
when the run ended`, `in progress when the run ended`, or `blocked:`
with the text that the executor added after the brief that the planner
wrote.

Storefront exploration never tries to pass a bot check. Prefetch stops
with `ShopUnreachableError` reason `bot_check` when the homepage is a
captcha, interstitial or rate-limit page (markers in
`src/explore/bot-check.ts`; a rate-limit marker counts only with HTTP
503, so a normal error page with the same words is not a bot check); a
Cloudflare challenge homepage keeps the reason `cloudflare_challenge`. In
the explore step, after each Browser tool call that loaded a page (not
only `navigate`), the page HTML and the HTTP status of the page are
checked for the same markers. On a bot check, the tool result tells the
executor not to try to pass the page and to mark its Plan task blocked
(`[!]`) with the note "bot check". While the page is a bot check,
`click`, `type`, `select` and `press` are refused with the same notice,
and the page does not change; `navigate` and `back` stay allowed. The
planner and executor prompts have the same rule. After two
Iterations in a row with a bot check (the planner Iteration counts too),
the explore step ends the harness run with a caller stop and the reason
`bot_check`. `navigate` refuses after `NAVIGATION_CAP` (200) calls in one
run of the explore step, and the run then stops after that Iteration with
the reason `navigation_cap`. A resume with `from: 'explore'` starts a new
count, as it gets a new iteration budget. A stopped
run has the final status `stopped`. Merge and synthesize still run on the
finished parts, the unfinished areas are coverage gaps, and
`manifest.json` records `stop: { reason, iteration, blocked_tasks }`
(`null` when the run did not stop early). `ExploreResult.stop` gives the
reason and the Iteration, and `shopgym explore` exits 0 for `completed`
and `stopped`.

## Gen

`generateShop(config, deps)` (also under the `gen` namespace export)
turns one or more Shop Manuals into a SandboxShop under
`outputs/shops/<name>/`. It runs six steps on the `@shop-gym/core`
pipeline runner; `GEN_STEPS` lists them in order:

| Step | Reads | Writes |
| --- | --- | --- |
| `manual_merge` | each manual dir's `manual.md`, `capabilities.json`, `stats.json`; the checked-in Standard sub-manual `src/gen/manual_merge/standard_sub_manual.md` | `manual/` (`manual.md`, `capabilities.json`, `stats.json`, `parts/*.md`, `manifest.json`); one manual is copied, several are merged (deterministic capability rules, LLM tiebreak for the descriptor and tied layout enums, LLM prose merge per H2 section); `parts/` holds the six Sub-manuals cut from `manual.md` and the shop's copy of the Standard sub-manual as `parts/standard.md`. Fusion: for each observed `## Account` or `## Checkout` section in `manual.md`, one LLM call fuses the notes into the copy. Observed labels and layout win. Unsupported behavior and the labels that the browser steps check keep the standard text. With no observed notes, the copy is unchanged and there is no LLM call. Merged stats take the totals only from the `catalog_endpoint` seeds; the merged `source` is `observed_sample` when any seed is, and `sample_size` adds up the seeds |
| `data_synth` | `manual/`; with `sourceDataDir` (`--data`), also `products.json`, `collections.json` and `images/` of that Dataset | `data/` (`store`, `products`, `collections`, `navigation`, `pages`, `policies`, `inventory`, `customers`, `orders`, `commerce`, `reviews` `.json` and `images/`), `identity.json`, `.shop_gen/stage_cache/` |
| `data_validation` | `data/` | `data_validation.json` (backend zod schema, referential integrity that includes the product and variant of each Review, valid Discount codes, seeded order totals and discounts that follow the backend pricing rules, hosting smoke on the pristine backend template: shop, products, collection, search, image, cart create / add / `checkoutComplete` as the first seeded customer) |
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

With `sourceDataDir` (`shopgym gen --data <dir>`), `data_synth` copies
the catalog of an existing SandboxShop Dataset. It does not run
`collections` through `images`. The products and collections keep the
same JSON values. This includes the fields that the backend schema does
not name.
`images/` is copied as it is. `data_synth` drops each collection with no
products and logs its handle. `identity` gets a summary of the copied
catalog: the product count, the collections, the most common product
types, the price range and some titles. The descriptor and tone must fit
these products. Menus link only to the kept collections. All other files
come from the manual as usual, so `catalog` and `imageBackend` do not
apply. A change to the three source paths runs `data_synth` again.

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
| `routes_200` | storefront tasks | static routes and the routes of every page bucket return 200, whatever the task; `/account*` redirect to `/account/login` logged out and return 200 after logging in as the first seeded customer; `/checkout` and `/cart.js` return 200 with a line in the cart; internal links from rendered pages resolve. Failures list status, redirect target and a body excerpt |
| `nav_coverage` | `gen_navigation`, `gen_theme`, `visual_fix` | every `navigation.json` target returns 200 and is linked from the rendered header or footer |
| `cart_conformance` | `gen_cart_search`, `gen_product`, `gen_checkout`, `visual_fix` | add, update quantity, cart page totals equal the backend cart cost, remove, guest checkout, confirmation page shows the order; after the add, the update and the remove, `GET /cart.js` returns the backend cart in the AJAX cart fields |
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
  "sourceManuals": ["/abs/path/to/outputs/shop_manuals/<host>/<run_id>"],
  "templates": { "storefront": { "name": "storefront", "commit": "...", "dirty": false, "contentHash": "...", "files": {}, "seededAt": "..." }, "backend": { "...": "..." } },
  "genBackend": true,
  "publishedAt": "2026-09-30T00:00:00.000Z",
  "finalStatus": "completed"
}
```

Calling it again replaces both component directories and rewrites the
manifest. `publish.readShopManifest(shopDir)` parses and validates it;
`dirty` may be absent in manifests written before the flag existed.
