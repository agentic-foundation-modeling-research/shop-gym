# EnvEval (`packages/shop_arena/src/shop_arena/env_eval`)

Status: **Implemented (`shop_arena.env_eval` v0.1.2)**
Version: **0.2**
Date: 05/04/2026

> A measurement instrument that scores how usable a storefront is as an
> environment for LLM agent **RL training and evaluation**. Given one
> shop URL, EnvEval samples five canonical pages and emits raw
> structural numbers across three layers — what an agent can **see**
> (observation), what it can **do** (action), and how the pages **link
> together** (transition graph). `metrics.json` is a closed pydantic v2
> schema; cross-run analysis happens downstream (e.g. notebooks).

---

## 1. Overview

`shop_arena.env_eval` is a measurement-only module. It does **not** generate
shops, manuals, or tasks; it does **not** evaluate agents. It evaluates
*environments*. The intended consumer is anyone deciding whether a
storefront — a real merchant, a generated SandboxShop, a baseline
fixture — is rich enough and structurally sound enough to serve as an
RL environment.

Three design choices shape the module:

- **Single URL in, raw metrics out.** The CLI takes one storefront URL.
  No prefetch dependency on `shop_arena.explore`, no per-shop YAML, no
  agent. v0.1 emits structured numbers; consumers decide weights.
- **Browser-gym is the source of truth for instrumentation.** Both the
  simplified accessibility tree and the action space are read through
  `browsergym.core` so EnvEval shares its observation/action vocabulary
  with the agents that will eventually train against the env.
- **Three independent measurement layers.** Observation, Action, and
  Transition each produce their own artifacts and can be re-run
  independently when one layer's logic changes. Caching is per-layer.

EnvEval is also the second non-trivial caller of browsergym in this
repo (after `shop_guru.eval`), so it intentionally stays inside the
`browsergym.core` API surface and avoids `agentlab` / `Study`.

> Naming: this module is `shop_arena.env_eval` (env eval). It must not be
> confused with `shop_guru.eval`, which evaluates *agents* against
> ShopGuru tasks.

---

## 2. Terminology

- **Storefront / Shop** — the public, unauthenticated view of an online
  store at a base URL.
- **Sample page** — one of five canonical pages EnvEval visits per
  shop: `homepage`, `collection`, `product`, `policy`,
  `cart_and_search`. The `cart_and_search` slot covers `/cart` plus a
  search URL (`/search?q=<query>`) where `<query>` is inferred from the
  storefront itself, then merged into one bucket for reporting.
- **Search query** — the deterministic query EnvEval derives from page
  evidence (product title/slug, collection title/slug, or navigation text)
  for the sampled search page and search-related stateful rules. It is
  not a CLI input in v0.1.
- **Observation layer** — measurement of what an agent can perceive on
  a sample page: simplified axtree statistics + LLM-categorized
  screenshot rubric.
- **Action layer** — measurement of what an agent can do on a sample
  page: target counts for the action vocabulary exposed by BrowserGym's
  `HighLevelActionSet` (`click`, `fill`, `hover`, `select_option`,
  `scroll`, `goto`, …), derived via EnvEval's versioned role/action
  heuristic.
- **Transition layer** — a coarse user-flow graph reverse-engineered
  from the shop. Nodes are *page classes* (canonical URL templates +
  named in-page states); edges are *transitions* labelled by the
  triggering action.
- **Page class** — a canonicalized URL or named state used as a graph
  node. URL-based nodes collapse instances to templates
  (`/products/<*>`, `/collections/<*>`, `/policies/<*>`); state-based
  nodes are named (`cart_drawer`, `search_overlay`,
  `variant_select_open`).
- **Cohort / group** — a named set of shops compared as a unit during
  aggregation (e.g. `sandbox`, `real`, `category=fashion`).
- **Run** — one full EnvEval invocation against one URL, written to
  `outputs/shop_env_evals/<shop_name>/<run_id>/`.

---

## 3. Current Status

- `packages/shop_arena/src/shop_arena/env_eval/` is implemented and
  exposed as the `shop-env-eval` console script.
- The shipping CLI surface is:
  - `shop-env-eval run <url>` for single-shop measurement and cached
    resume against an output directory;
  - `shop-env-eval compare <url> <url> [...]` for URL-only structural
    variance as specified in `structural_variance.md`;
  - `shop-env-eval visualize <run_dir>` for rendering the transition
    graph as a self-contained HTML page.
- The implementation includes page selection, BrowserGym-backed
  capture, accessibility-tree statistics, optional LLM screenshot
  rubric, role/action/choice target counting, hybrid href-BFS,
  fixed-rule stateful transitions, `/pages/<slug>` classification,
  closed pydantic metrics/manifest schemas, and artifact reuse.
- `packages/shop_arena/pyproject.toml` now depends on `browsergym` and
  Playwright; `--no-rubric` skips LLM calls while keeping
  schema-valid stub artifacts.
- General metrics aggregation remains downstream. URL-only structural
  comparison is implemented by the additive sibling specification
  [`structural_variance.md`](structural_variance.md).

---

## 4. Desired Status

A self-contained module under `packages/shop_arena/src/shop_arena/env_eval/`
that, given one storefront URL, runs a fixed measurement pipeline and
emits a single per-shop run directory plus a CLI for measuring one
shop and visualizing its transition graph.

### 4.1 I/O contract

**Inputs** (CLI or library):

