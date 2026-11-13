# Storefront exploration (`packages/shop-arena/src/explore`)

Status: **Implemented (`exploreStorefront`, `shopgym explore`)** · Version: **1.3**
Owners: ShopArena

> A storefront exploration pipeline that produces an anonymized **Shop
> Manual**: a structured, machine- and human-readable description of a
> Live storefront's UX, IA and feature set, so that a SandboxShop can
> later be synthesized from one or more such manuals.

---

## 1. Overview

Storefront exploration (`exploreStorefront` in `@shop-gym/shop-arena`,
`shopgym explore` in the CLI) reads one storefront URL and writes a
**Shop Manual**: a small set of Markdown and JSON files that tells the
structure, navigation and features of the shop (cart, search, filters,
sort, drawers, popups, reviews and so on) in an anonymized form.

Three design choices define the module:

- **Harness-driven exploration.** All browsing happens inside
  `@shop-gym/harness` plan-then-loop Iterations. A planner agent looks
  at the shop briefly and writes a Plan with the 14 Fixed areas and any
  shop-specific tasks. Each executor Iteration works on one Plan task
  and drives a new headless browser through the Browser tools of
  `@shop-gym/browser`. The module owns the prompts, an `AGENTS.md`, a
  deterministic prefetch step, the Verifiers, the bot-check rules and
  the steps after the loop. It owns no LLM session management and no
  telemetry plumbing. The harness owns those.
- **Two Platform paths.** Prefetch decides if the storefront is a
  Shopify shop (`shopify`) or another site (`generic`). The Shopify path
  reads the catalog endpoints of the shop. The generic path reads only
  `robots.txt`, the homepage and `sitemap.xml`, and the executors record
  Product observations for the catalog statistics.
- **Decoupled output.** A Shop Manual is a standalone set of files
  keyed by domain and run id. It is **not** tied to a SandboxShop. Shop
  generation (`shopgym gen`) reads one or more Shop Manuals as input.

Storefront exploration is the first non-trivial caller of
`@shop-gym/harness` and exercises its public surface end to end.

---

## 2. Terminology

- **Storefront** - the public, unauthenticated view of an online store
  at a given base URL. A real one is a Live storefront (`GLOSSARY.md`).
- **Shop Manual** - the files that this module writes for one
  storefront run: `manual.md` (prose), `capabilities.json` (structured
  features), `stats.json` (catalog statistics), `site_graph.json` (the
  Site state graph, §5.13) and `manifest.json` (the run summary), next
  to the prefetch seed and the harness workspace. See §5.4.
- **Capability** - a structured, schema-validated fact about one
  feature of the storefront (e.g. `cart.type=drawer`,
  `search.has_predictive=true`, `collection.filters=[size,color,price]`).
- **Platform path** - the way that the run reads the storefront, as
  prefetch decides it: `shopify` or `generic` (§5.9). `prefetch.json`
  and `manifest.json` record it as `platform`.
- **Prefetch** - a deterministic, no-LLM HTTP fetch of a fixed, small
  set of URLs before the loop. Every run fetches `robots.txt`, `/`,
  `/sitemap.xml` and the first `/products.json` page. The Shopify path
  then fetches the rest of the catalog and a fixed list of Shopify
  endpoints and pages. The output goes to `seed/prefetch/`, and the
  harness copies it to `run/artifact/prefetch/`.
- **Task brief** - the note text that follows a task id in a
  `plan.md` task line. The harness plan parser needs the U+2014 dash
  character between the id and the brief. The planner writes the brief,
  and the executor reads it.
- **Fixed area** - one of the 14 canonical Plan tasks that the planner
  emits in every run, on both Platform paths (§5.7). Each one ends done,
  or `manifest.json:fixed_area_gaps` lists it with a one-line reason.
- **Coverage taxonomy** - the list of feature areas that a storefront
  can have (§5.3). The planner lists the areas that the storefront does
  not have under `## Omitted Areas` in `plan.md`.
- **Focus hint** - the `focus` text (`--focus`) that tells the planner
  which part of a large site to explore (§5.14). It is a hint, not a
  filter.
- **Product observation** - one schema-checked record of one product
  page that an executor opened on a generic site: price, currency and
  variant facts, with no name, URL, seller or brand (§5.6).
- **Anonymization** - the rule that the manual describes structure and
  UX patterns, not the original shop. The prompts give the rules at
  write time. Two deterministic checks enforce the brand markers: the
  `anonymization` Verifier on the fragment of each Plan task, and the
  final scan of the published files (§5.15). Other identifying text,
  such as product names, has only prompt rules.
- **Brand term** - a word or phrase, such as a sub-brand, that the
  person who runs exploration adds with `--brand-term`, because the
  homepage title does not name it (§5.15).
- **Bot check** - a page that a site shows in place of the page that
  was asked for, to find out whether the visitor is a person: a
  Cloudflare challenge, a captcha page, an interstitial page with one
  button, or a rate-limit page served with HTTP 503. Exploration never
  tries to pass one (§5.16).
- **Navigation cap** - the fixed number of `navigate` calls (200) that
  one call of the explore step may make, over all its Iterations
  (§5.16).
- **Site state graph** - the published file `site_graph.json`. It tells
  how a shopper moves through the storefront: its states are pages and
  overlays, and its transitions are shopper actions from one state to
  another. See §5.13.
- **Trajectory digest** - the browser actions of one executor
  Iteration, one line for each action. The `graph` step gives it to its
  LLM call. It has no refs, hosts, query values or typed text.

---

## 3. Current Status

- v0.1 (Python, `shop_arena.explore`) shipped first: deterministic
  prefetch, a harness-driven planner and executor loop, and
  deterministic synthesis into `manual.md`, `capabilities.json`,
  `stats.json` and `manifest.json`, with replay cassettes as tests. The
  Python code was removed at the v1.1 cutover.
