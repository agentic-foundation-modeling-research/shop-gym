# ShopExplore (`packages/shop_arena/src/shop_arena/explore`)

Status: **Spec (proposed)** · Version: **0.1**
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
  `stats.json` (analysis statistics), per-task evidence, and a
  `manifest.json`. See §5.4.
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

---

## 3. Current Status

- `packages/shop_arena/src/shop_arena/explore/` is a 2-line scaffold (`cli.py`
  prints "not implemented"). No spec, no module structure.
- A legacy reference exists out-of-tree uses `browser_use` and one hard-coded agent per fixed page type
  (`homepage`, `collections`, `product`, `cart_and_search`,
  `info_pages`, `navigation`). Output is a single free-form
  `shop_manual.md` plus per-agent `reference_screenshots/`. It has no
  planner, no prefetch, no structured capabilities, no harness.
- `packages/harness` is fully implemented at v0.1.0 and has no caller in
  this repo yet.

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
  a planner task or a justified omission in `manifest.json`.

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
    │   └── <task_id>.caps.json
    └── evidence/             # written by executors
        └── <task_id>/
            ├── snapshots/    # playwright `pw.js snapshot` a11y dumps
            ├── screenshots/  # full-page PNGs
            └── network.jsonl # optional: captured XHR responses
```

The five **published** files (`manual.md`, `capabilities.json`,
`stats.json`, `manifest.json`, plus the `prefetch/` directory) form the
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
(union, deduplicated, order-preserving). Conflicts are recorded in
`manifest.json:capability_conflicts`.

### 5.6 Stats schema

`stats.json` is computed deterministically by `shop_arena.explore.stats` from
`prefetch/` + `capabilities.json`. No LLM. Shape:

```json
{
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
   - optional `network.jsonl` of relevant XHRs (e.g. predictive search
     suggestions).
5. Write a markdown section to `artifact/parts/<task_id>.md`,
   apply anonymization rules at write time.
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
     omitted_areas, capability_conflicts, paths}`.

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
3. **Fixture storefronts.** Pick 2–3 public Shopify dev demo stores
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