| Input          | Notes                                                                  |
| -------------- | ---------------------------------------------------------------------- |
| `url`          | Public storefront base URL. Required for `run`.                        |
| `out_dir`      | Defaults to `outputs/shop_env_evals/<shop_name>/<run_id>/`. May already contain a partial run; existing artifacts are reused. |
| `viewport`     | `1440x900` (default). Single viewport in v0.1.                         |
| `max_hops`     | BFS depth for the transition graph. Default 3.                         |
| `rubric_model` | LLM model used for the screenshot rubric. Default `claude-sonnet-4-6`. |
| `rediscover`   | Ignore an existing `pages.json` and select pages again. Default false. |

**Outputs** — one run directory per call (§5.5). The run directory
holds raw artifacts plus a `metrics.json` that is the single
**published** file; downstream tools (e.g. notebooks) consume it directly.

**Out of scope for v0.1:**

- Authenticated flows (login, account, wishlist).
- Checkout (cart-to-payment).
- Mobile viewport / responsive measurement (desktop only).
- Rendered page mass / asset weight / Lighthouse-style perf metrics.
- Composite quality score; weighting different metrics into one number.
- Re-deriving a Shop Manual or capabilities (that is `shop_arena.explore`).

### 4.2 Success criteria

- **SC1 — One command.** `shop-env-eval run <url>` writes a complete
  run directory and prints the path to `metrics.json` on stdout.
- **SC2 — Schema-valid metrics.** `metrics.json` validates against the
  v0.1 pydantic model on every fixture in the test set. Closed schema:
  unknown keys are rejected.
- **SC3 — Reproducible page selection within a run.** Re-running against
  the same `out_dir` reuses the same five sample URLs from `pages.json`;
  `--rediscover` selects pages again and records the fallback chain used.
- **SC4 — Artifact reuse skips work.** A second invocation against the
  same `out_dir` performs zero browser navigations and zero LLM calls for
  layers whose required artifacts already exist; `manifest.json` records
  which steps were reused. No global cache or content hash is required.
- **SC5 — Deterministic visualize.** `shop-env-eval visualize <run_dir>`
  emits byte-stable HTML for fixed inputs.

---

## 5. Proposal

### 5.1 Architecture
```
                     ┌──────────────────────────────────────┐
                     │            shop_arena.env_eval       │
                     │      url + out_dir → metrics.json    │
                     └──────────────────┬───────────────────┘
                                        │
                                        ▼
              ┌─────────────────────────────────────────┐
              │ run_dir artifact reuse                  │
              │ if expected files exist, read + skip;   │
              │ otherwise run the step and write files  │
              └──────────────────┬──────────────────────┘
                                 │
          ┌──────────────────────────────────────────────┐
          ▼                                              ▼
 ┌─────────────────┐                          ┌─────────────────┐
 │ pages.json      │─────────────────────────▶│ transition/*    │
 │ page discovery  │                          │ graph + nodes   │
 └─────────────────┘                          └────────┬────────┘
                                                        ▼
                                             ┌─────────────────┐
                                             │ observation/*   │
                                             │ node screenshots│
                                             │ + axtree/rubric │
                                             └────────┬────────┘
                                                        ▼
                                             ┌─────────────────┐
                                             │ action/*        │
                                             │ node action_space│
                                             └────────┬────────┘
                                                        ▼
                                             ┌─────────────────┐
                                             │ metrics.json    │
                                             │ published       │
                                             └────────┬────────┘
                                                      │
                                                      ▼
                              downstream tools (notebooks) read metrics.json
```

`shop_arena.env_eval` is a thin pipeline. It owns the page-selection logic,
three measurement layers, and run-directory artifact reuse. Artifact
reuse is intentionally literal:
`pages.json`, `observation/*`, `action/*`, `transition/*`, and
`metrics.json` are each the skip condition for their corresponding step.
It does not own a harness loop, a planner, or any LLM agent beyond the
screenshot rubric and state-name rubric.

### 5.2 Page selection

EnvEval visits exactly five buckets per shop. Discovery is
browser-driven and **not LLM-driven**: it uses BrowserGym/Playwright
navigation plus deterministic axtree/DOM rules. No model is called during
page selection. Discovery proceeds top-down so that a failure on the
homepage aborts the whole run loud:

1. **homepage** — `goto(url)`. Mandatory; if this fails the run aborts
   with `ShopUnreachableError`.
2. **collection** — scan the homepage axtree for the first href
   matching `/collections/<slug>` that is not `/collections/all` (and
   fall back to `/collections/all` if no other found). Visit it.
3. **product** — scan the collection axtree for the first
   `/products/<slug>` href. If absent, scan the homepage for one. If
   still absent, mark the bucket as `not_found` and continue.
4. **policy** — try `/policies/privacy-policy`. On 404, scan the
   homepage axtree footer for any `/policies/<*>` href. Record which
   one was used.
5. **cart_and_search** — visit `/cart`. Then infer a search query from
   storefront evidence and visit `/search?q=<query>` if a query is found;
   otherwise mark the search subpage as `not_found` and continue. Both
   subpages contribute to the `cart_and_search` bucket.

The search query is deterministic and page-derived. EnvEval chooses the
first available candidate from this ordered list, normalizing to lowercase
one-to-three meaningful tokens and dropping generic commerce words such as
`shop`, `all`, `new`, `sale`, and `collection`:

1. product title from the selected product page or product card;
2. selected product URL slug;
3. selected collection title/header or collection URL slug;
4. first non-generic category/navigation label on the homepage.

The chosen query, source rule, and raw source text are recorded in
`pages.json`. There is no hard-coded fallback query in v0.1.

Discovery is recorded in `pages.json` with the chosen URL per bucket
plus the rule that selected it (`first_href`, `fallback_path`,
`not_found`). If `pages.json` already exists in `out_dir`, re-runs read
it and evaluate the same URLs even if the storefront's homepage changed
since the first run; `--rediscover` forces a fresh selection.

