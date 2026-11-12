# ShopExplore (`packages/shop_arena/src/shop_arena/explore`)

Status: **Implemented (`shop_arena.explore` v0.1.0)** · Version: **0.1**
Owners: ShopArena

> A storefront exploration pipeline that produces an anonymized **Shop
> Manual** — a structured, machine- and human-readable description of a
> live storefront's UX, IA, and feature set — so that a sandbox shop can
> later be synthesized from one or more such manuals.

---

## 1. Overview

`shop_arena.explore` ingests one storefront URL and emits a **Shop Manual**: a
small bundle of files (markdown + JSON + raw evidence) that captures the
shop's structure, navigation, and modern e-commerce features (cart,
search, filters, sort, drawers, popups, etc.) in an anonymized form.

Two design choices define the module:

- **Harness-driven exploration.** All browsing happens inside
  `packages/harness` plan-then-exec iterations. The planner agent walks
  the shop briefly and emits a per-shop task list; executor agents work
  one task each, driving the browser through the **playwright skill**
  (CLI). `shop_arena.explore` owns prompts, an `AGENTS.md`, a deterministic
  prefetch step, and a post-loop synthesis step. It owns no
  orchestration, no LLM session management, and no telemetry plumbing —
  the harness owns those.
- **Decoupled output.** A Shop Manual is a standalone artifact keyed by
  domain + run id; it is **not** tied to a sandbox shop. Downstream
  (`shop_arena.gen` SandboxShop builder) consumes one or more Shop Manuals as
  input.

`shop_arena.explore` is the first non-trivial caller of `packages/harness` and
exercises its public surface end-to-end.

---

## 2. Terminology

- **Storefront** — the public, unauthenticated view of an online store at a given base URL.
- **Shop Manual** — the bundle this module emits for one storefront run:
  `manual.md` (prose), `capabilities.json` (structured features),
  `stats.json` (analysis statistics), `site_graph.json` (the Site state
  graph, §5.13), per-task evidence, and a `manifest.json`. See §5.4.
- **Capability** — a structured, schema-validated tag describing one
  feature of the storefront (e.g. `cart.type=drawer`,
  `search.has_predictive=true`, `collection.filters=[size,color,price]`).
- **Prefetch** — a deterministic, no-LLM HTTP fetch of a fixed set of
  shop webpages and JSON endpoints (`/`, `/sitemap.xml`,
  `/products.json`, `/collections.json`, `/search/suggest.json`,
  `/cart.js`, `robots.txt`, policy pages). Output is seeded into the
  harness `run_dir/artifact/prefetch/`.
- **Task brief** — the inline note text following a task id in
  `plan.md` (e.g. `- [ ] product_detail — capture variant selectors and
  gallery on 2 PDPs`). Authored by the planner; read by the executor.
- **Coverage taxonomy** — a fixed list of feature areas the planner is
  expected to consider when emitting tasks (§5.7). The planner *omits*
  areas the prefetch shows are not present.
- **Anonymization** — write-time obfuscation of brand-, store-, and
  product-identifying strings so the manual describes structure and UX
  patterns, not the original shop. v0.1 enforces this only via prompt
  rules; no deterministic post-pass scrubber.
- **Site state graph** - the published file `site_graph.json`. It tells
  how a shopper moves through the storefront: its states are pages and
  overlays, and its transitions are shopper actions from one state to
  another. See §5.13.
- **Trajectory digest** - the browser actions of one executor
  Iteration, one line for each action. The `graph` step gives it to its
  LLM call. It has no refs, hosts, query values or typed text.

---

## 3. Current Status

- `packages/shop_arena/src/shop_arena/explore/` is implemented and
  exposes the `shop-explore` console script plus the library entry
  point `explore(ExploreConfig)`.
- The v0.1.0 pipeline runs deterministic prefetch, a harness-driven
  planner/executor loop, and deterministic synthesis into
  `manual.md`, `capabilities.json`, `stats.json`, and
  `manifest.json`.
- The implementation includes:
  - capability schemas and merge helpers under `explore/capabilities/`;
  - HTTP prefetch under `explore/prefetch/`;
  - planner, executor, `AGENTS.md`, and synthesis prompts under
    `explore/prompts/`;
  - deterministic synthesis and manifest writing under
    `explore/synthesize/`;
  - resume support through the harness resume contract when `--out`
    points at an existing run directory.