- v1.1 TypeScript port (2026-09-30): `packages/shop-arena/src/explore/`
  exposes `exploreStorefront(options)` and re-implements the pipeline on
  `@shop-gym/core` `runPipeline` (steps `prefetch`, `explore`, `merge`,
  `synthesize`; `from` replaces `--prefetch-only` / `--synthesize-only`),
  `@shop-gym/harness` `runPlanExecLoop` with the pi runtime, and
  `@shop-gym/browser` tools plus run-dir-scoped `read_file` /
  `write_file` / `list_dir` tools (the pi runtime exposes only the
  request's tools). Changes from v0.1: `capabilities.json` gains
  `account` and `checkout` blocks (schema version `0.2`) with matching
  canonical tasks `checkout_flow` and `account_pages`; a deterministic
  `anonymization` verifier fails an executor iteration whose
  `parts/*.md` mention the store domain, brand tokens from the prefetched
  homepage, absolute store URLs, or email addresses; the manual is one
  `LlmClient.complete` call (a response under 200 characters fails the
  step instead of falling back to the parts concatenation); screenshots
  are kept by the runtime under the iteration directory rather than
  under `evidence/`. Published files (`manual.md`, `capabilities.json`,
  `stats.json`, `manifest.json`) sit at `<run_id>/`; the harness
  workspace lives at `<run_id>/run/` and the prefetch seed at
  `<run_id>/seed/prefetch/`. The `shopgym explore` CLI came with v1.1
  M10.
- Fresh browser per Iteration (2026-11-05): the explore step gives every
  planner and executor Iteration a new headless browser through the
  harness `onIterationStart` hook, so no cookies, storage or cart carry
  over from an earlier Iteration. Each new browser opens the storefront
  homepage. When the prefetched `cart.js` parses as a cart, the browser
  also reads `/cart.js`. The explore step writes the result to
  `run/iters/<id>/start_state.json` as `{ url, cart, error }`. When the
  homepage or the cart cannot be read, `error` gives the reason, and the
  Iteration still runs. All browsers of a run send the same
  `x-shopgym-episode` header. The storefront origin is the base URL of
  every browser, so `navigate` opens a site path such as `/cart` on the
  storefront. The explore `snapshot` tool shows at most 50,000
  characters of the accessibility tree in one result. A longer tree comes
  in parts of whole lines. Only a line longer than the limit is cut
  inside the line. The note after a cut part gives the `offset`
  for the next part. It also says that a scroll does not change the
  snapshot. An offset inside a line moves to the start of the next
  line. The other users of `@shop-gym/browser` keep the whole snapshot.
- Anonymization scope and reopen cap (2026-11-05): the `anonymization`
  verifier scans only `parts/<task_id>.md` of the selected task, so a
  leak in one fragment no longer reopens other tasks. It reopens a task
  at most twice; the next hit blocks the task with a note that names the
  fragment. The count per task is kept in
  `run/checks/anonymization_reopens.json`, so a resumed run keeps it.
- Coverage counts only done tasks (2026-11-05): a pending, in-progress
  or blocked Plan task does not cover its area, so a stopped or failed
  run lists the area in `coverage_gaps` (SC5).
- Platform paths (2026-11-05): prefetch decides the platform before the
  fetch plan (§5.9). Both paths fetch `robots.txt`, `/`, `sitemap.xml`
  and one `/products.json` probe. The `shopify` path then runs the
  Shopify fetch plan. The `generic` path stops there, and the planner
  gets `planner_generic.md`, which picks same-origin start paths from the
  homepage links and the sitemap. On both paths, prefetch skips a
  `sitemap.xml` that `robots.txt` forbids and keeps at most 1 MiB of it.
  `prefetch.json` and `manifest.json` record `platform`. A
  `prefetch.json` with no `platform` reads as `shopify`, so older runs
  resume.
- Marketplace Plan tasks and Capabilities 0.3 (2026-11-05): the planner
  emits 14 Fixed areas in every run, on both paths: the 11 earlier
  canonical tasks and three marketplace areas, `product_reviews`,
  `related_products` and `search_results` (§5.7). The briefs use
  platform-neutral words and name the Capabilities that each task fills.
  Each Fixed area that does not end done is in
  `manifest.json:fixed_area_gaps` with a one-line reason. The
  Capabilities schema goes to version `0.3` with a `departments` block,
  `search.facets`, `search.sort`, `product.has_rating_histogram`,
  `product.review_filters` and `product.related_product_types` (§5.5).
  A 0.2 document still parses. The Shop generation manual merge keeps
  the new fields.
- Catalog statistics from an observed sample (2026-11-05): on a generic
  site, `stats.json` comes from the Product observations of the
  executors (`source: observed_sample`); on a Shopify shop it comes from
  the catalog (`source: catalog_endpoint`). Both record `sample_size`
  (§5.6). The Shop generation stats schema accepts both new fields.
- Brand segment, brand terms and the final scan (2026-11-05): brand
  tokens come only from the brand segment of the homepage title (the
  segment that matches a hostname label), from `og:site_name` and from
  the hostname labels; when no segment matches, every segment counts. A
  repeatable `--brand-term <word>` (option `brandTerms`) adds sub-brands;
  a term of more than one word matches as a phrase. The terms are kept
  in `<run_id>/brand_terms.json`, which Shop generation does not read,
  and the `anonymization` verifier uses them. After synthesis, the final
  scan checks `manual.md`, `capabilities.json` and `stats.json` (JSON
  values only) for the host, email addresses, brand tokens and brand
  terms, and fails the `synthesize` step with `AnonymizationLeakError`
  before it writes `manual.md`. `manifest.json` is not scanned, because
  it records the `domain` by design. Since 2026-11-11 the `graph` step
  runs the same scan on `site_graph.json` (§5.15).
- Observed facts only (2026-11-05): the shared executor instructions
  (`AGENTS.md`) say to write only what the run saw. A field that the run
  did not see stays `null`, and `false` means that the run saw the
  feature is absent. The synthesis prompt keeps only what the parts
  show, marks what a part did not see as unknown, and lets no sentence
  contradict `capabilities.json`. Both prompts put site-specific lists,
  internal request names and the site's own feature names into generic
  words. These are prompt rules; the final scan matches only the brand
  markers, the host and email addresses.
- Focus hint (2026-11-05): an optional `focus` (`--focus <text>`) adds
  `planner_focus.md` after the planner prompt (§5.14). The planner picks
  its pages and queries in the focus and writes the focus into the
  briefs. Navigation is not blocked. `focus.json` and
  `manifest.json:focus` record it, and a resume must pass the same focus.
- Bot checks and the Navigation cap (2026-11-05): prefetch stops on a
  captcha, interstitial or rate-limit homepage with the reason
  `bot_check`. In a run, the Browser tools find bot-check pages, add a
  notice to the tool result, and refuse `click`, `type`, `select` and
  `press` on them. Two Iterations in a row with a bot check, or 200
  `navigate` calls in one explore-step call, end the run with a harness
  Caller stop. A stopped run still writes the manual from the finished
  parts, records `stop` in `explore.json` and `manifest.json`, and
  `shopgym explore` exits 0 (§5.16).
- First run on a generic site (2026-11-06): the Video Games Shop Manual
  of a large marketplace, with `--focus "Video Games"`. The live run
  stopped on bot checks after 3 of the 14 Fixed areas. The other 11
  parts were written offline from page captures, and a `--from merge`
  run with no site traffic wrote the manual. The user accepted this
  manual on 2026-11-11 (§8.4).
- Site state graph (2026-11-11): a fifth step, `graph`, runs after
  `merge` and writes `site_graph.json` with one `LlmClient.complete`
  call, and one repair call when the reply fails a check. It reads the
  finished fragments with no Styling lines, the Trajectory digests of
  their executor Iterations, and the merged Capabilities.
  `parseSiteGraph` of `@shop-gym/core` checks the reply with a closed
  schema and graph rules. The step adds a source check and the
  Anonymization scan. A failed check of the repair reply, or a leak,
  writes no file.
  `--from graph` adds a graph to an existing Shop Manual. The graph
  step does not browse, and it does not write `manual.md`.
  `manifest.json:paths.site_graph` names the file. See §5.13. The
  first graph, of the Video Games Shop Manual, is reviewed and
  accepted (2026-11-12). After the review, a `load` trigger fixes the
  trigger limit, and sharper prompt rules fix the rule breaks of the
  review. Two reruns show that the model still breaks other prompt
  rules, and that the breaks change from run to run.

---

## 4. Desired Status

A self-contained module under `packages/shop-arena/src/explore/` that,
given a storefront URL, runs one harness `runPlanExecLoop` against it
and emits a Shop Manual under `outputs/shop_manuals/<domain>/<run_id>/`.

### 4.1 I/O contract

**Inputs** (library option, with the CLI option in brackets):

| Input                                  | Notes                                                                                                   |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `url`                                  | Public storefront URL. Required. Only the scheme and the host are used.                                 |
| `outDir` (`--out`)                     | Defaults to `outputs/shop_manuals/<domain>/<run_id>/` under the working directory. An existing `outDir` resumes (§5.2). |
| `model` (`--model`)                    | `provider/model-id`. Library default `anthropic/claude-opus-4-7`; CLI default `openai/gpt-5.5`.        |
| `maxIters` (`--max-iters`)             | Executor Iterations of the explore step. Default 20.                                                    |
| `timeoutMs` (`--timeout`)              | Wall clock budget of one Iteration. Default 1,800,000 ms (30 minutes).                                  |
| `from` (`--from`)                      | Force this step and every step after it: `prefetch`, `explore`, `merge`, `synthesize` or `graph`.       |
| `forceResume` (`--force-resume`)       | Resume a harness run that ended in a refused status.                                                    |
| `focus` (`--focus`)                    | The Focus hint (§5.14). The CLI refuses a blank value.                                                  |
| `brandTerms` (`--brand-term`, repeatable) | Brand terms (§5.15). A term with no letter or digit fails the call.                                  |

Library only: `credentials` (required; the CLI reads them with the
repository credentials loader), `rateLimitMs` (the prefetch pace),
`runtime` and `llm` (inject an `AgentRuntime` and an `LlmClient`, for
tests), `onEvent`, `log` and `signal`.

**Outputs** (under `<outDir>/`):

The published files sit at `<outDir>/`. The harness workspace is
`<outDir>/run/`, and the prefetch seed is `<outDir>/seed/prefetch/`.
See §5.4 for the full layout.

**Out of scope:**

- Authenticated flows. The executors look only at the public sign-in
  and sign-up entries and never submit them.
- Orders and payment. `checkout_flow` stops at the first sign-in or
  payment wall.
- Any way to pass a bot check: captcha solving, proxies, user agent
  rotation or stealth browsers (§5.16).
- Rules for each path in `robots.txt`. Prefetch keeps the root gate and
  the sitemap check only (§8.2).
- Platform paths other than `shopify` and `generic`.
- Cross-shop merging and SandboxShop synthesis (Shop generation,
  `docs/specs/shop_arena/shop_gen.md`).
- Sandbox shop generation, asset rewriting, GraphQL mocking.
- Asset downloads beyond the screenshots that the runtime keeps.
- A deterministic scrubber that rewrites leaks. The final scan fails
  the run; it does not change the text (§6 E).

### 4.2 Success criteria

- **SC1 - One command.** `shopgym explore <url>` produces a complete
  Shop Manual under `outputs/shop_manuals/<domain>/<run_id>/` with no
  additional flags required.
- **SC2 - Schema-valid capabilities.** `capabilities.json` validates
  against the closed 0.3 schema (§5.5). Unknown fields are rejected. A
  0.2 document still parses.
- **SC3 - Anonymized.** The published files `manual.md`,
  `capabilities.json`, `stats.json` and `site_graph.json` contain no
  occurrence of the source host, an email address, a brand token or a
  Brand term. The final scan enforces this in the production pipeline
  (§5.15). Product names and the site's own feature names have prompt
  rules only.
- **SC4 - Tested with no live site.** The tests drive
  `exploreStorefront` end to end with `FakeRuntime` scripts and a stub
  `LlmClient` against local HTTP fixture storefronts with fake brand
  names: a Shopify fixture and a generic fixture. No test opens a live
  site.
- **SC5 - Coverage.** On the fixture set, every coverage-taxonomy area
  that prefetch evidence indicates is present (§5.7) appears as either
  a done planner task or a justified omission in `manifest.json`. A
  pending, in-progress, or blocked task does not cover its area. When
  the plan has a task with the area's own name, only that task can cover
  the area. Each evidenced area that nothing covers is listed in
  `manifest.json:coverage_gaps`. Apart from the evidence, each of the
  14 fixed areas (the canonical Plan tasks that the planner emits in
  every run: 11 for the surfaces of every storefront and
  `product_reviews`, `related_products`, `search_results`) that does
  not end done is listed in
  `manifest.json:fixed_area_gaps` with a one-line reason.
- **SC6 - Generic sites and bot checks.** On the generic fixture, the
  run takes the generic path, and `stats.json` comes from the Product
  observations. A Plan task that meets a bot-check page is blocked, and
  no page action runs on that page. Two Iterations in a row with a bot
  check, or the Navigation cap, stop the run, and the run still
  publishes the manual with the stop and the gaps in `manifest.json`.

---

## 5. Proposal

### 5.1 Architecture

```
url
 │
 ▼
prefetch ───► seed/prefetch/                         no LLM; gates; Platform path
 │
 ▼
explore ────► run/ (harness workspace), explore.json  @shop-gym/harness runPlanExecLoop:
 │                                                    1 planner Iteration, then executor
 │                                                    Iterations, one Plan task each
 ▼
merge ──────► capabilities.json, stats.json,          no LLM
 │            manifest.json
 ├──────────────────────────────┐
 ▼                              ▼
synthesize ─► manual.md         graph ─► site_graph.json
1 LLM call + final scan         1 LLM call, at most 1 repair, + scan
```

Storefront exploration is a thin layer over the harness. The harness
owns the loop, telemetry, resume and `run.json`. The agent runtime
(default `pi`) owns the LLM session. Storefront exploration owns four
things:

1. **Prefetch** - one deterministic step before the loop (§5.9).
2. **Prompt and `AGENTS.md` bundle** - the planner and executor
   instructions for each Platform path, and the project constitution
   that scopes the run (§5.8).
3. **Tools, Verifiers and stops** - a new browser for each Iteration,
   the run-dir-scoped file tools, the `record_product_observation` tool
   on a generic site, the `anonymization` and `product_observations`
   Verifiers, and the Caller stop on bot checks and at the Navigation
   cap (§5.16).
4. **Steps after the loop** - deterministic merge and stats, one LLM
   call for the prose, the graph step, and the final scan (§5.10,
   §5.13, §5.15).

### 5.2 Execution model

```
shopgym explore <url>               (library: exploreStorefront(options))
  │
  ├─ 1. normalize the url to scheme + host, derive domain + run_id,
  │     check the focus against focus.json, resolve the Brand terms
  ├─ 2. prefetch   -> seed/prefetch/                         (no LLM)
  │      • stop with ShopUnreachableError at a gate (§5.9)
  │      • decide the Platform path, record it in prefetch.json
  ├─ 3. explore    -> run/, focus.json, explore.json
  │      • runPlanExecLoop({
  │            runDir: run/,
  │            prompts: { planner (by platform, + focus hint),
  │                       execute (by platform) },
  │            agentsMd, artifactSeedDir: seed/,
  │            tools, verifiers, maxIters, timeoutMs, model,
  │            onIterationStart: new browser + start_state.json,
  │            onIterationEnd: Caller stop on bot checks or the cap,
  │         }, runtime, { force: forceResume })
  │      • 1 planner Iteration, then ≤ maxIters executor Iterations
  │      • each executor Iteration = one Plan task in plan.md
  ├─ 4. merge      -> capabilities.json, stats.json, manifest.json
  │      • merge parts/*.caps.json                      (deterministic)
  │      • stats from the catalog or the Product observations
  │      • manifest: counts, omissions, conflicts, gaps, stop, paths
  ├─ 5. synthesize -> manual.md
  │      • 1 LLM call: parts/*.md + capabilities.json -> manual text
  │      • final Anonymization scan; a leak writes no manual.md
  ├─ 6. graph      -> site_graph.json (§5.13)
  └─ 7. exit code (CLI) = 0 iff every step passed AND the harness
                          final status is `completed` or `stopped`
```

A gate in prefetch, a failed step or an error stops the pipeline, and
the CLI exits 1. A harness run that ends with a status other than
`completed` or `stopped` (for example `budget_exhausted` or
`runtime_error`) still runs the later steps, but the CLI exits 1.

Calling again with the same `outDir` skips each complete step (the
records in `.pipeline/`) and resumes an unfinished harness run. `from`
forces a step and every step after it. The pipeline never deletes
`run/`, so `from: 'explore'` continues the same exploration with a new
Iteration budget.

The planner Iteration receives the prefetch files in
`run/artifact/prefetch/` via `artifactSeedDir`. It must browse at most
4 pages with `navigate` (homepage, one listing page, one product page,
one more page only when needed) before it writes `plan.md`; this is
enforced by the planner prompt, not the harness.

### 5.3 Coverage taxonomy

The coverage taxonomy names the feature areas that a storefront can
have:

```
Site shell:        announcement_bar, header_navigation, mega_menu, footer
Departments:       department_menu (count, levels)
Homepage:          hero, sections (featured_collection / banner / testimonials /
                   carousel / video), newsletter, popups
Collection:        listing_layout, product_card, filters, sort, pagination
Product detail:    gallery, variant_selectors, qty_selector, add_to_cart,
                   description, recommendations, reviews, rating_histogram,
                   review_filters, related_product_blocks
Cart:              cart_drawer_or_page, line_item_edit, upsells, promo_code
Search:            search_trigger, predictive, results_layout, facets, sort
Checkout:          guest_checkout, shipping, payment, discount_code
Account:           sign_in, sign_up
Info / policy:     about, contact, shipping, returns, privacy, tos, faq, gift_cards
Internationalization: locale_switcher, currency_switcher
Floating:          chat_widget, age_gate, cookie_banner
```

The planner does not decide which surfaces to explore. It emits the 14
Fixed areas (§5.7) in every run, verbatim, in a fixed order and with
fixed priorities, also when a feature looks absent. If a feature is
missing, the executor says so in its fragment, and `capabilities.json`
shows it. This keeps runs stable across shops and gives the synthesis
a predictable input shape. The planner can add shop-specific Plan
tasks after the 14, each with a one-line evidence reference in its
brief.

Three Fixed areas are marketplace areas: `product_reviews`,
`related_products` and `search_results`. They fill the 0.3
Capabilities of large sites: rating histograms, review filters,
related-product blocks, search facets and search sort.

Areas observed-absent are listed in `plan.md` under `## Omitted Areas`
with a one-line reason, and merge copies them to
`manifest.json:omitted_areas`. A Fixed area id is never an omitted
area.

### 5.4 Output layout

`outDir` holds the published files, the prefetch seed, the harness
workspace and the step records. The harness owns the structure of
`run/` (§5.3 of the harness spec); Storefront exploration owns
everything else, and the agents write under `run/artifact/`.

```
outputs/shop_manuals/<domain>/<run_id>/      # outDir
├── manual.md                 # PUBLISHED - prose, anonymized
├── capabilities.json         # PUBLISHED - Capabilities, schema 0.3
├── stats.json                # PUBLISHED - catalog statistics
├── site_graph.json           # PUBLISHED - Site state graph (§5.13)
├── manifest.json             # PUBLISHED - run summary, gaps, stop, paths
├── seed/
│   └── prefetch/             # written by prefetch (no LLM)
│       ├── prefetch.json     # platform + one entry per request
│       ├── robots.txt
│       ├── index.html
│       ├── sitemap.xml       # when robots.txt allows it; at most 1 MiB
│       ├── products.json     # shopify: all catalog pages, merged
│       ├── collections.json  # shopify only, as the 5 files below
│       ├── search_suggest.json
│       ├── cart.js
│       ├── cart.html
│       ├── search.html
│       ├── policies/         # shopify: 4 policy pages
│       └── pages/            # shopify: about, contact, faq
├── run/                      # harness workspace (runDir)
│   ├── AGENTS.md
│   ├── prompts/              # planner.md, execute.md as the run got them
│   ├── plan.md
│   ├── run.json
│   ├── iters/<id>/           # trajectory, metadata, start_state.json
│   ├── checks/anonymization_reopens.json
│   └── artifact/
│       ├── prefetch/         # copy of seed/prefetch/ (artifact seed)
│       ├── parts/            # written by executors
│       │   ├── <task_id>.md
│       │   ├── <task_id>.caps.json
│       │   └── <task_id>.product-<key>.json # generic sites only (§5.6)
│       └── evidence/         # written by executors
│           └── <task_id>/
│               ├── snapshots/    # `snapshot` text, one per page state
│               └── network.jsonl # optional
├── focus.json                # the Focus hint of the run, or null
├── explore.json              # harness outcome: final_status, iters, stop
├── brand_terms.json          # Brand terms; never published
└── .pipeline/                # step records of the pipeline runner
```

The **published** files are `manual.md`, `capabilities.json`,
`stats.json`, `site_graph.json` and `manifest.json`. Shop generation
reads `manual.md`, `capabilities.json` and `stats.json` (ADR 0012).
`manifest.json` records the `domain` by design, so the final scan does
not cover it. Everything else (`seed/`, `run/`, `brand_terms.json` and
the step files) is run state and debugging context. It can hold raw
site text, and tooling that ships manuals around must leave it out.

`<run_id>` is `<UTC timestamp>-<8 hex digits>`, where the digits are
the SHA-256 prefix of `(url, runtime, version)`, so parallel runs of
the same shop do not collide.

### 5.5 Capabilities schema

`capabilities.json` is one zod `strictObject` in
`src/explore/capabilities.ts`, at schema version `0.3`. It is
**closed** (extra fields rejected) so schema drift is loud. Each scalar
is nullable (`null` means unknown), and each list defaults to empty, so
a fragment fills only its own fields. Top-level shape, with fake
values:

```json
{
  "version": "0.3",
  "shop": {
    "descriptor": "premium minimalist jewelry store",
    "category": "fashion_accessories",
    "currency": "USD",
    "tone": ["minimal", "luxury"]
  },
  "site_shell": {
    "has_announcement_bar": true,
    "header_style": "horizontal",
    "has_mega_menu": true,
    "nav_depth": 2,
    "footer_groups": 4
  },
  "departments": {
    "has_department_menu": true,
    "department_count": 12,
    "max_depth": 3
  },
  "homepage": {
    "section_types": ["hero_carousel", "featured_collection",
                      "promo_banner", "testimonials", "newsletter"],
    "section_count": 5,
    "has_popup_modal": true
  },
  "collection": {
    "layout": "grid",
    "columns_desktop": 4,
    "filters": ["size", "color", "price"],
    "sort": ["featured", "price_asc", "price_desc", "newest"],
    "pagination": "load_more"
  },
  "product": {
    "gallery_style": "thumbnail_strip",
    "variant_selectors": ["color_swatch", "size_button"],
    "has_quantity_selector": true,
    "description_layout": "tabs",
    "has_reviews": true,
    "has_recommendations": true,
    "has_personalization": false,
    "has_rating_histogram": true,
    "review_filters": ["star_rating"],
    "related_product_types": ["bought_together", "also_viewed"]
  },
  "cart": {
    "type": "drawer",
    "has_promo_input": true,
    "has_upsells": true,
    "has_shipping_estimate": false
  },
  "search": {
    "trigger": "header_icon",
    "has_predictive": true,
    "predictive_types": ["products", "collections"],
    "results_layout": "grid_with_filters",
    "facets": ["brand", "price", "rating"],
    "sort": ["relevance", "price_asc", "newest"]
  },
  "floating": {
    "has_chat_widget": true,
    "has_age_gate": false,
    "has_cookie_banner": true,
    "has_newsletter_popup": true
  },
  "intl": {
    "has_locale_switcher": true,
    "has_currency_switcher": false
  },
  "account": {
    "has_login": true,
    "has_signup": true,
    "has_profile": null,
    "has_addresses": null,
    "has_order_history": null
  },
  "checkout": {
    "has_guest_checkout": true,
    "payment_methods": ["card", "wallet"],
    "has_discount_code": true,
    "shipping_options": ["standard", "express"]
  },
  "info_pages_present": ["about", "contact", "shipping_policy",
                         "returns_policy", "privacy", "tos", "faq",
                         "gift_cards"]
}
```

**Versions.** 0.2 added the `account` and `checkout` blocks. 0.3 added
the `departments` block, `search.facets`, `search.sort`,
`product.has_rating_histogram`, `product.review_filters` and
`product.related_product_types`. Each new field is nullable or defaults
to an empty list, so a 0.2 document still parses. `version` defaults to
`0.3`, and a parse keeps the version that a document gives. `AGENTS.md`
shows the schema as JSON Schema, rendered at run time, so it cannot
drift.

Each executor writes a fragment matching one or more top-level keys to
`parts/<task_id>.caps.json`. The post-loop merge is a deterministic
deep-merge with the rule: **last writer wins per leaf**, except lists
(union, deduplicated, order-preserving) and `null`. For a scalar field,
`null` means unknown: it never replaces a non-null value, and a later
non-null value fills it. Neither case is a conflict. Conflicts (two
different non-null values for one leaf) are recorded in
`manifest.json:capability_conflicts`.

The Shop generation manual merge, which merges the Capabilities of
more than one Shop Manual, has its own rules for the 0.3 fields:
`departments.has_department_menu` and `product.has_rating_histogram`
are true when any manual says true, `departments.department_count` is
the most common value, `departments.max_depth` is the largest value,
and the 0.3 lists are the union.

### 5.6 Stats schema

`stats.json` is computed deterministically by `src/explore/stats.ts`.
No LLM. The source depends on the platform:

- **`catalog_endpoint`** (Shopify). The stats come from `prefetch/` (the
  Shopify catalog endpoints) + `capabilities.json`. `sample_size` is the
  number of products read.
- **`observed_sample`** (generic). The site has no catalog endpoint. Each
  executor records each product page that it opens with the
  `record_product_observation` tool, while the page is open. The
  executor gives only `price`, `currency`, `has_variants` and
  `variant_axes` (axes as short generic nouns, not the label text of the
  page); the schema is closed, has no name, URL, seller or brand field,
  and is shown in `AGENTS.md`. The tool refuses facts that do not match
  the schema. It takes the page key from the open page, not from the
  model: the first 12 hex digits of the SHA-256 of the page URL without
  its query and fragment, where the URL is the `<link rel="canonical">`
  target when the page has one. It writes the fragment
  `parts/<task_id>.product-<key>.json`. A `product_observations` Verifier
  fails the executor Iteration of a fragment that does not match the
  schema. The sample has one fragment for each page key, so a product
  page that more than one task records counts once (the first fragment in
  filename order). The price stats use the fragments of the sample in the
  most frequent currency; `products_with_variants_pct` and
  `variant_axes_observed` (sorted) use all of them. `sample_size` is the
  number of distinct product pages. `products_total`,
  `collections_total` and `products_per_collection` stay 0, because a
  sample does not show them. Shop generation takes its totals from its
  config targets either way. The key has limits. A site that gives each
  variant its own URL counts each variant page as one product. A call
  made after the executor left the product page records the key of the
  page that is open then. The key is a hash, not the URL. But a person
  who already knows a product URL can check if the run recorded it.

Shape:

```json
{
  "source": "catalog_endpoint",
  "sample_size": 124,
  "products_total": 124,
  "collections_total": 12,
  "products_per_collection": {"avg": 18.2, "median": 14, "max": 60},
  "price": {"min": 12.0, "max": 480.0, "median": 65.0, "currency": "USD"},
  "products_with_variants_pct": 0.86,
  "variant_axes_observed": ["size", "color", "material"],
  "navigation_depth_max": 2,
  "homepage_section_count": 5,
  "info_pages_count": 7,
  "feature_count": 24
}
```

`feature_count` is derived from `capabilities.json` (sum of truthy
booleans + non-empty list lengths) and provides a single coverage
number for cross-shop comparison.

On both paths, `navigation_depth_max` is `site_shell.nav_depth` and
`homepage_section_count` is `homepage.section_count`. An unknown
(`null`) count becomes 0, so 0 can mean "none" or "unknown" (§8.2).
`info_pages_count` is the length of `info_pages_present`.

### 5.7 Plan + executor contract

The planner emits `plan.md` tasks of the form:

```
- [ ] homepage_sections — capture all sections below the hero, full-page screenshot per section [priority: 8]
- [ ] cart_drawer        — add 1 product, capture drawer states (empty, filled, qty change) [priority: 7]
- [ ] search_predictive  — type 2 prefixes; capture suggestion panel [priority: 6]
- [ ] collection_filters — open one collection, exercise filters and sort [priority: 6]
- [ ] product_variants   — pick 2 PDPs with variants; capture each selector state [priority: 5]
- [ ] info_pages         — visit shipping, returns, privacy, tos; one screenshot each [priority: 3]
```

The harness plan parser needs the U+2014 dash between the id and the
brief, and a `[priority: N]` tag. The briefs above are only an example
of the form. The canonical briefs are in `prompts/planner.md` and
`prompts/planner_generic.md`, and both prompts emit them verbatim.

**The 14 Fixed areas** (`FIXED_AREAS`, in this order):

| Fixed area           | Priority | What the brief asks for                                                                                  |
| -------------------- | -------- | -------------------------------------------------------------------------------------------------------- |
| `homepage_sections`  | 9        | Every section below the hero; fill the `shop` block (descriptor, category, currency code, tone).         |
| `header_navigation`  | 8        | Header rows, sticky behavior, the department menu and its levels (`departments`), flyouts, header icons. |
| `cart_drawer`        | 8        | Add one product; the cart surface (drawer, page or side sheet): empty, filled, quantity change, remove.  |
| `product_variants`   | 7        | Two product pages, one with more than one variant: gallery, variant selectors, quantity stepper.         |
| `product_reviews`    | 6        | The review block of a product page (`product.has_rating_histogram`, `product.review_filters`); skip all-reviews pages behind a sign-in. |
| `related_products`   | 5        | Each related-product block of two product pages; their kinds in `product.related_product_types`.         |
| `collection_filters` | 7        | A collection, department or category landing page, not a search results page: filters, sort, pagination. |
| `search_predictive`  | 6        | Two prefixes in the search box; the suggestion dropdown; no network or API capture.                      |
| `search_results`     | 7        | One submitted query: results layout, facets (`search.facets`), sort (`search.sort`), pagination, empty state. |
| `checkout_flow`      | 6        | Checkout from a filled cart: guest option, shipping, payment, discount input; stop at the first sign-in or payment wall. |
| `account_pages`      | 5        | Only the public sign-in and sign-up entries: their fields and options; never submit them.                |
| `footer`             | 4        | Link groups, legal links, payment icons, social icons.                                                    |
| `info_pages`         | 4        | Shipping, refund, privacy, terms, FAQ, and contact or about when present.                                |
| `floating_widgets`   | 3        | Cookie banner, newsletter popup, chat widget, age gate: presence and behavior.                           |

The ids are stable names, not a claim about how the shop is built.
Every brief uses platform-neutral words, so the same block fits any
storefront: `cart_drawer` covers a cart page or side sheet too. A key
in backticks names the Capabilities that the task fills. The planner
can make a brief more specific, for example with start paths or the
Focus hint, but the brief keeps every rule of its canonical brief.

**Per-task executor obligations** (encoded in the execute prompt and
`AGENTS.md`):

1. Read `plan.md` for the selected task and its inline brief. The
   harness adds the `selected_task_id` control header and the Verifier
   feedback of the earlier attempt.
2. Read `artifact/prefetch/` for context. On a generic site, find the
   pages from the start paths in the brief, the links in `index.html`
   and the `<loc>` entries of `sitemap.xml`.
3. Drive the browser **only** through the Browser tools, and read and
   write files only through `read_file`, `write_file` and `list_dir`,
   which stay inside the run directory. There is no HTTP fetch tool.
4. Capture evidence under `artifact/evidence/<task_id>/`:
   - one `snapshots/NN-<state>.md` (the `snapshot` text) per distinct
     page state,
   - optional `network.jsonl`, only when a request is the evidence
     (e.g. cart updates).
   Screenshots help to read the layout. The runtime keeps them under
   the Iteration directory.
5. Write a markdown section to `artifact/parts/<task_id>.md` with the
   per-element template of `execute.md` (Type, Layout, Content,
   Behavior, Styling, UX Notes), and apply the anonymization rules at
   write time. The `anonymization` verifier scans only this file of the
   selected task. A hit reopens the task at most twice (the count per
   task is kept in `run/checks/anonymization_reopens.json`); the next
   hit blocks the task with a note that names the file.
6. Write a JSON fragment to `artifact/parts/<task_id>.caps.json`
   containing only the capabilities-schema keys this task is
   responsible for.
7. On a generic site, call `record_product_observation` on each product
   page that the task opens, while the page is open (§5.6).
8. On a bot-check page, do not click, type or submit. Mark the task
   `[!]` with the reason "bot check" and end the Iteration (§5.16).
9. Self-check: both part files exist, the caps file is one JSON
   object, at least one snapshot is saved, and the text has no store,
   brand or product names and no verbatim page copy.
10. Mark the task `[x]` (or `[!]` with the reason after a `;` in the
    brief) before exiting. Change only the line of the selected task.

### 5.8 Prompts and AGENTS.md

Nine caller-owned files live under
`packages/shop-arena/src/explore/prompts/`. They are plain Markdown with
`{{NAME}}` placeholders, not a template language:

- `agents.md` - the project constitution (`AGENTS.md` of the run):
  anonymization and observed-facts rules, Browser tool use, file-write
  conventions, the Capabilities schema (`{{CAPABILITIES_SCHEMA}}`) and
  the Product observation schema (`{{PRODUCT_OBSERVATION_SCHEMA}}`),
  both rendered as JSON Schema at run time.
- `planner.md` - the planner prompt on a Shopify shop: the browse
  budget of 4 `navigate` calls with start pages from
  `collections.json` and `products.json`, the 14 Fixed areas verbatim,
  shop-specific tasks, omitted areas and the shape of `plan.md`.
- `planner_generic.md` - the planner prompt on a generic site. It is a
  full copy of `planner.md` with its title and its browse section
  rewritten: the planner picks start URLs from the homepage links and
  the sitemap, on the same origin only, and writes them as paths.
- `planner_focus.md` - the Focus hint, added after either planner
  prompt when the run has a focus, with `{{FOCUS}}` replaced (§5.14).
- `execute.md` - instructions for one task Iteration on a Shopify shop.
  References `AGENTS.md` for shared conventions.
- `execute_generic.md` - the executor prompt on a generic site. It is
  `execute.md` plus the start pages of a generic site and the rule to
  record each product page that the executor opens with the
  `record_product_observation` tool (§5.6).
- `synthesize_manual.md` - the prompt of the one manual call: keep only
  what the parts show, mark the rest unknown, let no sentence
  contradict `capabilities.json`, and use generic words for the site's
  own names.
- `site_graph.md` and `site_graph_repair.md` - the graph prompt and its
  repair prompt (§5.13).

Prompts are shipped as package files and are not user-templated.

### 5.9 Prefetch

`prefetch(url, outDir, options)` in `src/explore/prefetch.ts` performs a
fixed, small fetch with `fetch`, in this order:

1. `/robots.txt`. A network error stops prefetch (`network_error`). A
   body with a status other than 200 counts as empty. When the rules for
   `User-Agent: *` forbid `/`, prefetch stops (`robots_disallow`).
2. `/`, saved as `index.html`, then the homepage gates (below).
3. `/sitemap.xml`, unless `robots.txt` forbids it for `*`. Prefetch keeps
   at most 1 MiB and marks a longer body as cut. It does not follow the
   child sitemaps of a sitemap index.
4. `/products.json?page=1&limit=250`, the platform probe. While a page
   returns a product list, prefetch reads the next page, until a page
   has fewer than 250 products or 200 pages are read. The pages are
   merged into one `products.json`.
5. The Platform path: `shopify` when the homepage has a Shopify marker
   (`cdn.shopify.com`, `myshopify.com`, `Shopify.theme`,
   `shopify-section`) or the probe returned a product list, else
   `generic`.
6. On the Shopify path only, this fixed plan:

```
/collections.json?limit=50                        -> collections.json
/search/suggest.json?q=a&resources[type]=product  -> search_suggest.json
/cart.js                                          -> cart.js
/cart                                             -> cart.html
/search                                           -> search.html
/policies/refund-policy                           -> policies/refund-policy.html
/policies/privacy-policy                          -> policies/privacy-policy.html
/policies/terms-of-service                        -> policies/terms-of-service.html
/policies/shipping-policy                         -> policies/shipping-policy.html
/pages/about, /pages/contact, /pages/faq          -> pages/<name>.html
```

7. `prefetch.json`: `base_url`, `platform`, `user_agent`, `started_at`,
   `finished_at`, and one entry for each request with its status,
   content type, size, saved file or error.

This is intentionally bounded. It captures *enough* to seed the
planner, not the whole shop. (The legacy `shop-snap` crawler is
broader and slower; we deliberately do not adopt it here, §6 F.)

**Homepage gates**, in this order. Each one throws
`ShopUnreachableError` with a `reason` before any browser starts:

1. A network error: `network_error`.
2. A bot check of the site: a captcha marker, an interstitial marker,
   or a rate-limit marker on a page served with HTTP 503: `bot_check`.
   This gate comes before the status gate, because the bot-check page
   of a site often comes with HTTP 503.
3. An unknown status or a status of 400 or more (this includes 403,
   429 and 503): `http_status`.
4. A Cloudflare challenge marker: `cloudflare_challenge`. Because the
   status gate comes first, a challenge page served with 403 or 503
   stops with `http_status` (§8.2).

The gates are the same on both paths. The marker lists are in
`src/explore/bot-check.ts` (§5.16).

Other behavior:

- **Rate limit.** ≥ 500 ms between requests (`rateLimitMs`).
- **Timeout.** 30 s for each request.
- **User-Agent.** `ShopExplore/0.1.0 (+https://github.com/...)`.
- Output is written verbatim, next to `prefetch.json`.

Prefetch is the only HTTP client code in Storefront exploration. The
agents do all further browsing through the Browser tools. The new
browser of each Iteration opens `/`, and it reads `/cart.js` only when
the prefetched `cart.js` parses as a cart (§3).

### 5.10 Merge and synthesis

After the harness loop returns, these steps run with no further harness
involvement:

1. **Capabilities merge** (`merge`, deterministic). Read every
   `parts/*.caps.json`, deep-merge into one `capabilities.json`,
   validate against the 0.3 schema. Conflicts → `manifest.json`.
2. **Stats** (`merge`, deterministic). On a Shopify shop, compute
   `stats.json` from `prefetch/products.json`,
   `prefetch/collections.json` and `capabilities.json`. On a generic
   site, compute it from the Product observation fragments and
   `capabilities.json` (§5.6).
3. **Manifest** (`merge`, deterministic). Write `manifest.json`:

   ```
   { run_id, domain, runtime, model, platform, focus, harness_status,
     iters: { plan, exec }, plan_tasks_total, plan_tasks_done,
     plan_tasks_blocked, omitted_areas: [{ area, reason }],
     capability_conflicts, coverage_gaps, fixed_area_gaps: [{ area, reason }],
     stop: { reason, iteration, blocked_tasks } | null, merged_at,
     paths: { manual, capabilities, stats, manifest, site_graph, prefetch, run } }
   ```

   - `harness_status`, `iters` and `stop` come from `explore.json`. The
     task counts, `coverage_gaps` and `fixed_area_gaps` come from the
     Plan tasks in the harness `run.json` when the run ended, not from
     `plan.md`. `omitted_areas` comes from `plan.md`.
   - A `fixed_area_gaps` reason is `not in the plan`,
     `not started when the run ended`, `in progress when the run ended`,
     or `blocked: <reason>`, where the reason is the text that the
     executor added after the planned brief.
   - `coverage_gaps` holds only the areas that prefetch evidenced. On a
     generic site, prefetch evidences only `homepage_sections`,
     `header_navigation` and `footer` (from `index.html`), so the
     unfinished areas of a generic run are in `fixed_area_gaps`.
   - `stop.blocked_tasks` lists every Plan task that is blocked when the
     run ends, not only the tasks that met a bot check.
4. **Manual prose** (`synthesize`, one LLM call, no browsing).
   Concatenate `parts/*.md` and `capabilities.json`, send them with
   `synthesize_manual.md` to `LlmClient.complete` with the model of the
   run. Then the final Anonymization scan (§5.15) checks the reply,
   `capabilities.json` and `stats.json`. Only a clean scan writes
   `manual.md`.
5. **Site state graph** (`graph`, §5.13).

Synthesis failure modes (loud, no silent fallback). Each one fails its
step with `StepFailedError`, and the CLI exits 1:

- A fragment that breaks the Capabilities schema, or an invalid merged
  document → `CapabilitiesValidationError`; merge writes no
  `capabilities.json`, `stats.json` or `manifest.json`, and no
  `manual.md` is emitted. A Product observation fragment that breaks its
  schema fails merge too.
- Manual LLM call empty / < 200 chars → `ManualRenderError`, no
  `manual.md` emitted. (`manifest.json` is already written by merge.)
  An early Python revision silently concatenated `parts/*.md` and set
  `manifest.json:manual_fallback=true`; that path masked LLM-client
  misconfiguration and was removed deliberately.
- Manual LLM call raises (network error, timeout) → no `manual.md`
  emitted.
- The final scan finds a leak → `AnonymizationLeakError`, no
  `manual.md` emitted.

### 5.11 CLI surface

```
shopgym explore <url> [--out <dir>] [--model <provider/id>]
                      [--brand-term <word>]... [--max-iters <n>]
                      [--timeout <ms>] [--from <step>]
                      [--force-resume] [--focus <text>]
```

- `--from prefetch|explore|merge|synthesize|graph` forces that step and
  every step after it. `--from merge` and `--from graph` send no site
  traffic when the earlier steps are up to date (§5.13).
- `--brand-term` is repeatable. `--focus` must not be blank.
- The progress lines go to stderr. The last line of stdout is the path
  of `manual.md`. The log line at the end gives the final status and,
  for a stopped run, the stop reason and Iteration.
- Exit code: 0 when the harness run is `completed` or `stopped`; 1 for
  any other final status and for any error.
- The CLI reads the model keys with the repository credentials loader.

Library equivalent:

```ts
import { loadCredentials } from '@shop-gym/core';
import { exploreStorefront } from '@shop-gym/shop-arena/explore';

const result = await exploreStorefront({
  url: 'https://shop.example',
  credentials: loadCredentials(process.cwd(), process.env),
  focus: 'Video Games',
  brandTerms: ['Zephyr', 'Nova Pass'],
});
console.log(result.manualPath, result.finalStatus, result.stop);
```

### 5.12 Module layout

```
packages/shop-arena/src/explore/
├── index.ts              # public re-exports (§8.1)
├── pipeline.ts           # exploreStorefront, the five steps, manifest, Caller stop
├── prefetch.ts           # prefetch, the gates, the Platform path, readPlatform
├── bot-check.ts          # Cloudflare, captcha, interstitial and rate-limit markers
├── browser.ts            # IterationBrowser: a new browser for each Iteration,
│                         #   start_state.json, snapshot tool, bot-check notice
│                         #   and refusal, Navigation cap
├── files.ts              # run-dir-scoped read_file, write_file, list_dir
├── capabilities.ts       # Capabilities 0.3 schema, parseCapabilities, mergeFragments
├── observations.ts       # Product observation schema, tool, Verifier, reader
├── stats.ts              # computeStats (catalog), computeObservedStats (sample)
├── coverage.ts           # evidencedAreas, coverageGaps, FIXED_AREAS, fixedAreaGaps
├── anonymization.ts      # brandTokens, leakScanner, Verifier, publishedLeaks
├── synthesize.ts         # renderManual (the one manual call)
├── graph.ts              # renderSiteGraph (§5.13)
├── trajectory-digest.ts  # Trajectory digest of an executor Iteration (§5.13)
├── testing.ts            # fixture storefronts for the tests
└── prompts/              # §5.8
```

The CLI command is `packages/cli/src/commands/explore.ts`.

Tests are co-located `*.test.ts` files and exercise:

- `prefetch.test.ts`: the gates, platform detection, the generic path,
  `robots.txt` and the sitemap, against local HTTP servers.
- `capabilities.test.ts`: schema round trip, 0.2 documents, merge edge
  cases.
- `coverage.test.ts`: coverage gaps and Fixed area gaps.
- `anonymization.test.ts`: brand tokens, Brand terms, the scanner, the
  final scan, the Verifier and its reopen cap.
- `browser.test.ts` and `files.test.ts`: the start state, the snapshot
  tool, and the file tools that stay in the run directory.
- `pipeline.test.ts`: `exploreStorefront` end to end with `FakeRuntime`
  scripts against a Shopify fixture and a generic fixture with fake
  brand names: steps and resume, the Fixed areas, Product observations
  and stats, the Focus hint, bot checks and the Navigation cap, Brand
  terms and the final scan, and the graph step.

### 5.13 Site state graph

The `graph` step writes `site_graph.json`, the **Site state graph** of
the storefront. A Shop Manual tells what each page looks like and what
its sections do. The graph tells how a shopper moves through the
storefront: which action on which page opens which page or overlay.
The graph is abstract, like a UX prototype. It has one state for each
page type and URL shape, not one for each page that the executors
opened. It has no locators, element ids, product ids or site text.

**Place in the pipeline.** The steps are
`prefetch | explore | merge | synthesize | graph`. The step reads
`capabilities.json`, so the runner puts it after `merge`. `synthesize`
and `graph` are two branches after `merge`: `graph` does not read
`manual.md`, and `synthesize` does not read the graph. So:

- `--from graph` forces only the graph step. It does not browse, and
  it does not write `manual.md` again. But the runner still runs each
  earlier step whose inputs changed, and the input fingerprints of
  `runPipeline` hold absolute paths. When a run must send no site
  traffic, use the same output path as the earlier runs, and check
  that each record in `.pipeline/` matches its inputs first.
- `--from merge` runs the graph step again: merge writes
  `manifest.json` again with a new `merged_at`, and the manifest is an
  input of the graph step.
- The runner skips a complete graph step on a later call with the same
  inputs. The inputs are `capabilities.json`, `manifest.json`,
  `brand_terms.json`, `seed/prefetch/` and `run/plan.md`. The fragments
  and the trajectories are not inputs. Only the explore step writes the
  trajectories, and the merge after it makes the graph stale. After a
  change to a fragment with no merge, use `--from graph` or
  `--from merge`.

**Prompt inputs.** The prompt is a plain Markdown file,
`prompts/site_graph.md`, with `{{NAME}}` placeholders. The step fills
them in one pass. The closed lists come from `@shop-gym/core`. The
prompt gets three inputs:

- **Fragments.** A finished fragment is the `parts/<task_id>.md` of a
  Plan task that `plan.md` marks done. `plan.md` decides, so a fragment
  written outside the harness counts when its task is done. For each
  finished fragment, the prompt gets one `<part task="<id>">` block
  that holds the fragment, but not its Styling lines or their wrapped
  lines. A wrapped line has more indent than its Styling bullet. The
  Styling lines tell how the storefront looks, not how a shopper moves
  through it. The other lines can name paths and states that no
  Behavior line names, for example a register path in a Layout line.
- **Trajectory digest.** After each fragment come the
  `<actions task="<id>" iteration="<id>" start="<path>">` blocks of the
  executor Iterations that selected its Plan task, in run order. Each
  line is `<action> -> <path after the action>`:
  - Only `navigate`, `back`, `click`, `hover`, `select`, `type` and
    `press` give a line. Snapshot, wait, scroll, screenshot, evaluate,
    finish and file tool calls give no line.
  - A ref becomes the role and accessible name of its element. The name
    comes from the newest earlier snapshot that holds the ref. A ref
    that no snapshot showed is `unknown element`.
  - `type` shows the element. It adds `and submit` when the call
    submitted. It never shows the text. `select` shows no value.
    `press` shows the key.
  - The path has no scheme and no host. Each query value is `{value}`,
    and the step drops the fragment identifier. `(path changed)` marks
    an action that went to another path. `(failed)` marks an action
    that failed or got no result.
  - The `start` path comes from the `start_state.json` of the
    Iteration. A run from before start states shows `unknown path`.
  - Each `source` must name a finished fragment. So the step leaves
    out the Iterations of Plan tasks that are not done. A Plan task with
    no Iteration has only its fragment, for example when its fragment
    was written outside the harness.
- **Capabilities.** The merged `capabilities.json`. For example, it
  tells the LLM that the cart is a drawer.

**The call.** The step makes one `LlmClient.complete` call with the
model of the run. The reply is one JSON object, bare or in one fenced
block. When the reply fails a check, the step logs the problems and
makes one repair call. A reply fails a check when it is not one JSON
object, when it breaks the schema or a graph rule, or when a `source`
names no finished fragment. `LlmClient.complete` takes one prompt, so
the repair prompt is the graph prompt, then
`prompts/site_graph_repair.md` with the reply and the list of problems.
The repair reply gets the same checks. There is no second repair.

**Prompt rules.** Some rules of the prompt have no check in code:

- One page type and one path make one page state. A query key goes in
  a URL pattern only when the page needs it to show its content, such
  as a search query or a category id. A key whose value selects the
  item that the page shows stays, also when its name is short or not
  clear. A path segment that changes from page to page, such as a
  category name, is a placeholder, also when the inputs show only one
  such page. Two URL shapes that open the same kind of page, such as a
  path with and with no name segment, make one state, with the shape
  that most action lines show.
- An overlay covers a part of the page. A region that the page makes
  room for, such as a docked rail, is part of the page, and each of its
  controls gets one transition from one page that shows it. A control
  that only selects a value for its page, such as a sort, is one
  `update_in_place` transition, with no overlay for its list.
- An action line with no `(path changed)` mark stays on its state, or
  opens an overlay on it. A filter, sort, page or variant change is
  `update_in_place`, also when the URL loads again. `navigate` goes to
  another page: another state, or another page of the same state.
- The header and the footer show on every page. Their overlays list
  every page state as a host page, and each of their controls gets one
  transition from `home`, not one from each page.
- `from` is the state that shows the control.
- A behavior that a fragment calls unknown gives no transition.
- A way to close an overlay that a fragment shows, such as a close
  button in a Layout line, gives a `close_overlay` transition. A close
  that a fragment calls unknown gives none.
- A transition has a trigger that a fragment or the actions show. The
  `load` trigger is for a change that the site makes when a page loads,
  such as an overlay that shows with no shopper action. When no trigger
  of the list fits the input, such as a scroll, there is no transition.
  A state that then has no transition is not in the graph.

**Schema.** `@shop-gym/core` owns the schema, the closed lists
(`PAGE_TYPES`, `OVERLAY_KINDS`, `TRANSITION_TRIGGERS`,
`TRANSITION_EFFECTS`) and `parseSiteGraph`. So ShopArena writes the
file and later readers read it with one definition. All ids and names
are snake_case.

```ts
type SiteGraph = {
  version: '0.1';
  states: State[];
  transitions: Transition[];
};

type State =
  | { id: string; kind: 'page'; page_type: PageType; url_pattern: string }
  | {
      id: string;
      kind: 'overlay';
      overlay: 'modal' | 'side_sheet' | 'popover' | 'dropdown' | 'flyout';
      on: string[]; // ids of the page states that the overlay opens on
    };

type Transition = {
  from: string;
  to: string;
  trigger: 'click' | 'hover' | 'type' | 'submit' | 'key' | 'load'; // 'load': no shopper action
  action: string; // action kind, for example 'open_result', 'add_to_cart'
  effect: 'navigate' | 'open_overlay' | 'swap_overlay' | 'close_overlay' | 'update_in_place';
  params?: string[]; // for example ['query']
  needs?: string[]; // for example ['variant']
  source: string; // the Plan task whose fragment or Trajectory digest shows it
};
```

`PageType` is `home | collection | product | search | cart | page |
policy | login | register | account | addresses | order_detail |
checkout | checkout_confirmation | other`.

`parseSiteGraph` first checks the closed schema. Only when the schema
passes does it check the graph rules. It throws
`SiteGraphValidationError`, which lists every problem of the first
check that fails.

1. The closed schema:
   - An unknown field or list value fails.
   - A URL pattern starts with one `/` and has no `://`, so it is not
     an absolute URL and holds none. It uses only `{name}`
     placeholders, and it has a placeholder for each query value.
   - An overlay has one or more host pages.
   - `params` and `needs` have no repeated item.
2. The graph rules:
   - State ids are unique. Each `from` and `to` names a state, and each
     host page names a page state.
   - No two page states have one URL pattern. Two patterns that differ
     only in their placeholder names count as one.
   - No two page states of one page type have one path, the part of the
     pattern before `?`. Two states with one URL pattern give only the
     problem of the rule before.
   - Each state is the `from` or the `to` of one or more transitions.
   - A `navigate` transition ends on a page.
   - An `open_overlay` transition ends on an overlay and starts on one
     of its host pages.
   - A `swap_overlay` transition goes from an overlay to a different
     overlay.
   - A `close_overlay` transition starts on an overlay and ends on one
     of its host pages.
   - An `update_in_place` transition has the same `from` and `to`.
   - No two transitions have the same `from`, `action` and `to`.

The step adds one rule that core cannot check: each `source` names a
finished fragment.

**Anonymization.** Before it writes the file, the step scans the graph
text with the same scanner as the final scan of synthesize. The scanner
matches the host, the brand tokens of the host name and of the
prefetched homepage, the Brand terms and email addresses. In a `.json`
file the scan reads only the values. It has no general pattern for
absolute URLs, but the schema keeps them out of the graph: ids, actions,
params and needs are snake_case, and a URL pattern has no `://`. The
prompt forbids site text: button labels, headings, product names and
ids.

**Failure.** The step fails with `StepFailedError` for `graph`, and
writes no `site_graph.json`, in three cases:

- The repair reply is not one JSON object (`SiteGraphReplyError`).
- The repair reply breaks a check (`SiteGraphValidationError`).
- The scan finds a leak (`AnonymizationLeakError`). A leak gets no
  repair call.

**Output.** `site_graph.json` is a published file at `<run_id>/`, next
to `capabilities.json`. Merge writes `paths.site_graph` into
`manifest.json`, as it writes `paths.manual` before synthesize runs.
So a manifest from before the graph step does not name the file until
the next merge. `ExploreResult` names the path as `siteGraphPath`. The
CLI output does not change: its last line is still the manual path. The
step logs one line with the counts of pages, overlays and transitions.

**Changes to the first graph design.** Decision 12 of the Source
bundles spec review
(`packages/reports/pages/2026-11-03-source-bundles-review.html`) gave a
first shape of the graph. Its states had `id`, `page_type` and
`url_pattern`. Its transitions had `from`, `to`, `action`, `params` and
`needs`. It also had a `weights` block. The graph that shipped changes
that shape:

- A state has a kind. An overlay is a state of its own, with a kind
  from a closed list. So a cart drawer or a filter sheet is a step in
  a flow.
- An overlay names one or more host pages, not one, because a header
  widget opens on every page.
- A transition adds `trigger`, `effect` and `source`.
- Two graph rules are new: one page state for each page type and path,
  and one transition for each `from`, `action` and `to`.
- The page types of two words are snake_case: `order_detail`,
  `checkout_confirmation`.
- The graph has a `version`.
- The graph has no `weights` block (see §8.3).

**Review of the first graph (2026-11-12).** The first graph is of the
Video Games Shop Manual: 15 pages, 9 overlays and 78 transitions, from
a `--from merge` run and a `--from graph` run with no site traffic. The
review page is
`packages/reports/pages/2026-11-12-video-games-site-graph.html`. The
graph is accepted. The review keeps these results:

- The graph follows the rules in three places that can look wrong:
  - An overlay whose close or accept a fragment calls unknown has no
    transition for it. So the add-on sheet after add to cart has only
    its decline transition, and an overlay can have no exit.
  - A step with no path of its own in the inputs is part of the state
    that it shows as. So the add-to-cart confirmation page is part of
    the cart state.
  - A variant pick that loads another product path is `navigate`, a
    loop on the product state.
- Two limits stayed open after the review:
  - The closed trigger list had no trigger for an overlay that shows
    with no shopper action, such as a sign-in tooltip on page load. The
    model gave such an overlay a trigger that no fragment shows. The
    `load` trigger now covers this case. The graph `version` stays
    `0.1`, because the change only adds a list value and no code reads
    the graph yet.
  - The model broke some prompt rules that no check catches. A
    category name stayed as text in a path, and a category page lost
    its id key. One sort control showed as a page control and also as
    an overlay. A docked rail showed as a popover that a click opens. A
    menu that a fragment says closes had no close transition. Sharper
    prompt rules now cover these cases.

**Reruns after the follow-ups (2026-11-12).** Two `--from graph` runs
with the `load` trigger and the sharper prompt rules sent no site
traffic. The first run used the first wording of the new rules. After
it, the code review changed the wording and added two rules: a state
that then has no transition is not in the graph, and two URL shapes of
one page get the shape that most action lines show. The second run
used the final prompt. The runs keep these results:

- The first run gave 16 pages, 8 overlays and 78 transitions. Its first
  reply had two repeated transitions, and the repair reply passed all
  checks.
  - It fixed four cases of the review and the trigger limit. The
    category page is one state, with its id key and with no category
    name in its path. Each sort control is one `update_in_place`
    transition. The sign-in tooltip opens with `load`. The menu has a
    close transition.
  - The mini cart was still a popover. Two fragments tell about it in
    different ways: one calls it a small cart popover on the add
    confirmation page, and one calls it a docked rail that does not
    cover the page. The graph followed the first fragment.
  - It broke two rules that the graph before kept or that the review
    did not name. It had a checkout page that no fragment shows: the
    checkout fragment says that the cart goes to a sign-in gate, and
    that no checkout page shows before the gate. A help topic page lost
    its topic id key and the file extension of its path.
- The second run gave 11 pages, 7 overlays and 55 transitions, and its
  first reply passed all checks.
  - It fixes all five cases of the review and the trigger limit. The
    category page and the sort control are as in the first run, and
    the sign-in tooltip opens with `load`. The menu closes to `home`
    with the Escape key that the actions show. The mini cart is not an
    overlay.
  - The two breaks of the first run are gone. The cart goes to the
    sign-in gate, and the help topic page keeps its file extension and
    a topic key.
  - It breaks other rules. It leaves out the brand store pages that the
    homepage fragment names, and the go-to-cart link of the docked mini
    cart. It writes the help topic key in snake_case, not with the name
    that the actions show.
- So the sharper prompt rules fix the cases that they name, but the
  model still breaks some rules, and the breaks change from run to
  run. A reviewer must still read each graph.

### 5.14 Focus hint

A large site, such as a marketplace, has many departments. The `focus`
option (`--focus <text>`, for example `--focus "Video Games"`) keeps a
run in one part of it.

- The explore step adds `prompts/planner_focus.md` after the planner
  prompt of either platform, and replaces `{{FOCUS}}` with the focus
  text. The composition is plain text concatenation. With no focus, the
  planner prompt does not change.
- The hint tells the planner to pick its listing pages, product pages
  and search queries inside the focus, for its own browse and for the
  briefs. The browse budget does not change.
- The planner keeps every Fixed area, also the site-wide ones (header,
  footer, cart, checkout entry, account entries, info pages, floating
  widgets). A task can open a page outside the focus when it needs that
  page.
- The executors see only their brief, so the planner writes the focus
  into each brief that opens a listing page, a product page or a
  search. The executor prompts do not get the focus.
- If no part of the site matches the focus, the planner plans as if
  there were no focus and says so in the plan summary.
- The code does not block navigation outside the focus. The focus is a
  hint, not a filter.
- The explore step writes `focus.json` (`{ "focus": <text or null> }`)
  before the harness runs. A later call on the same `outDir` with a
  different focus, or with no focus, fails before any step runs,
  because a resumed harness run keeps the plan of its first planner.
- `manifest.json:focus` records the focus, or `null`. A focus names a
  department, not a brand, so it can be published.
- The CLI refuses a blank `--focus`.

### 5.15 Brand terms and the final scan

**Brand tokens.** `brandTokens(hostname, html)` takes its tokens from:

- the hostname labels of 4 or more characters, other than `www` and the
  top-level label;
- the brand segment of the homepage `<title>`. The title splits at a
  `|`, `:`, `·` or dash that has spaces on both sides, and after a `.`,
  `!` or `?` that a space follows. The brand segment is the segment whose
  compact text (lowercase letters and digits only) matches a hostname
  label, alone or joined with the labels after it. When no segment
  matches, every segment counts, because a false alarm is safer than a
  missed brand;
- `og:site_name`.

Words shorter than 3 characters and stop words (such as `the`, `shop`,
`store`, `home`) give no token. So the words of a tagline, such as
"Spend less. Shop more.", do not become brand tokens when a segment
names the brand.

**Brand terms.** The repeatable `--brand-term <word>` (option
`brandTerms`) adds words or phrases that the title does not name, such
as sub-brands: for example `--brand-term Zephyr --brand-term "Nova
Pass"`. A term matches as a whole word. A term of more than one word
matches as a phrase: its words in order, with only spaces or
punctuation between them, so "Nova Pass" does not match "nova" alone. A
term with no letter or digit fails the call. The run keeps the terms in
`<outDir>/brand_terms.json`, which is never published and which Shop
generation does not read. A later call with no terms uses the stored
terms again; a call with terms replaces them.

**One scanner, three uses.** `leakScanner` matches, line by line, the
host (with or without `www.`, so also every absolute URL on the host),
email addresses, the brand tokens and the Brand terms. It is used in
three places:

1. The `anonymization` Verifier, after each executor Iteration, on the
   `parts/<task_id>.md` of the selected task only (§5.7).
2. The final scan of the `synthesize` step (`publishedLeaks`), on
   `manual.md`, `capabilities.json` and `stats.json`. In a `.json` file
   the scan reads only the values, because the keys are schema names.
   A hit fails the step with a `StepFailedError` whose cause is an
   `AnonymizationLeakError` that lists each `file:line`, and `manual.md`
   is not written. The final scan catches
   a leak that a blocked task left behind or that synthesis wrote.
3. The same scan in the `graph` step, on `site_graph.json` (§5.13).

`manifest.json` is not scanned, because it records the `domain` by
design. A leak gets no repair call and no rewrite: the person who runs
exploration fixes the part or adds a Brand term, then runs
`--from synthesize` or `--from graph`.

### 5.16 Bot checks and the Navigation cap

Storefront exploration never tries to pass a bot check.
`src/explore/bot-check.ts` finds one by HTML markers:

| Kind                 | Markers                                                         |
| -------------------- | --------------------------------------------------------------- |
| Cloudflare challenge | element names, a token prefix and text of the challenge page    |
| Captcha page         | the two prompts and the form path of a marketplace captcha page |
| Interstitial page    | the heading of a page with one button to go on to the shop      |
| Rate-limit page      | the page title; it counts only on a page served with HTTP 503   |

The lists hold page text and URL paths only, with no domain. A
rate-limit title can also be on a normal error page, so it counts only
with HTTP 503.

**In prefetch**, a bot-check homepage stops the run before any browser
starts (§5.9).

**In a run**, `IterationBrowser` (`src/explore/browser.ts`) wraps the
Browser tools:

- After each tool call that loaded a document (any tool, not only
  `navigate`), it reads the page HTML and the HTTP status of the
  main-frame document, and looks for a marker. It checks the start page
  of an Iteration at the first tool call.
- On a bot check, the tool result gets a notice: the page is a bot
  check, not a page of the shop; do not try to pass it; mark the Plan
  task `[!]` with the reason "bot check" after a `;` in its brief, and
  end the Iteration. The notice works for the planner too: the planner
  does not open the page again and plans only from the pages that it
  could read.
- Before each `click`, `type`, `select` and `press`, it reads the page
  again. On a bot-check page it refuses the action, and the result is
  the notice. `navigate` and `back` stay allowed, so the agent can leave
  the page.
- The planner and executor prompts say the same rule. A cookie banner,
  an age gate or a popup over a shop page is not a bot check.

**The bot-check stop.** After each Iteration, the harness
`onIterationEnd` hook counts the Iterations in a row that came to a
bot-check page. The planner Iteration counts. At 2 in a row, the
explore step returns a Caller stop with the reason `bot_check`.

**The Navigation cap.** `NAVIGATION_CAP` is 200 `navigate` calls in
one call of the explore step, over all its Iterations. The start page
of an Iteration does not count. At the cap, `navigate` refuses with a
note, and the run stops after that Iteration with the reason
`navigation_cap`. The cap is a constant, not an option. A resume starts
a new count. When both stops apply, the reason is `bot_check`.

**A stopped run.** The stop acts only between Iterations and never cuts
an Agent run in the middle. The harness ends the run with the final
status `stopped` (harness spec, §5.10 Caller stop), so the run can
resume later. The harness ignores a stop after an Iteration that failed
the run. Then:

- `explore.json` records `stop: { reason, iteration }`, and
  `ExploreResult.stop` returns it.
- Merge, synthesize and graph run on the finished parts. Each Fixed
  area that did not end done is in `fixed_area_gaps` with its reason.
- `manifest.json:stop` is `{ reason, iteration, blocked_tasks }`, or
  `null` when the run did not stop early.
- `shopgym explore` logs the reason and the Iteration, and exits 0,
  because the run published a manual. No person needs to act during a
  run.

---

## 6. Alternatives

**A. Keep the per-page-type fixed agent layout** (legacy
`build_shop_manual.py`). Rejected: doesn't scale to varied storefronts
(some have a cart drawer, some don't; some have predictive search, some
don't) and fights the planner-then-loop design we already have in the
harness. Mode-collapses to a static taxonomy.

**B. Single-pass agent with one big prompt.** Rejected: long-context
mega-prompts degrade and we lose per-iteration trajectory boundaries.
The harness paper's argument applies directly here.

**C. Synthesis-as-an-extra-task** instead of a deterministic post-loop
step. Rejected: synthesis does no browsing; making it a harness task
forces the executor prompt to handle a degenerate "no-tools" case and
muddies the executor contract.

**D. LLM-emitted capabilities.json directly** (no per-task fragments).
Rejected for v0.1: less robust than schema-validated fragments. May
revisit if structured-output guarantees from the underlying LLM mature.

**E. Deterministic anonymization scrubber** (regex + brand block-list)
that rewrites leaks before publishing. Partly taken (2026-11-05): the
final scan (§5.15) is a hard gate with the same markers as the
Verifier, and the Brand terms are a block list for each run. The scan
fails the run; it does not rewrite text. A scrubber that rewrites is
still deferred (§8.3).

**F. Use the full `shop-snap` crawler for prefetch.** Rejected: it's
designed for byte-perfect snapshots (assets, CSS, JS, ≤ 1000 pages) and
takes minutes. We need < 30 s of seed data, not a snapshot.

**G. Pass bot checks** (captcha solving, proxies, user agent rotation,
stealth browsers). Rejected: exploration reads only what a site shows
to a polite visitor. A bot check blocks its Plan task, and two in a row
stop the run (§5.16).

**H. A focus filter** that blocks navigation outside the focus.
Rejected: the site-wide Fixed areas (header, cart, checkout entry,
account entries) need pages outside the focus. The focus is a hint in
the plan (§5.14).

**I. A CLI option for the Navigation cap.** Not taken: the cap is a
fixed constant, and the planner keeps its fixed limit of 4 navigations.

---

## 7. Execution Table

| Item                                                                                      | Status                                                         | Date       |
| ----------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ---------- |
| M1 to M5: v0.1 in Python (prefetch, schemas, stats, prompts, harness wiring, synthesis, replay tests, `shop-explore` CLI) | Done; removed at the v1.1 cutover                              | -          |
| v1.1 TypeScript port on `runPipeline`, `runPlanExecLoop` and the Browser tools; Capabilities 0.2 | Done                                                           | 2026-09-30 |
| `shopgym explore` CLI (v1.1 M10)                                                          | Done                                                           | -          |
| Fresh browser per Iteration; anonymization scope and reopen cap; coverage counts only done tasks | Done                                                           | 2026-11-05 |
| Platform paths (§5.9)                                                                     | Done                                                           | 2026-11-05 |
| Marketplace Plan tasks, platform-neutral briefs, `fixed_area_gaps` (§5.7)                 | Done                                                           | 2026-11-05 |
| Capabilities 0.3, through the Shop generation manual merge (§5.5)                         | Done                                                           | 2026-11-05 |
| Catalog statistics from an observed sample (§5.6)                                         | Done                                                           | 2026-11-05 |
| Brand segment, Brand terms and the final scan (§5.15)                                     | Done                                                           | 2026-11-05 |
| Focus hint (§5.14)                                                                        | Done                                                           | 2026-11-05 |
| Harness Caller stop, bot-check stop and Navigation cap (§5.16)                            | Done                                                           | 2026-11-05 |
| First run on a generic site: the Video Games Shop Manual (§8.4)                           | Done; 11 parts written offline; accepted by the user 2026-11-11 | 2026-11-06 |
| Site state graph (§5.13)                                                                  | Done; first graph accepted                                     | 2026-11-12 |
| This spec, updated for the items above                                                    | Done                                                           | 2026-11-12 |
| Findings of the first generic run (§8.2, items 6 to 9)                                    | Open                                                           | -          |

---

## 8. Appendix

### 8.1 Public surface (informative)

Exported from `@shop-gym/shop-arena` and `@shop-gym/shop-arena/explore`:

- **Pipeline** (`pipeline.ts`): `exploreStorefront(options) ->
  ExploreResult`, `EXPLORE_STEPS`, `DEFAULT_MODEL`,
  `DEFAULT_MAX_ITERS`, `DEFAULT_TIMEOUT_MS`, `DEFAULT_OUTPUT_ROOT`,
  `parseModel`, `runId`; types `ExploreOptions`, `ExploreResult`,
  `ExploreOutcome`, `ExploreStep`, `ExploreStop`, `ExploreStopReason`
  (`bot_check` | `navigation_cap`), `Manifest`.
- **Prefetch** (`prefetch.ts`): `prefetch`, `normalizeBase`,
  `robotsDisallowsRoot`, `ShopUnreachableError`; types `Platform`,
  `PrefetchEntry`, `PrefetchOptions`, `PrefetchReport`,
  `UnreachableReason` (`network_error` | `robots_disallow` |
  `http_status` | `cloudflare_challenge` | `bot_check`).
- **Capabilities** (`capabilities.ts`): `capabilitiesSchema`,
  `capabilitiesJsonSchema`, `parseCapabilities`, `mergeFragments`,
  `CAPABILITY_KEYS`, `CapabilitiesValidationError`; types
  `Capabilities`, `Conflict`, `MergeResult`.
- **Coverage** (`coverage.ts`): `FIXED_AREAS`, `fixedAreaGaps`,
  `coverageGaps`, `evidencedAreas`, `parseOmittedAreas`; type
  `FixedAreaGap`.
- **Stats** (`stats.ts`): `computeStats`, `computeObservedStats`,
  `STATS_SOURCES`; types `Stats`, `StatsSource`.
- **Product observations** (`observations.ts`):
  `productObservationSchema`, `productObservationJsonSchema`,
  `productObservationTool`, `productObservationVerifier`,
  `readObservations`; type `ProductObservation`.
- **Anonymization** (`anonymization.ts`): `brandTokens`, `leakScanner`,
  `publishedLeaks`, `formatLeaks`, `anonymizationVerifier`,
  `AnonymizationLeakError`; types `Leak`, `LeakScanner`.
- **Synthesis and graph**: `renderManual`, `buildManualPrompt`,
  `concatParts`, `MANUAL_MIN_CHARS`, `ManualRenderError`,
  `SiteGraphReplyError`; `fileTools`.

`bot-check.ts` and `NAVIGATION_CAP` are internal.

### 8.2 Open questions

1. ~~**LLM provider for synthesis.**~~ **Resolved:** synthesis and the
   graph step use the `LlmClient` of the run (default `PiLlmClient`)
   with the model of the run.
2. ~~**Run id collision policy.**~~ **Resolved:** a call on an existing
   `outDir` resumes it: it skips the complete steps and resumes an
   unfinished harness run (§5.2).
3. ~~**Fixture storefronts.**~~ **Resolved:** the tests use hand-written
   local fixture storefronts with fake brand names
   (`src/explore/testing.ts`), not recordings of real shops.
4. **Capabilities schema versioning.** Field-additive only within
   `0.x`; bump to `1.x` for any field rename or removal. 0.2 and 0.3
   were additive.
5. ~~**Stats from prefetch is a sample.** `/products.json?limit=50`
   caps at 50 products; for accurate `products_total` we may need
   pagination. v0.1 reports the sample size and a `truncated: true`
   flag rather than crawling every page.~~ **Resolved (2026-04-25):**
   prefetch paginates `/products.json?page=N&limit=250` until the
   storefront's last (short) page or a safety cap; `Stats.products_total`
   is exact (T6.4). The `products_truncated` flag was removed.
6. **Rules for each path in `robots.txt`.** Prefetch checks `robots.txt`
   only for `/` and `/sitemap.xml`. The executors can open a path, such
   as a cart path, that `robots.txt` forbids for `*`. The team accepted
   this risk for the first generic run; the policy question is open.
7. **Prefetch reason for a Cloudflare challenge.** The status gate comes
   before the Cloudflare gate, so a challenge homepage served with 403
   or 503 stops with `http_status`, not `cloudflare_challenge`. Both
   stop the run. A change of the gate order is a code change.
8. **Findings of the first generic run** (§8.4), still open:
   - Some prose lines tell about the run ("this task", "captured"), not
     about the storefront.
   - `stats.json` writes 0 for an unknown structural count (§5.6).
   - There is no total budget for `read_file` in one Iteration.
   - `shop.currency` can stay `null` when the prices show a currency.
   - The homepage can show blank in a new headless browser. A likely
     cause is the CORS preflight that the extra `x-shopgym-episode`
     header causes on cross-origin requests.
   - All Iteration browsers of a run send the same `x-shopgym-episode`
     id.
9. **Findings of the 2026-11-11 criteria check**, still open:
   - `execute_generic.md` names predictive search as a request that can
     be evidence, but the `search_predictive` brief says "no network or
     API capture".
   - A malformed Product observation fragment fails the merge step, so
     one bad fragment stops the manual.
   - A brand token with letters or digits joined to it, such as
     `Zephyr01`, passes the scan, because a token matches only as a
     whole word.

### 8.3 Future directions (non-blocking)

- **Deterministic anonymization scrubber** (Alternative E) that
  rewrites leaks. Today the final scan only fails the run.
- ~~**Cross-shop manual diff/merge**~~ **Done:** the `manual_merge`
  step of Shop generation (`src/gen/manual_merge`) merges one or more
  Shop Manuals.
- **Mobile viewport pass** as a second planner (currently desktop
  1280×800 only, the `BrowserSession` default).
- **Headed-mode debug runs** through the `headless` option of
  `BrowserSession`. The explore step does not pass it yet.
- **Authenticated flows** (account, wishlists) once we have a
  stable test-account story.
- **Shop Manual input from a recording** made by a person or a
  computer-use agent (user, 2026-11-06). The offline parts of the first
  generic run (§8.4) came from such captures. Not yet specified.
- **Uses of the Site state graph** (§5.13). Shop generation can carry
  the graph into a SandboxShop and add a `weights` block from shopper
  behavior data. A Build loop Verifier can walk each transition. Task
  generation (`docs/specs/shop_guru/task_generation_proposal.md`) can
  list the transitions that its tasks do not reach. Named flows, such
  as search to purchase, can go on top of the transitions.

### 8.4 The first run on a generic site

The first run on a generic site explored a large marketplace with
`--focus "Video Games"` and Brand terms. Its Shop Manual is the
**Video Games Shop Manual**. It is in the gitignored
`outputs/shop_manuals/` folder of the person who ran it, with a
`provenance/README.md` that records how each file was made. No
committed file names the site.

- **Live run (2026-11-05, UTC 2026-11-06, model `openai/gpt-5.5`).** This was the
  second live run; the first one ran before the fixes of 2026-11-05.
  Prefetch took the `generic` path. The planner wrote the 14 Fixed
  areas, and the executors finished 3 of them: `header_navigation`,
  `cart_drawer` and `collection_filters`. The browser found three
  bot-check pages (two interstitial pages and one rate-limit page with
  HTTP 503) at once, and no page action ran on them.
  `product_variants`, `product_reviews` and `search_results` were
  blocked with "bot check". `homepage_sections` was blocked because the
  homepage showed blank in the new headless browser. After the second
  Iteration in a row with a bot check (`exec-0008`), the run stopped
  with the reason `bot_check`. `manifest.json` records
  `harness_status: stopped`, the stop with its 4 blocked tasks, and 11
  `fixed_area_gaps`: the 4 blocked areas and 7 areas that were not
  started.
- **Offline parts (2026-11-06).** The 11 missing parts were written
  from page captures, not by the harness. On 2026-11-05 a browsing
  agent that the user ran saved the pages signed out at 1280×800, and
  the user cleared two human checks by hand. A script turned the saved
  pages into text outlines with no scripts, hidden elements, form
  values, query strings or session ids. Four subagents wrote the parts
  from the outlines with the executor rules and did no browsing. The three Product observation
  fragments were written by hand with the key method of the tool. No
  per-Iteration Verifier ran on these parts; a check with the merge code
  found 0 conflicts and 0 leaks. `plan.md` marks the 11 tasks done.
- **Merge and synthesis (2026-11-06).** A `--from merge` run with no
  site traffic merged the 14 parts with 0 conflicts and wrote a
  `manual.md` of 111,882 characters (12 H2 and 95 H3 sections). The
  final scan passed. `capabilities.json` (0.3) and `stats.json`
  (`observed_sample`, `sample_size` 3) parse with the Shop generation
  schemas, and the manual splits into the 6 Shop generation parts. The
  Site state graph came later (§5.13).
- **Decision (user, 2026-11-11).** The offline-filled manual counts for
  the exit criterion of the first generic run, with its provenance kept
  next to it.
- **Known limits.**
  - `run.json`, `explore.json` and the harness fields of
    `manifest.json` (`harness_status`, the task counts, `stop`,
    `coverage_gaps`, `fixed_area_gaps`) describe only the live harness
    run. Merge takes the task counts from `run.json`, not from
    `plan.md`, so they do not count the offline parts.
  - 7 prose lines tell about the run, not the storefront. All come from
    the 3 parts that the harness wrote.
  - Not captured: single reviews and review sort, checkout after the
    sign-in wall, registration after its entry page, the returns page,
    a true no-results page, carousel paging, hover states, mobile, and
    signed-in states.