The first possible LLM call in the pipeline happens later in the
observation screenshot rubric (§5.3), after `pages.json` has already fixed
the sample URLs.

URL handling is explicit and deterministic: EnvEval normalizes the input
base URL to a scheme + host + trailing slash, resolves relative hrefs
against the current page, treats only the same host as in-domain in v0.1,
and strips query/fragment values for canonical graph node ids except for
the sampled search URL recorded in `pages.json`. A 404 is determined from
the HTTP response returned by navigation when available; soft-404 content
is not detected in v0.1 and is recorded as an ordinary page.

### 5.3 Observation layer

EnvEval opens **one** BrowserGym environment for the entire run. Page
selection and the transition layer drive the browser; the observation layer
then uses the browser states already captured under `transition/node/` as its
input. URL graph nodes read `screenshot.png`, `axtree.json`, and `axtree.txt`
from their node folder. Stateful graph nodes read the post-action state:
`post.png`, `post.axtree.json`, and `post.axtree.txt`. Per captured graph
node, EnvEval writes node-stemmed observation artifacts:

- `<node_folder>.png` — full-viewport screenshot for the graph node.
- `<node_folder>.axtree.txt` — EnvEval-rendered text view of the axtree.
- `<node_folder>.axtree.json` — BrowserGym axtree object for the stat pass.
- `<node_folder>.rubric.json` — parsed screenshot-rubric response.
- `index.json` — graph-node id to node-level observation files.

**Axtree statistics** (deterministic, no LLM):

- `node_count` — total nodes in the simplified tree.
- `interactive_count` — nodes whose role is in
  `{button, link, textbox, combobox, checkbox, radio, menuitem, …}`.
- `link_count`, `button_count`, `textbox_count`, `image_count`,
  `heading_count`, `landmark_count` — by-role counts (closed enum).
- `max_depth` — deepest path in the raw tree.
- `semantic_max_depth` — deepest path after collapsing presentational/text
  wrapper roles (`none`, `generic`, `Section`, `StaticText`,
  `InlineTextBox`, etc.) so theme/layout nesting does not dominate the
  depth signal.
- `content_character_count` — normalized character count of visible text
  content.

**Screenshot rubric** (one LLM call per screenshot):

The rubric prompt sends the screenshot plus a closed enum of element
categories and asks the model to return a JSON object
`{category: count, …}`. v0.1 enum:

```
nav | mega_menu | announcement_bar | hero | product_card |
product_image | cta_button | secondary_button | form_input |
filter_chip | breadcrumb | text_block | footer | popup_modal |
cart_drawer | search_bar | chat_widget | other
```

Output schema is closed (`extra="forbid"`); unknown categories surface
as `other`. The rubric prompt and enum live in
`shop_arena/env_eval/rubric/prompt.md`. Model is configurable via
`--rubric-model`; default is the same model used by `shop_arena.explore`
for parity. EnvEval stores the normalized prompt version, raw model
response, parsed JSON, and parse errors in the rubric artifact. Calls use
temperature `0` where the provider supports it; artifact reuse, not model
determinism, is the reproducibility boundary.

This is an LLM-using step in the default pipeline. It can be disabled with
`--no-rubric`, in which case EnvEval writes schema-valid stub rubric artifacts
and performs no observation-layer LLM calls.

In `metrics.json`, EnvEval aggregates observation across all successfully
captured transition nodes instead of duplicating the per-node/page records.
The aggregate contains `node_count`, `interactive_count`,
`distinct_node_count` (normalized role/name signatures), `max_depth`,
`semantic_max_depth`, `content_character_count`, and summed rubric category
counts. Per-node detail
remains available in `observation/` via `index.json` plus the referenced
artifacts.

### 5.4 Action layer

For each captured transition graph node, EnvEval uses BrowserGym's
high-level action set as the **action vocabulary** and derives target counts
from the node axtree. URL nodes use their captured `axtree.json`; state nodes
use `post.axtree.json`. BrowserGym exposes the available action functions,
but it does not expose a per-element "applicable actions" API; EnvEval
therefore owns a small versioned role/action heuristic.

```python
from browsergym.core.action.highlevel import HighLevelActionSet
```

EnvEval instantiates the set with the same subsets ShopGuru's agents use
(`("chat", "infeas", "bid", "nav", "tab")`) so the vocabulary matches
the training/evaluation agents. Hidden AX nodes (`hidden` or `hiddenRoot`)
are skipped. The per-target counts are then computed from visible,
bid-bearing axtree/DOM metadata with a closed mapping:

| Roles / target shape | Counted actions |
| -------------------- | --------------- |
| `button`, `link`, `menuitem`, clickable controls | `click`, `hover`, `dblclick` |
| `textbox`, `searchbox`, text-like inputs | `fill`, `clear`, `press` |
| `combobox`, `listbox`, `option` controls | `select_option` |
| scrollable page/regions | `scroll` |

Global or targetless actions from the subset (`goto`, `go_back`,
`go_forward`, `new_tab`, `tab_focus`, `tab_close`, `send_msg_to_user`,
`report_infeasible`, `noop`) are recorded in the artifact's vocabulary
block but are not included in target counts. The heuristic version is
recorded in `manifest.json` and in each action artifact.

EnvEval also records non-action target categories in `by_category`. v0.2
defines `choice`: visible discrete choice targets/controls, including
`radio`, `checkbox`, `combobox`, `listbox`, `option`, sort/filter popup
buttons (`hasPopup="listbox"`, `Filter*`, `Sort*`), and pressed
variant/color/size buttons when their local or ancestor text indicates a
choice context. This category is not a BrowserGym action verb; it exists
to compare storefront choice/control richness across implementation styles.