- Replay cassettes and tests cover fixture storefronts, capability
  merging, stats, prefetch, synthesis, CLI wiring, and the harness
  integration path. Live runtime smoke and real-LLM synthesis remain
  follow-up work.
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
  `<run_id>/seed/prefetch/`. The CLI binary is scheduled for M10.
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
- Brand segment, brand terms and the final scan (2026-11-05): brand
  tokens come only from the brand segment of the homepage title (the
  segment that matches a hostname label) and from `og:site_name`; when
  no segment matches, every segment counts. A repeatable
  `--brand-term <word>` (option `brandTerms`) adds sub-brands; a term
  of more than one word matches as a phrase. The terms are kept in
  `<run_id>/brand_terms.json`, which Shop generation does not read, and
  the `anonymization` verifier uses them. After synthesis, the final scan
  checks `manual.md`, `capabilities.json` and `stats.json` (JSON values
  only) for brand tokens, brand terms and the host, and fails the
  `synthesize` step before it writes `manual.md`. `manifest.json` is not
  scanned, because it records the `domain` by design.
- Observed facts only (2026-11-05): the shared executor instructions
  (`AGENTS.md`) say to write only what the run saw. A field that the run
  did not see stays `null`, and `false` means that the run saw the
  feature is absent. The synthesis prompt keeps only what the parts
  show, marks what a part did not see as unknown, and lets no sentence
  contradict `capabilities.json`. Both prompts put site-specific lists,
  internal request names and the site's own feature names into generic
  words. These are prompt rules; the final scan matches only the brand
  markers and the host.
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
  `manifest.json:paths.site_graph` names the file. See §5.13.

---

## 4. Desired Status

A self-contained module under `packages/shop_arena/src/shop_arena/explore/`
that, given a storefront URL, runs one harness `plan_exec_loop` against
it and emits a Shop Manual under
`outputs/shop_manuals/<domain>/<run_id>/`.

### 4.1 I/O contract

**Inputs** (CLI or library):

| Input        | Notes                                                                                  |
| ------------ | -------------------------------------------------------------------------------------- |
| `url`        | Public storefront base URL. Required.                                                  |
| `out_dir`    | Defaults to `outputs/shop_manuals/<domain>/<run_id>/`. Must be empty or non-existent.  |
| `runtime`    | `pi` (default) or `claude_code`. Selected via `harness.get_runtime`.                   |
| `max_iters`  | Executor budget; default 12.                                                           |
| `timeout`    | Per-iteration timeout; default 600s.                                                   |

**Outputs** (under `<out_dir>/`):

The output directory **is** the harness `run_dir`. The Shop Manual
itself is the contents of `<out_dir>/artifact/`. See §5.4 for the full
layout.

**Out of scope:**

- Authenticated flows (login, account, wishlist).
- Checkout (cart-to-payment).
- Cross-shop merging / SandboxShop synthesis (separate spec under
  `shop_arena.gen`).
- Sandbox shop generation, asset rewriting, GraphQL mocking.
- Asset downloads beyond what playwright captures opportunistically.
- Deterministic anonymization scrubber (deferred; §6).

### 4.2 Success criteria

- **SC1 — One command.** `shop-explore <url>` produces a complete Shop
  Manual under `outputs/shop_manuals/<domain>/<run_id>/` with no
  additional flags required.
- **SC2 — Schema-valid capabilities.** `capabilities.json` validates
  against the v0.1 schema (§5.5) on a representative set of fixture
  storefronts. Unknown fields are rejected.
- **SC3 — Anonymized.** `manual.md` and `capabilities.json` contain no
  occurrence of the source domain, source store name, or any product
  title from prefetched `products.json`, on the fixture set. Verified by
  a test-only regex scan (the production pipeline does not enforce this
  in v0.1).
- **SC4 — Replayable.** A test harness using `harness.runtimes.replay`
  can drive a recorded `shop_arena.explore` run end-to-end without network
  access.
- **SC5 — Coverage.** On the fixture set, every coverage-taxonomy area
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

---

## 5. Proposal