In `metrics.json`, EnvEval aggregates raw action counts across all captured
transition nodes and adds `choice_target_count` from `by_category.choice`.
Raw action counts are `click`, `fill`, `hover`, `select_option`, and
`scroll`. Semantic counts are mutually exclusive buckets derived only from
transition graph edges: `search`, `filter`, `goto_home`, `goto_collection`,
`goto_product`, `goto_policy`, `goto_cart`, `open_cart`, and `explore`.
URL-edge targets map to the matching `goto_*`/`search` bucket by canonical
path. State-edge targets map as follows: `cart_drawer` → `open_cart`;
`search_overlay` and `predictive_panel` → `search`; `filter_panel_open`
and `sort_menu_open` → `filter`; all other state targets → `explore`.
Per-node action-space detail remains in `action/` and does not contribute
to semantic counts.

For each counted target, EnvEval records:

- the action types that apply to it (`click`, `fill`, `hover`,
  `select_option`, `dblclick`, `scroll`, …),
- the element's bid when BrowserGym assigned one,
- its role and accessible name (truncated to 80 chars).

Per graph node, the artifact is `action/<node_folder>.action_space.json`:

```json
{
  "vocabulary": ["click", "fill", "hover", "goto", "send_msg_to_user"],
  "by_action": {
    "click": 78,
    "fill": 4,
    "hover": 12,
    "select_option": 1,
    "scroll": 1
  },
  "by_category": {
    "choice": 9
  },
  "elements": [
    {"bid": "a12", "role": "button", "name": "Add to cart",
     "actions": ["click", "hover"]}
  ],
  "subsets": ["chat", "infeas", "bid", "nav", "tab"],
  "heuristic_version": "0.2"
}
```

Counts are flat (not per-element-type-then-per-action) because the downstream
metric is "how many distinct *targets* exist for action X on this graph node",
which is the relevant RL-difficulty proxy.

This layer uses no LLM calls.

### 5.5 Transition layer

The transition graph is built in two passes that share a node table.
Both passes are bounded by `max_hops` (default 3) and a hard ceiling
of 64 BFS navigation attempts to keep cost predictable.

#### 5.5.1 Structural BFS (no LLM)

Starting from each measurable sample URL as a seed (homepage, collection,
product if found, policy, cart, and search):

1. Load the queued representative URL and read the browser's final URL after
   navigation completes.
2. For every link element on the final page, resolve the concrete href and
   canonicalize a tentative node id:
   - drop fragment + query for the canonical id,
   - reject in-domain asset endpoints (Shopify's `/fast-image/` image
     transformation paths and `/cdn/` CDN) — they serve binary files,
     not pages, and would otherwise inflate the node count with one
     entry per image,
   - reject paths whose tail is a non-page file extension (`.xml`,
     `.json`, `.txt`, `.pdf`, image formats) — covers `/sitemap.xml`
     and similar resources reachable via `<a href>`,
   - reject paths containing `:` — these uniformly come from a CMS
     wrapping a `mailto:` link the storefront authored with broken syntax
     (e.g. `/pages/mail%20to:%contact@mock-shop.example`),
   - collapse `/products/<slug>` → `/products/<*>`,
   - collapse `/collections/<slug>` → `/collections/<*>`,
   - collapse `/policies/<slug>` → `/policies/<*>`,
   - collapse `/blogs/<...>` → `/blogs/<*>` (entire subtree, posts and indexes),
   - collapse `/account/<...>` → `/account/<*>` (entire subtree; auth-gated and
     not a shopping affordance — agents cannot operate inside it),
   - collapse `/pages/<slug>` → `/pages/<*>` only when the LLM
     `/pages/<slug>` classifier (spec §5.5.3) labels the slug as
     `marketing`. `/pages/` is Shopify's catch-all for static pages and
     mixes terse info slugs (`/pages/warranty`, `/pages/faq`) with
     sentence-shaped marketing/campaign slugs
     (`/pages/gordons-golden-ticket-paris-rules`,
     `/pages/quality-recipes-made-in-the-finest-cookware`). The
     classifier is invoked lazily inside the BFS — once per page
     expansion that surfaces fresh slugs — and the running result is
     persisted as `transition/pages_classification.json`,
   - leave `/`, `/cart`, `/search`, the bare `/account` dashboard root etc.
     as themselves.
3. Each unique tentative canonical id becomes a graph node. The node table
   stores a concrete in-domain URL as `representative_url`; BFS enqueues
   representative URLs, never placeholder templates like `/products/<*>`.
4. When a queued URL redirects to a different same-domain canonical id, merge
   the tentative node into the final canonical node and rewire existing edges.
   The edge label still keeps the original href (`click(href)`) for debugging.
5. Each (`current_node_id`, `target_node_id`) pair becomes an edge labelled
   `click(href)`. Edge deduplication runs after redirect alias rewrites.
6. Enqueue any unseen representative URL that is in-domain. Stop when the
   per-seed BFS exceeds `max_hops` or the global navigation cap is hit.

This pass is fully deterministic and produces an `href`-edge graph.
When a redirect alias is observed, the BFS trace row includes optional
`final_url` and `resolved_canonical_id` fields.
It uses no LLM calls.

#### 5.5.2 Stateful pass (fixed rules + LLM state naming)

Hrefs miss the JS-driven transitions that matter most for RL agents
— cart drawers, search overlays, variant pickers. v0.1 ships a
**fixed-rule** stateful pass: the candidate interactions are deterministic
and not chosen by an LLM. An LLM is used only after a rule fires, to
disambiguate the resulting state's name from a closed enum.

Per page class, EnvEval attempts a closed list of canonical
interactions and records which ones produced a visible state change
(detected via diff against the pre-action axtree):

```
homepage:    click(announcement_bar.close) → announcement_dismissed
homepage:    click(header.cart_icon)       → cart_drawer
homepage:    click(header.search_icon)     → search_overlay
homepage:    fill(search_input, <derived_query>) → predictive_panel
collection:  click(filter[*])              → filter_panel_open
collection:  click(sort_dropdown)          → sort_menu_open
product:     click(variant[*])             → variant_select_open
product:     click(add_to_cart)            → cart_drawer
cart:        click(qty_inc)                → cart_qty_changed
search:      fill(search_input, <derived_query>) → predictive_panel
```

Rules that require `<derived_query>` are skipped when page selection could
not infer a search query.

For each attempt that produces an axtree-visible change, EnvEval captures
pre/post screenshots and pre/post axtrees, then asks the LLM only `"is
this a meaningfully new state? if yes, name it from {cart_drawer,
search_overlay, …, other}"`. State nodes are added to the graph with
edges labelled by the triggering action. The state artifact stores the
prompt version, raw response, parsed state name, parse errors, pre/post
screenshots, and pre/post axtrees. Calls use temperature `0` where
supported; if the artifact exists on disk, the LLM is not called again.

EnvEval also writes a per-node artifact tree under `transition/node/`.
Each graph node gets its own folder; the homepage node `/` is named
`home`. URL nodes contain `node.json`, `screenshot.png`, `axtree.json`,
and `axtree.txt` for the representative page. State nodes contain
`node.json` plus `pre.*` and `post.*` screenshot/axtree pairs mirrored
from the stateful attempt that produced the node.

The rule list lives in `shop_arena/env_eval/transition/rules.py` and is
versioned with `metrics.json:version`. Adding rules is field-additive
within a schema version only when the metrics schema is also updated for
that version.

#### 5.5.3 `/pages/<slug>` classifier

Shopify storefronts route arbitrarily many static pages through `/pages/<slug>`
— policies, FAQ pages, ambassador profiles, marketing campaigns, contest rules,
recipe blurbs. Without help the BFS records each one as a distinct graph node,
which inflates node counts on shops that weaponise `/pages/` for marketing
content.

The classifier is a single batched LLM call (default model `gpt-5`, provider
routed by prefix) that takes a list of post-`/pages/` paths plus the
storefront base URL and returns one entry per path with a `label` from a
closed seven-value enum:

- `support` — help center, contact, FAQ, return forms.
- `about` — brand story, team, sustainability narrative.
- `policy` — terms, privacy, accessibility, shipping policy.
- `program` — loyalty / referral / ambassador / wholesale signup.
- `locator` — store finder, dealer locator, service map.
- `marketing` — campaign / bundle / promo / contest / recipe page.
- `unknown` — conservative fallback when the model is not confident.

`marketing` is the only label whose paths collapse into the shared
`/pages/<*>` canonical id. Every other label keeps its distinct node identity
so policy / support / about pages remain distinguishable in the transition
graph. `unknown` never collapses, by design.

Invocation is lazy: the BFS calls the classifier once per page expansion that
surfaces previously-unseen slugs, forwarding only the new slugs. The running
classification is persisted as `transition/pages_classification.json` after
every update — partial work survives crashes and resume reuses the document
verbatim. Errors raised by the classifier propagate to the caller; the BFS
does not silently fall back to the un-collapsed graph.

`--no-rubric` switches the classifier to a no-LLM stub: every emitted slug is
recorded with label `"unknown"`, so the artifact stays schema-valid and no
collapsing happens.

#### 5.5.4 Graph metrics

`metrics.json:transition` is computed deterministically from the
combined graph:

- `node_count` — `|V|` (URL nodes + state nodes).
- `edge_count` — `|E|`.
- `state_node_count` — count of named state nodes (drawer, overlay,
  …).
- `avg_out_degree`, `max_out_degree` — branching factor.
- `dead_end_count` — nodes with `out_degree == 0`.
- `diameter` — longest shortest-path between any two reachable nodes.
- `reachable_pct_from_homepage` — `|reachable(homepage)| / |V|`.
- `homepage_to_cart_min_clicks` — shortest path length homepage →
  `cart_drawer` or `/cart` (whichever is reachable; `null` if
  neither). Reported because this is the canonical RL task and a
  proxy for environment "ease".

Graph metrics are computed on a directed graph. For disconnected directed
graphs, `diameter` is the maximum finite shortest-path length within any
reachable component; unreachable node pairs are excluded.

### 5.6 Output layout

```
outputs/shop_env_evals/<shop_name>/<run_id>/
├── pages.json                       # discovered URLs + selection rules
├── observation/
│   ├── index.json                    # transition node -> observation files
│   ├── home.{png,axtree.json,axtree.txt,rubric.json}
│   ├── collections__template.{png,axtree.*,rubric.json}
│   └── state__home__cart_drawer.{png,axtree.*,rubric.json}  # copied from post.*
├── action/
│   ├── index.json                    # transition node -> action files
│   ├── home.action_space.json
│   ├── collections__template.action_space.json
│   └── state__home__cart_drawer.action_space.json           # computed from post.*
├── transition/
│   ├── graph.json                   # nodes + edges + edge labels
│   ├── trace.jsonl                  # per-attempt log (which rule, outcome)
│   ├── pages_classification.json    # /pages/<slug> labels (closed schema)
│   ├── node/                        # one folder per graph node
│   │   ├── index.json               # canonical id -> node folder mapping
│   │   ├── home/                    # URL node for "/"
│   │   │   ├── node.json
│   │   │   ├── screenshot.png
│   │   │   ├── axtree.json
│   │   │   └── axtree.txt
│   │   └── state__home__cart_drawer/
│   │       ├── node.json
│   │       ├── pre.{png,axtree.json,axtree.txt}
│   │       └── post.{png,axtree.json,axtree.txt}
├── metrics.json                     # PUBLISHED — v0.2 schema
└── manifest.json                    # run/reuse summary + config
```