### 5.1 Architecture

```
              ┌──────────────────────────────────────────────┐
              │                shop_arena.explore                  │
              │  url → out_dir/{manual.md, capabilities.json,│
              │         stats.json, evidence/, …}            │
              └────────────┬───────────────────────┬─────────┘
                           │ owns                  │ owns
                           ▼                       ▼
       ┌────────────────────────┐   ┌─────────────────────────────┐
       │  Prefetch (no LLM)     │   │  Synthesis (post-loop)      │
       │  HTTP + sitemap + JSON │   │  parts → manual + caps +    │
       │  endpoints; aborts on  │   │  stats + manifest           │
       │  bot-block / 4xx/5xx   │   │  (1 LLM call + det. merge)  │
       └───────────┬────────────┘   └────────────▲────────────────┘
                   │ seeds                       │ reads
                   ▼                             │
       ┌────────────────────────────────────────┴────────────────┐
       │                 packages.harness                         │
       │                                                          │
       │  run_plan_exec_loop(config, runtime)                     │
       │  • planner iter (1×): reads prefetch, light browse,      │
       │                       writes plan.md                     │
       │  • executor iters (N×): each task = one feature area;    │
       │                         drives playwright skill;         │
       │                         writes parts/<task>.md +         │
       │                         parts/<task>.caps.json +         │
       │                         evidence/<task>/…                │
       └──────────────────────────────────────────────────────────┘
```

`shop_arena.explore` is a thin façade. The harness owns the loop, telemetry,
and `run.json`. The agent runtime (default `pi`) owns the LLM and the
playwright skill discovery. `shop_arena.explore` owns three things:

1. **Prefetch** — one deterministic Python step before the loop.
2. **Prompt + AGENTS.md bundle** — the planner/executor instructions
   and the project constitution that scope the run.
3. **Synthesis** — one deterministic Python step after the loop, plus a
   single LLM call to merge the prose.

### 5.2 Execution model

```
shop-explore <url>
  │
  ├─ 1. validate url, derive domain + run_id
  ├─ 2. prefetch(url) → seed_dir/prefetch/         (no LLM, ~5–15 s)
  │      • abort early on bot-block, network error, non-2xx index
  ├─ 3. render prompts + AGENTS.md into seed_dir/
  ├─ 4. run_plan_exec_loop(
  │        run_dir=out_dir,
  │        prompts={planner, execute},
  │        agents_md=...,
  │        artifact_seed_dir=seed_dir,
  │        runtime=get_runtime("pi"),
  │        config={max_iters, timeout},
  │     )
  │      • 1 planner iter, then ≤ max_iters executor iters
  │      • each executor iter = one task in plan.md
  ├─ 5. synthesize(out_dir/artifact/)
  │      • merge parts/*.caps.json → capabilities.json   (deterministic)
  │      • compute stats.json from prefetch + capabilities (deterministic)
  │      • single LLM call: parts/*.md + caps.json → manual.md + final anonymization re-check
  │      • write manifest.json (run summary, justified omissions)
  └─ 6. exit code = 0 iff harness final_status == completed
                       AND capabilities.json validates
                       AND manual.md non-empty
```

The planner iteration receives prefetch evidence in
`run_dir/artifact/prefetch/` via `artifact_seed_dir`. It must browse at
most a small fixed number of pages (homepage + 1 collection + 1 PDP +
homepage interactions) before emitting `plan.md`; this is enforced by
the planner prompt, not the harness.

### 5.3 Coverage taxonomy

The planner is expected to **consider** each of these feature areas and
emit a task when the prefetch indicates it is present (or skip it with a
note in `manifest.json` when it is absent):

```
Site shell:        announcement_bar, header_navigation, mega_menu, footer
Homepage:          hero, sections (featured_collection / banner / testimonials /
                   carousel / video), newsletter, popups
Collection:        listing_layout, product_card, filters, sort, pagination
Product detail:    gallery, variant_selectors, qty_selector, add_to_cart,
                   description, recommendations, reviews
Cart:              cart_drawer_or_page, line_item_edit, upsells, promo_code
Search:            search_trigger, predictive, results_layout
Info / policy:     about, contact, shipping, returns, privacy, tos, faq, gift_cards
Internationalization: locale_switcher, currency_switcher
Floating:          chat_widget, age_gate, cookie_banner
```

The planner does not blindly emit a task for every area. Tasks must be
*evidenced*: derived from prefetch (`/cart.js` exists ⇒ cart task) or
from the planner's brief browse. Areas observed-absent are listed in
`manifest.json:omitted_areas` with a one-line reason.

### 5.4 Output layout

`out_dir == run_dir`. The harness owns the top-level structure (§5.3 of
the harness spec); `shop_arena.explore` owns everything under `artifact/`.

```
outputs/shop_manuals/<domain>/<run_id>/
├── AGENTS.md                 # harness-stable; written by shop_arena.explore
├── prompts/                  # harness-stable; planner.md, execute.md
├── plan.md                   # harness; evolving
├── iters/                    # harness; per-iteration trajectories
├── run.json                  # harness; run summary
└── artifact/                 # owned by shop_arena.explore + agents
    ├── manual.md             # PUBLISHED — prose, anonymized
    ├── capabilities.json     # PUBLISHED — structured tags, schema-validated
    ├── stats.json            # PUBLISHED — analysis statistics
    ├── manifest.json         # PUBLISHED — run summary + omitted_areas
    ├── prefetch/             # seeded by shop_arena.explore (no LLM)
    │   ├── index.html
    │   ├── sitemap.xml
    │   ├── robots.txt
    │   ├── products.json
    │   ├── collections.json
    │   ├── search_suggest.json
    │   ├── cart.js
    │   ├── policies/         # /policies/* HTML
    │   └── prefetch.json     # what we tried + outcome per URL
    ├── parts/                # written by executors
    │   ├── <task_id>.md
    │   ├── <task_id>.caps.json
    │   └── <task_id>.product-<key>.json # generic sites only (§5.6)
    └── evidence/             # written by executors
        └── <task_id>/
            ├── snapshots/    # playwright `pw.js snapshot` a11y dumps
            ├── screenshots/  # full-page PNGs
            └── network.jsonl # optional: captured XHR responses
```

The six **published** files (`manual.md`, `capabilities.json`,
`stats.json`, `manifest.json`, `site_graph.json` (§5.13), plus the
`prefetch/` directory) form the
contract consumed by downstream `shop_arena.gen`. Everything else
(`parts/`, `evidence/`, harness telemetry) is debugging context and may
be excluded by tooling that ships manuals around.

`<run_id>` is `<UTC-timestamp>-<short-hash>` where the hash is the
SHA-256 prefix of `(url, runtime, version)` to allow safe parallel runs
of the same shop.

### 5.5 Capabilities schema

`capabilities.json` is a single pydantic v2 model owned by
`shop_arena.explore.capabilities`. It is **closed** (extra fields rejected)
so schema drift is loud. Top-level shape:

```json
{
  "version": "0.1",
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
    "has_personalization": false
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
    "results_layout": "grid_with_filters"
  },
  "intl": {
    "has_locale_switcher": true,
    "has_currency_switcher": false
  },
  "floating": {
    "has_chat_widget": true,
    "has_age_gate": false,
    "has_cookie_banner": true,
    "has_newsletter_popup": true
  },
  "info_pages_present": ["about", "contact", "shipping_policy",
                         "returns_policy", "privacy", "tos", "faq",
                         "gift_cards"]
}
```

Each executor writes a fragment matching one or more top-level keys to
`parts/<task_id>.caps.json`. The post-loop merge is a deterministic
deep-merge with the rule: **last writer wins per leaf**, except lists
(union, deduplicated, order-preserving) and `null`. For a scalar field,
`null` means unknown: it never replaces a non-null value, and a later
non-null value fills it. Neither case is a conflict. Conflicts (two
different non-null values for one leaf) are recorded in
`manifest.json:capability_conflicts`.

### 5.6 Stats schema

`stats.json` is computed deterministically by `shop_arena.explore.stats`.
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

**Per-task executor obligations** (encoded in the execute prompt and
`AGENTS.md`):

1. Read `plan.md` for the selected task and its inline brief.
2. Read `artifact/prefetch/` for context.
3. Drive the browser **only** via the playwright skill CLI
   (`node $SKILL_DIR/scripts/pw.js …`). No HTTP fetch from inside the
   executor.