`<run_id>` is the run directory name. If `--out` is omitted, the CLI
creates a timestamped directory. If the caller passes an existing `--out`,
EnvEval treats that directory as a resumable run and skips steps whose
artifacts are already present; no content-addressed cache key is computed.

### 5.7 Artifact reuse / resume

EnvEval intentionally does **not** have a global cache, content hash, TTL,
or HTTP freshness check in v0.1. The filesystem run directory is the cache.
Before each step, the pipeline checks whether that step's expected artifacts
already exist in `out_dir`:

| Step | Required artifacts for reuse |
| ---- | ---------------------------- |
| pages | `pages.json` |
| transition | `transition/graph.json`, `transition/trace.jsonl`, and `transition/node/index.json` |
| observation | `observation/index.json` plus indexed node-stemmed screenshot, `*.axtree.json`, `*.axtree.txt`, and `*.rubric.json` files |
| action | `action/index.json` plus indexed node-stemmed `*.action_space.json` files |
| metrics | `metrics.json` after all upstream artifacts are complete |

If the required files are present, the step is skipped. If any required
file is missing, the step runs and overwrites only that step's artifacts.
`--rediscover` is the only v0.1 invalidation flag: it ignores/deletes
`pages.json` and selects pages again. EnvEval does not cascade-delete
downstream artifacts; callers who rediscover should use a fresh `out_dir`
or delete stale downstream files. EnvEval does not try to detect whether
a live storefront changed; freshness is caller-owned.

`manifest.json` records which steps ran vs. reused, the CLI/config values
(including `pages_classifier_model`), the BrowserGym version,
prompt/rule/heuristic versions (including `pages_classifier_version`), and
counts of browser navigations and LLM calls (rubric + state-namer +
`/pages/` classifier combined). These run facts stay out of
`metrics.json` so the published metrics file remains a comparable
measurement artifact.

### 5.8 Metrics schema (`metrics.json`)

Single closed pydantic v2 model owned by `shop_arena.env_eval.metrics`.
Top-level shape:

```jsonc
{
  "version": "0.3",
  "shop": {
    "url": "https://example-shop.com",
    "domain": "example-shop.com",
    "eval_version": "0.1.2"
  },
  "pages": {
    "homepage":        {"status": "ok", "url": "/", "selected_by": "input"},
    "collection":      {"status": "ok", "url": "/collections/men", "canonical_url": "/collections/<*>", "selected_by": "first_href"},
    "product":         {"status": "ok", "url": "/products/linen-shirt", "canonical_url": "/products/<*>", "selected_by": "first_href"},
    "policy":          {"status": "ok", "url": "/policies/privacy-policy", "canonical_url": "/policies/<*>", "selected_by": "convention"},
    "cart_and_search": {"cart": {"status": "ok", "url": "/cart"}, "search": {"status": "ok", "url": "/search?q=linen%20shirt", "query": "linen shirt", "selected_by": "product_title"}}
  },
  "observation": {
    "node_count": 2432,
    "interactive_count": 380,
    "distinct_node_count": 861,
    "max_depth": 15,
    "semantic_max_depth": 9,
    "content_character_count": 8124,
    "rubric": {
      "nav": 5, "hero": 2, "product_card": 24,
      "cta_button": 9, "footer": 5, "other": 0
    }
  },
  "action": {
    "click": 156, "fill": 5, "hover": 20,
    "select_option": 2, "scroll": 5,
    "choice_target_count": 7,
    "semantic": {
      "search": 4, "filter": 6, "goto_home": 0,
      "goto_collection": 3, "goto_product": 8,
      "goto_policy": 1, "goto_cart": 2,
      "open_cart": 1, "explore": 10
    }
  },
  "transition": {
    "node_count": 14, "edge_count": 22,
    "state_node_count": 4,
    "avg_out_degree": 1.57, "max_out_degree": 6,
    "dead_end_count": 2,
    "diameter": 4,
    "reachable_pct_from_homepage": 0.93,
    "homepage_to_cart_min_clicks": 2
  },
  "artifacts": {
    "observation_dir": "observation/",
    "action_dir": "action/",
    "transition_graph": "transition/graph.json"
  }
}
```

The schema is **closed** (`model_config = ConfigDict(extra="forbid")`)
so drift is loud. Field additions are allowed only with an `eval_version`
bump and a matching schema update; any rename or removal bumps to `1.x`.
Unavailable sample entries use an explicit closed status object instead of
zeroed metrics, e.g. `{"status": "not_found", "reason": "no_product_link"}`.
The `observation` and `action` blocks are website-level aggregates over
captured transition graph nodes. They intentionally do not duplicate per-page
or per-node measurements. Detailed node records stay in `observation/index.json`,
`action/index.json`, and the node-stemmed artifacts those indexes reference.

### 5.9 CLI surface

```
shop-env-eval run <url> [--out PATH] [--max-hops N]
                        [--rubric-model M]
                        [--pages-classifier-model M]
                        [--no-rubric]
                        [--rediscover]

shop-env-eval visualize <run_dir> [--out PATH]

shop-env-eval compare <url> <url> [<url> ...] [--out PATH]
```

- `run` measures one shop. `compare` runs that measurement for a URL cohort
  and derives deterministic structural snapshots and pairwise distances;
  its contract is defined in `structural_variance.md`.
- `visualize` reads `<run_dir>/transition/graph.json` and writes a
  self-contained interactive HTML page (vis-network from CDN) to
  `<run_dir>/transition/graph.html` (or `--out PATH`). Seeds, discovered
  URL nodes, and stateful state nodes are color-coded; edges carry the
  pipeline's `click(...)` / `fill(...)` labels as tooltips. Output is
  byte-stable for fixed inputs.

Library equivalent:

```python
from shop_arena.env_eval import evaluate, EvalConfig

result = evaluate(EvalConfig(url="https://example-shop.com"))
print(result.metrics.transition.diameter)
```

### 5.10 BrowserGym task + module layout

EnvEval uses BrowserGym through a minimal task wrapper instead of
AgentLab/Study. `EnvEvalBrowserTask(AbstractBrowserTask)` accepts the
shop's homepage URL, navigates to it during setup, exposes no validation
goal, and lets BrowserGym produce the observation (`screenshot`,
`axtree_object`, DOM metadata, URL). The task is constructed **once per
run**; the pipeline drives subsequent sample URLs by calling
`page.goto()` on the same Playwright `Page` rather than tearing down and
re-creating the env. This keeps EnvEval on the same observation/action
surface as ShopGuru agents without adding an agent loop.

Implementation adds `browsergym==0.14.3` (or the repo-pinned compatible
version) to `packages/shop_arena/pyproject.toml`.

```
packages/shop_arena/src/shop_arena/env_eval/
├── __init__.py            # public re-exports: evaluate, EvalConfig, EvalResult,
│                          # render_graph_html
├── cli.py                 # thin argparse → run/visualize dispatch
├── config.py              # EvalConfig, EvalResult (pydantic v2)
├── env.py                 # EnvEvalBrowserTask + BrowserGym env factory
├── errors.py              # EnvEvalError + typed subclasses
├── pages.py               # 5-bucket page discovery (BrowserGym-driven)
├── pipeline.py            # evaluate() — orchestrates the three layers
├── resume.py              # artifact-existence checks; no global cache
├── action/
│   ├── __init__.py        # re-exports ACTION_SUBSETS, HEURISTIC_VERSION,
│   │                      # ROLE_TO_ACTIONS, compute_action_space, …
│   └── heuristic.py       # HighLevelActionSet vocabulary + role/action heuristic
├── observation/
│   ├── __init__.py
│   ├── axtree_text.py     # deterministic text rendering for debug artifacts
│   ├── axtree_stats.py    # role-counted statistics from BrowserGym axtree
│   ├── rubric.py          # LLM screenshot categorizer (closed enum)
│   └── prompt.md          # rubric prompt (importlib.resources)
├── transition/
│   ├── __init__.py
│   ├── bfs.py             # structural href BFS + URL canonicalization
│   ├── canonicalize.py    # URL canonicalization helpers
│   ├── graph.py           # graph + metric computation
│   ├── rules.py           # closed rule list (versioned)
│   └── stateful.py        # fixed-rule in-page state attempts
├── schema/                # published-artifact schemas (metrics.json + manifest.json)
│   ├── __init__.py
│   ├── _digest.py         # shared closed-schema walker
│   ├── manifest.py        # Manifest pydantic model
│   └── metrics.py         # Metrics pydantic model
├── visualize/             # HTML visualizations of run artifacts
│   ├── __init__.py
│   └── transition_graph.py  # render_graph_html(...) for transition graph
└── py.typed
```

Modules shared across `shop_arena` CLIs (e.g., the provider-agnostic
vision LLM client used by both EnvEval and ShopGuru) live under
``shop_arena.util`` (e.g., ``shop_arena.util._llm``) rather than inside
``env_eval/`` so they can be reused without a circular dependency.

Tests live under `packages/shop_arena/tests/env_eval/`:

- `test_pages_*` — discovery rules against recorded fixtures.
- `test_axtree_stats_*` — statistic correctness on hand-crafted
  axtrees.
- `test_rubric_*` — schema-closed prompt parsing (LLM stubbed).
- `test_action_*` — action-space vocabulary + role/action heuristic on fixture observations.
- `test_transition_bfs_*` — canonicalization + BFS termination.
- `test_transition_stateful_*` — rule application against fixture
  states.
- `test_metrics_schema_*` — round-trip + closed-extra rejection.
- `test_resume_*` — artifact-existence reuse and run/reuse accounting.
- `test_evaluate_replay` — full pipeline on a recorded fixture run
  (no live browser, no live LLM).

---

## 6. Alternatives

**A. Reuse `shop_arena.explore.prefetch` for page selection.** Rejected
per design call: EnvEval is decoupled from explore so it can run on
shops that have no manual yet, including freshly generated SandboxShops
and arbitrary live URLs.

**B. Pure structural BFS with no stateful pass.** Rejected: misses
cart-drawer, search-overlay, and variant-picker transitions, which are
the most RL-relevant edges. The fixed-rule stateful pass adds them at
predictable cost.

**C. Free-form LLM-driven exploration for the transition graph.**
Rejected for v0.1: too non-deterministic to compare across shops or
across re-runs of the same shop. The fixed-rule list keeps the graph
metric a stable yardstick.

**D. Composite quality score.** Rejected for v0.1: domain-specific
weights are premature. Raw metrics let downstream consumers
(SandboxShop builder, RL infra team) define their own scores from the
same numbers.