4. Capture evidence under `artifact/evidence/<task_id>/`:
   - one a11y `snapshot.md` per distinct page state,
   - one full-page PNG per distinct page state (use playwright's
     `--full-page`),
   - optional `network.jsonl` of relevant XHRs (e.g. cart updates).
5. Write a markdown section to `artifact/parts/<task_id>.md`,
   apply anonymization rules at write time. The `anonymization`
   verifier scans only this file of the selected task. A hit reopens
   the task at most twice (the count per task is kept in
   `run/checks/anonymization_reopens.json`); the next hit blocks the
   task with a note that names the file.
6. Write a JSON fragment to `artifact/parts/<task_id>.caps.json`
   containing only the capabilities-schema keys this task is
   responsible for.
7. Self-check (per harness §5.8): the markdown describes structure,
   not original copy; the JSON fragment is well-formed; ≥ 1 screenshot
   exists.
8. Mark the task `[x]` (or `[!]` with reason) before exiting.

### 5.8 Prompts and AGENTS.md

Three caller-owned files live under `packages/shop_arena/src/shop_arena/explore/prompts/`:

- `agents.md` — project constitution. Anonymization rules (verbatim
  from the legacy `anonymization_rules.md`, lightly extended), how to
  invoke the playwright skill, file-write conventions, the
  capabilities schema reference.
- `planner.md` — instructions to emit `plan.md`. Guides through the
  coverage taxonomy (§5.3), priority assignment, the small-browse
  budget, and the omitted-areas reporting.
- `execute.md` — instructions for one task iteration. References
  `AGENTS.md` for shared conventions; the harness prepends the
  `selected_task_id` control header.
- `execute_generic.md` - the executor prompt on a generic site. It is
  `execute.md` plus the rule to record each product page that the
  executor opens with the `record_product_observation` tool (§5.6).

Prompts are shipped as importable resources; not user-templated in
v0.1.

### 5.9 Prefetch

`shop_arena.explore.prefetch.run(url) -> PrefetchResult` performs a fixed,
small fetch using `httpx`:

```
critical_html  = ["/", "/cart", "/search",
                  "/policies/refund-policy",
                  "/policies/privacy-policy",
                  "/policies/terms-of-service",
                  "/policies/shipping-policy",
                  "/pages/about", "/pages/contact", "/pages/faq"]
json_endpoints = ["/products.json?page=N&limit=250",  # paginated; see below
                  "/collections.json?limit=50",
                  "/search/suggest.json?q=a&resources[type]=product",
                  "/cart.js"]
plus           = ["/sitemap.xml", "/robots.txt"]
```

`/products.json` is walked across every page until a page returns
fewer than 250 products (or a safety cap is hit), and the merged
``{"products": [...]}`` document is written verbatim to
``prefetch/products.json``. Each page request appears as its own entry
in ``prefetch.json`` so the per-URL log stays honest.

This is intentionally bounded — it captures *enough* to seed the
planner, not the whole shop. (The legacy crawler at
`shop-snap/src/collector/crawler.py` is broader and slower; we
deliberately do not adopt it here.)

Behavior:

- **Bot-block detection.** If `/` returns 403/429/503, contains a
  Cloudflare challenge marker, or `robots.txt` blocks `User-Agent: *`
  on `/`, abort with `ShopUnreachableError`.
- **Rate limit.** ≥ 500 ms between requests.
- **User-Agent.** `ShopExplore/<version> (+https://github.com/...)`.
- Output is written verbatim plus a `prefetch.json` summary listing
  `url → status, content_type, bytes`.

Prefetch is the only network code in `shop_arena.explore`. The agents do all
further browsing through playwright.

### 5.10 Synthesis

After the harness loop returns, `shop_arena.explore.synthesize(run_dir)`
runs (no further harness involvement):

1. **Capabilities merge** (deterministic). Read every
   `parts/*.caps.json`, deep-merge into one `capabilities.json`,
   validate against the v0.1 schema. Conflicts → `manifest.json`.
2. **Stats** (deterministic). Compute `stats.json` from
   `prefetch/products.json`, `prefetch/collections.json`, and
   `capabilities.json`.