**E. Multi-viewport / mobile pass.** Deferred. v0.1 measures the
desktop env an agent will train on first; mobile is a v0.2 spec.

**F. Use `agentlab.Study` to drive measurement.** Rejected: Study is
designed for many-trial agent evaluation. EnvEval needs a single
measurement pass per shop with no agent in the loop.

**G. Global content-addressed cache.** Rejected for v0.1: the run
directory itself is the cache. If an artifact exists, the corresponding
step is skipped; if users need freshness, they use a fresh `out_dir` or
delete stale artifacts.

**H. Fresh BrowserGym env per measured page.** Rejected: it pays a
browser-startup tax (~1–2 s × 6 buckets) on every run with no artifact
or determinism benefit, since each `page.goto()` already replaces the
DOM/axtree/screenshot for the next bucket. v0.1 holds one env open for
the whole run (§5.3, §5.10) and lets the run directory be the only
reuse boundary.

---

## 7. Milestones

**M1 — Page selection + observation layer.** `evaluate()` discovers
the five buckets via browsergym, captures screenshots + axtrees,
computes axtree stats, and writes `observation/*` plus an aggregate
`metrics.json`. LLM rubric is stubbed (returns empty). Deliverable:
`shop-env-eval run <url> --no-rubric` works end-to-end on a fixture.

**M2 — LLM rubric.** Implement the closed-enum screenshot prompt and
schema-validated parsing. Deliverable: aggregate `metrics.observation.rubric`
populated from node-level rubric artifacts; LLM artifacts are reused on a
second invocation against the same `--out`.

**M3 — Action layer.** Load `HighLevelActionSet` for the vocabulary, apply
the EnvEval role/action heuristic per graph node, and write `action/*`.
Deliverable: aggregate raw and semantic `metrics.action` counts.

**M4 — Transition graph (BFS).** Implement URL canonicalization and
bounded BFS with global cap. Deliverable: `transition/graph.json` with
href-only edges + structural metrics in `metrics.transition`.

**M5 — Stateful pass.** Implement fixed-rule attempts with axtree-diff
state detection and LLM state-naming. Deliverable: state nodes in the
graph, `homepage_to_cart_min_clicks` populated.

**M6 — Resume + manifest.** Artifact-existence reuse with run/reuse
accounting in `manifest.json`. Deliverable: SC4 passes for a second
invocation against the same `--out` (zero browser/LLM work for reused
steps).

**M7 — (removed).** The original generic metrics aggregation proposal was
removed. The later, narrower URL-only structural comparison is specified in
`structural_variance.md`; arbitrary cohort aggregation remains downstream.

**M8 — v0.1.0.** README, CLI help, module CHANGELOG, docs/specs index
updated. Tag `shop-env-eval-v0.1.0`.

**M10 — v0.1.1 / metrics v0.2.** Add `semantic_max_depth` to the
observation schema so cohorts can compare meaningful AXTree nesting without
theme wrapper/text-node inflation.

**M11 — v0.1.2 / metrics v0.3.** Skip hidden AX nodes in action-space
target counts, add `by_category.choice` to action artifacts, and expose
aggregate `metrics.action.choice_target_count` so choice/control richness
does not depend on whether a storefront implements variants/filter/sort as
native selects, radios, checkboxes, or popup buttons.

---

## 8. Appendix

### 8.1 Public surface (informative)

- **Types**: `EvalConfig`, `EvalResult`, `CompareConfig`, `CompareResult`.
- **Schemas** (`shop_arena.env_eval.metrics`): `Metrics`, `Observation`,
  `Action`, `Transition`, `AxtreeStats`, `Rubric`.
- **Functions**: `evaluate(config) -> EvalResult`,
  `compare_urls(config) -> CompareResult`,
  `render_graph_html(run_dir, out_path=None) -> Path`.
- **Errors**: `ShopUnreachableError`, `PageDiscoveryError`,
  `MetricsValidationError`, `ResumeError`, `StructureComparisonError`.

### 8.2 Open questions

1. **Rubric category list.** The v0.1 enum (§5.3) is opinionated and
   shopify-flavored. A v0.2 review pass after running on ~30 shops
   should adjust. Field-additive within `0.x`.
     - A: shopify flavored is fine, but don't assume any data available via public rest apis (e.g. products.json) as they won't work on sandbox shops
2. **Stateful rule list.** Same — v0.1 list is opinionated; expand
   only if a missing rule changes a `metrics.transition` number we
   care about for a real cohort.
3. ~~Should generic comparison diff raw artifacts?~~ Resolved by the narrower
   structural comparison in `structural_variance.md`, which reads canonical
   graph and accessibility-tree artifacts.
4. **Should EnvEval reuse `shop_guru.eval.run`'s subset choice
   (`("chat","infeas","bid","nav","tab")`) or expose its own flag?**
   v0.1 hard-codes the same subset for parity; consider exposing
   `--action-subsets` if a downstream caller diverges.
     - A: Expose its own flags you see fit
5. **Aggregate weights.** Per design call (4a), no composite score in
   v0.1. If demand emerges, v0.2 can layer a weights YAML on top of
   the same artifacts without touching the schema.

### 8.3 Future directions (non-blocking)

- **Mobile viewport pass.** Second sample sweep at 390x844 producing a
  `metrics.observation_mobile` block.
- **Composite RL-fitness score.** Weights YAML compiled into a single
  number per shop, calibrated against agent training results.
- **Time-series eval.** Keep N most-recent runs per shop and report
  drift on `metrics.transition.node_count` etc. Useful for monitoring
  generated SandboxShops as the build pipeline evolves.