3. **Manual prose** (one LLM call, no browsing). Concatenate
   `parts/*.md` and `capabilities.json`, send to the configured LLM
   (default the same as the agent runtime's underlying model) with the
   merge prompt. Output: `manual.md`. The merge prompt re-applies
   anonymization rules as a final pass on the prose.
4. **Manifest** (deterministic). Write `manifest.json`:
   `{domain, run_id, runtime, started_at, finished_at, harness_status,
     iters, plan_tasks_total, plan_tasks_done, plan_tasks_blocked,
     omitted_areas, capability_conflicts, coverage_gaps, fixed_area_gaps,
     paths}`.

Synthesis failure modes (loud — no silent fallback):

- Capabilities schema invalid → exit non-zero, no `manual.md` emitted.
- Manual LLM call empty / < 200 chars → exit non-zero, no `manual.md` /
  `manifest.json` emitted. Earlier revisions silently concatenated
  `parts/*.md` and set `manifest.json:manual_fallback=true`; that path
  masked LLM-client misconfiguration (the `_NoOpLLMClient` always
  returned `""`) and was removed deliberately.
- Manual LLM call raises (network error, timeout, runtime missing
  `complete()`) → exit non-zero, no `manual.md` / `manifest.json`
  emitted. Runtimes that do not implement `harness.runtimes.LLMCompleter`
  (e.g. `replay`) require an explicit `llm=` argument to
  `shop_arena.explore.pipeline.explore`.

### 5.11 CLI surface

```
shop-explore <url> [--out PATH] [--runtime {pi,claude_code}]
                   [--max-iters N] [--timeout SECONDS]
                   [--prefetch-only] [--synthesize-only]
```

- `--prefetch-only` runs §5.9 and exits; useful for debugging.
- `--synthesize-only PATH` re-runs §5.10 against an existing run_dir
  (mirrors the legacy `--merge-only` flag, but pure-Python this time).

Library equivalent:

```python
from shop_arena.explore import explore, ExploreConfig

result = explore(ExploreConfig(url="https://example-shop.com",
                                runtime="pi"))
assert result.manual_path.exists()
```

### 5.12 Module layout

```
packages/shop_arena/src/shop_arena/explore/
├── __init__.py            # public re-exports: explore, ExploreConfig, ExploreResult
├── cli.py                 # thin argparse → explore()
├── config.py              # ExploreConfig, ExploreResult (pydantic v2)
├── prefetch.py            # PrefetchResult, run(url)
├── capabilities.py        # Capabilities schema + merge_fragments()
├── stats.py               # compute_stats(prefetch, capabilities)
├── synthesize.py          # synthesize(run_dir, llm) → manual.md, manifest.json
├── pipeline.py            # explore() — orchestrates the four steps
├── prompts/
│   ├── agents.md
│   ├── planner.md
│   └── execute.md
└── py.typed
```

Tests live under `packages/shop_arena/tests/explore/` and exercise:

- Prefetch against a recorded `respx`/`httpx` cassette.
- Capabilities schema round-trip + merge edge cases.
- Stats computation against fixture prefetches.
- A full harness e2e using `harness.runtimes.replay` against a
  recorded `shop_arena.explore` cassette (one fixture storefront).
- Anonymization regex scan over the synthesized manual.

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
  as a search query or a category id. A path segment that changes from
  page to page, such as a category name, is a placeholder.
- An action line with no `(path changed)` mark stays on its state, or
  opens an overlay on it. A filter, sort, page or variant change is
  `update_in_place`, also when the URL loads again. `navigate` goes to
  another page: another state, or another page of the same state.
- The header and the footer show on every page. Their overlays list
  every page state as a host page, and each of their controls gets one
  transition from `home`, not one from each page.
- `from` is the state that shows the control.
- A behavior that a fragment calls unknown gives no transition.

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
  trigger: 'click' | 'hover' | 'type' | 'submit' | 'key';
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
as a hard gate. Deferred: requires curated block-lists per store; the
prompt-rule version is sufficient to ship and we can layer a scrubber
later without changing the artifact contract.

**F. Use the full `shop-snap` crawler for prefetch.** Rejected: it's
designed for byte-perfect snapshots (assets, CSS, JS, ≤ 1000 pages) and
takes minutes. We need < 30 s of seed data, not a snapshot.

---

## 7. Milestones

**M1 — Prefetch + capabilities schema + stats.** Pure Python, no LLM.
Unit-tested against recorded fixtures. Deliverable: `shop-explore
--prefetch-only <url>` writes `prefetch/` + a draft empty
`capabilities.json` skeleton.

**M2 — Prompts + AGENTS.md + harness wiring.** Author `agents.md`,
`planner.md`, `execute.md`. Implement `pipeline.explore()` calling
`run_plan_exec_loop` with a stub runtime. Deliverable: e2e under
`harness.runtimes.replay` against a hand-crafted cassette.

**M3 — Synthesis.** Implement deterministic capabilities merge, stats,
and the single-call LLM manual merge. Deliverable: full Shop Manual
emitted on the replay fixture; SC2 + SC3 pass.

**M4 — Real-runtime smoke.** Record cassettes by running the live `pi`
runtime against 2 fixture storefronts (one with a cart drawer + mega
menu, one minimal). Add `HARNESS_SMOKE_*`-style gates. Deliverable:
documented fixture set, smoke-test green locally.

**M5 — v0.1.0.** README, CLI help, module CHANGELOG, docs/specs index
updated. Tag `shop-explore-v0.1.0`.

---

## 8. Appendix

### 8.1 Public surface (informative)

- **Types** (`shop_arena.explore.config`): `ExploreConfig`,
  `ExploreResult`, `RuntimeName`.
- **Schemas** (`shop_arena.explore.capabilities`, `shop_arena.explore.stats`):
  `Capabilities` (pydantic v2), `Stats`.
- **Functions**: `explore(config) -> ExploreResult`,
  `prefetch.run(url) -> PrefetchResult`,
  `synthesize.synthesize(run_dir) -> SynthesisResult`,
  `capabilities.merge_fragments(parts_dir) -> Capabilities`.
- **Errors**: `ShopUnreachableError`, `PrefetchError`,
  `CapabilitiesValidationError`, `SynthesisError`.

### 8.2 Open questions

1. **LLM provider for synthesis.** Reuse the agent runtime's LLM
   (extra adapter), or go direct (`anthropic` SDK with a configurable
   model)? Direct is simpler; runtime-coupling is cleaner. Lean
   toward direct for v0.1.
2. **Run id collision policy.** Currently abort if `<out_dir>` is
   non-empty. Should we add `--force` to overwrite? Lean no.
3. **Fixture storefronts.** Pick 2–3 public dev demo stores
   for the test cassettes that we have license to redistribute
   anonymized snapshots of.
4. **Capabilities schema versioning.** Field-additive only within
   `0.x`; bump to `1.x` for any field rename or removal. Document
   migration in `CHANGELOG`.
5. ~~**Stats from prefetch is a sample.** `/products.json?limit=50`
   caps at 50 products; for accurate `products_total` we may need
   pagination. v0.1 reports the sample size and a `truncated: true`
   flag rather than crawling every page.~~ **Resolved (2026-04-25):**
   prefetch paginates `/products.json?page=N&limit=250` until the
   storefront's last (short) page or a safety cap; `Stats.products_total`
   is exact (T6.4). The `products_truncated` flag was removed.

### 8.3 Future directions (non-blocking)

- **Deterministic anonymization scrubber** (Alternative E) as a
  hard gate before publishing.
- **Cross-shop manual diff/merge** in `shop_arena.gen` consuming N
  manuals.
- **Mobile viewport pass** as a second planner (currently desktop
  1440×900 only).
- **Headed-mode debug runs** wired through the playwright skill's
  `--headed` flag.
- **Authenticated flows** (account, wishlists) once we have a
  stable test-account story.
- **Uses of the Site state graph** (§5.13). Shop generation can carry
  the graph into a SandboxShop and add a `weights` block from shopper
  behavior data. A Build loop Verifier can walk each transition. Task
  generation (`docs/specs/shop_guru/task_generation_proposal.md`) can
  list the transitions that its tasks do not reach. Named flows, such
  as search to purchase, can go on top of the transitions.
