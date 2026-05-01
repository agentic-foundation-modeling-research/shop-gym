# ShopProbe (`packages/shop_arena/src/shop_probe`)

Status: **Spec (proposed)** · Version: **1.0**
Owners: ShopGym
Last updated: **2026-04-30**

> **A website is an MDP — measure the MDP.** ShopProbe scores the
> structural fidelity between SandboxShops and real storefronts
> by independently measuring each component of the agent's MDP:
> what the agent **observes**, what **actions** are available, and what
> **transitions** those actions produce.

---

## 1. Overview

ShopProbe answers one operational question: **are SandboxShops
realistic enough that an agent's behaviour transfers between them
and real storefronts?** Transfer requires similarity in the three
components that determine agent behaviour — the components of the
underlying MDP:

- **Observation** — what the agent perceives without acting.
- **Action** — what the agent can do.
- **Transition** — what happens when the agent acts.

ShopProbe v1.0 is the measurement instrument for these three
components. Each rubric entry is tagged with the family it measures
(`observation` / `action` / `transition`), keyed on a fixed set of
canonical **page types** (`homepage`, `collection`, `product`, `search`,
`cart`). For `observation` and `action`, every entry is computed over
one or both **modalities** the agent might consume — the
**accessibility tree** (text-based agents) and the **screenshot**
(vision agents) — so a fidelity claim made here generalizes across
agent architectures rather than pinning the rubric to one
observation modality.

ShopProbe operates against any deployed URL — sandbox or real — and
emits a typed `ProbeReport` per shop. Cohort-level fidelity is the
headline metric and answers three independent claims, one per family:

1. *Observation fidelity* — sandbox shops present pages of similar
   shape and content (per modality) to real shops.
2. *Action fidelity* — sandbox shops expose the same canonical
   actions, with comparable findability properties.
3. *Transition fidelity* — sandbox shops respond to canonical actions
   the same way real shops do.

These three together compose the transfer claim without
relying on a single, rubric-shaped checklist.

---

## 2. Terminology

| Term | Meaning |
| --- | --- |
| Target | One deployed storefront URL plus its `(name, label)` identity. Labels are `sandbox` or `real`. May carry an optional `data_dir`. |
| Benchmark | A YAML file listing two flat groups of targets (`sandboxes:` and `reals:`) — the input to `shop-probe eval`. |
| Page type | One of the five canonical page surfaces an agent encounters: `homepage`, `collection`, `product`, `search`, `cart`. |
| Modality | The agent's observation channel: `a11y` (accessibility tree) or `screenshot` (rendered pixels). Family-`transition` entries are modality-agnostic. |
| Family | One of `observation`, `action`, `transition` — corresponds to a component of the agent's MDP. |
| Slot | A canonical, page-type-specific item the rubric checks for: an information slot (e.g. *PDP price*) or a control slot (e.g. *PDP add-to-cart*). |
| Probe | The runner that produces a slot's verdict. Three runner kinds: `mechanical` (deterministic measurement), `judge` (one LLM call over a single modality), `scripted` (a Playwright interaction). |
| Rubric | The closed set of slots, content-addressed by SHA-256. Pinned to one version. |
| ProbeReport | The closed Pydantic schema written per target under `<out>/reports/<label>__<name>.json`. |
| BenchSummary | The cohort-level rollup written under `<out>/figures/`, comparing sandbox-vs-real distributions per family. |

---

## 3. Current Status

ShopProbe v0.4 ships a 75-entry rubric over three loosely-defined axes
(`probe`, `capture_judge`, `scale`) bucketed by 11 cross-cutting
categories (`a11y`, `cart`, `dynamics`, …). End-to-end runs against
the demo benchmark (3 sandbox + 5 real) succeed; the full pipeline,
caching, and figure generation are operational.

For the transfer claim, v0.4 has four blocking limitations:

1. **HTML-shaped, not agent-shaped.** Most probes assert specific CSS
   / ARIA selectors (`<header>`, `<h1>`, `[class*="quantity"]`).
   Storefronts with custom markup that an agent can still navigate
   (e.g. `aloyoga`) score near-zero on entire categories — a probe
   artifact that biases the headline coverage and is the dominant
   source of variance in the real cohort.
2. **Static presence, not affordance / dynamics.** Probes ask "does
   this element exist?" rather than "can the agent find and act on
   it?" or "does acting on it produce the expected effect?" This is
   the wrong shape for a benchmark that claims agent transfer.
3. **Cross-cutting categories are not MDP components.** Categories
   like `a11y`, `dynamics`, `floating`, `i18n` mix concerns and do not
   map onto anything the agent's behaviour depends on. The category
   axis cannot support a structured fidelity claim.
4. **Single modality, no multimodal future.** The capture-judge tier
   is implicitly visual; deterministic probes are HTML-only. Vision
   agents and text agents are not separately measurable, so the rubric
   cannot make modality-specific claims.

Empirically: of 69 enabled probes, 18 (26%) are non-discriminating
(13 universally fail across all 8 shops, 5 universally pass), and the
headline `coverage_weighted` shows sandbox > real (0.528 vs 0.421) —
the wrong direction, driven entirely by Dawn-shaped selectors that
favour the sandbox templates. The result is unsuitable as a fidelity instrument as-is.

---

## 4. Desired Status

After v1.0:

- Every rubric can rerun separately; rerun of the full eval suite 
  will skip completed rubrics.
- Every rubric entry maps to exactly one MDP component
  (`observation`, `action`, `transition`).
- Every entry on `observation` or `action` is tagged with at least one
  modality (`a11y`, `screenshot`); entries that should hold across
  modalities are run on both, and a **cross-modal consistency** score
  is reported as a first-class fidelity property.
- The page-type axis (`homepage`, `collection`, `product`, `search`,
  `cart`) replaces the cross-cutting categories. Per-page-type
  fidelity is the unit of analysis.
- Selector-style assertions survive only where they are genuinely
  unambiguous (e.g. `cart.page` returns 2xx). Affordance presence is
  judged from the agent's actual observation (a11y tree or
  screenshot), neutralizing custom-markup bias.
- The cohort report exposes three independent fidelity claims —
  observation, action, transition — each with a single headline number
  per family plus a per-page-type breakdown.
- The cohort report uses **distributional tests** (Mann-Whitney +
  Cliff's δ + per-shop z-scores against the real IQR) on continuous
  metrics, and **real-cohort majority baseline coverage** on binary
  slots, replacing the v0.4 min-max envelope and weight-summed coverage.

---

## 5. Proposal

### 5.1 Page types

Five canonical page types, sampled deterministically per shop:

| Page type | Sample size |
| --- | --- |
| `homepage` | 1 |
| `collection` | 5 (deterministic stratified sample from catalog) |
| `product` | 5 (deterministic stratified sample from catalog) |
| `search` | 1 (canonical query, e.g. brand name; one variant for `no-results`) |
| `cart` | 1 (after one scripted ATC) |

Sampling is deterministic via a per-target RNG seed, so the same shop
yields the same five collections / five PDPs across runs — necessary
for the cache to hit and for cohort figures to be reproducible.

### 5.2 Three families

For each `(shop, page_type)` and (where applicable) each modality, the
rubric produces three blocks of measurements.

#### Family `observation` — what the agent perceives without acting

Two subfamilies:

**`observation.shape`** — mechanical, deterministic, no LLM. Captures
the *shape* of the agent's observation. Per modality:

| Modality | Metrics |
| --- | --- |
| `a11y` | `nodes`, `tokens`, `landmark_count`, `heading_outline_depth`, `actionable_count`, `unique_role_name_rate`, `visible_text_tokens`, `external_link_ratio`, `time_to_stable_dom_ms`, `modal_on_first_paint` |
| `screenshot` | `megapixels`, `distinct_ui_regions`, `ocr_token_count`, `mean_text_height_px`, `contrast_p10`, `modal_area_pct`, `time_to_first_stable_paint_ms` |

These produce continuous distributions over the page-type sample.
Compared cohort-vs-cohort with Mann-Whitney + Cliff's δ.

**`observation.info_slots`** — judge over a single modality. A small
set of canonical *information* slots per page type. Each slot is
judged twice (once on `a11y`, once on `screenshot`); the verdict is
binary per modality plus a `cross_modal_consistent` derived flag.

| Page type | Information slots |
| --- | --- |
| `homepage` | brand identity · primary nav labels · hero / value prop · featured-content area · footer info |
| `collection` | product list (≥k items) · per-item name · per-item price · per-item image · per-item PDP link · result count · breadcrumb |
| `product` | title · price · gallery image(s) · description · breadcrumb · brand · stock status · variant options visible · ratings/reviews · recommendations |
| `search` | query echo · result count · results list · no-results state |
| `cart` | line items (name + image + price + qty) · subtotal/total · line count · empty-state |

Each slot is judged with a fixed prompt template (`prompts/info_slots/<slot>.md`)
that takes a single-modality input — the trimmed a11y JSON or the
page screenshot — and emits `{present: bool, name_used: str | null,
evidence_locator: str | null}`. Same prompt structure across modalities;
only the input changes. This is what neutralizes the custom-markup bias.

#### Family `action` — what the agent can do

Two subfamilies, mirroring `observation`.

**`action.space`** — mechanical, deterministic. Properties of the
action space exposed on the page, per modality:

| Modality | Metrics |
| --- | --- |
| `a11y` | `actionable_count` (links + buttons + role-button + role-link + inputs), `unique_role_name_rate`, `name_token_length_p50`, `name_token_length_p90`, `keyboard_focusable_count` |
| `screenshot` | `button_shaped_region_count`, `clickable_density_per_kpx2`, `text_on_button_ocr_rate`, `mean_button_area_px2` |

**`action.control_slots`** — judge over a single modality. Canonical
*controls* per page type:

| Page type | Control slots |
| --- | --- |
| `homepage` | nav→collection · search-entry · cart-entry |
| `collection` | click-product · filter · sort · paginate |
| `product` | select-variant · change-qty · add-to-cart |
| `cart` | edit-qty · remove · checkout · apply-promo |
| `search` | submit-query |

Same prompt structure as `observation.info_slots` — judge per modality,
emit `{present, name_used, evidence_locator}`. The split rule is:
information goes in `observation`, controls go in `action`. Items that
are dual (e.g. variant options — visible information *and* a
selectable control) are judged in `action` because the property the
matters is whether the agent can act on them.

#### Family `transition` — what happens when the agent acts

Modality-agnostic. For each control slot in `action.control_slots`, a
scripted Playwright probe attempts the action via a role+name locator
(the same way an agent would) and records four bits:

| Bit | Meaning |
| --- | --- |
| `action_found` | Locator resolved deterministically. |
| `action_executed` | Click / fill / select completed without error. |
| `state_changed` | A measurable observation delta was detected (URL, page-type classifier, cart-count token, line-item count, toast text). |
| `state_changed_as_expected` | The delta matches the action's expected effect (e.g. ATC → cart count incremented; remove → line gone). |

Plus a `latency_ms` measurement. Scripted, deterministic, no LLM.

The list of canonical transitions per page type:

| Page type | Transitions |
| --- | --- |
| `homepage` | click `collection` link → land on collection |
| `collection` | click product card → land on PDP · apply filter → result count or URL changes · change sort → order changes · paginate → URL or list changes |
| `product` | select variant → price/sku/url changes · change qty → input value changes · add-to-cart → cart count or drawer or url changes |
| `cart` | edit line qty → subtotal changes · remove line → line gone · click checkout → url changes |
| `search` | submit query → results page · empty query → no-results state |

### 5.3 Modality and cross-modal consistency

Modality is a first-class dimension on `observation` and `action`.
Each rubric slot defaults to running on **both** modalities; the
runner picks per-modality based on slot config. The judge prompt is
modality-aware (`a11y` prompts include the trimmed a11y JSON; `screenshot`
prompts include the rendered image), but the schema is identical.

For each slot run on both modalities, the runner derives:

```
cross_modal_consistent = (verdict_a11y == verdict_screenshot)
```

Aggregated to per-shop **modality-consistency rate**:

```
mc_rate(shop) = mean over slots [ cross_modal_consistent ]
```

Real shops typically have lower `mc_rate` than naive sandboxes (custom
canvas heroes, image-only CTAs, etc. show in screenshot but not in
a11y). A sandbox with `mc_rate ≫ mc_rate_real` is *too clean* across
modalities — its own kind of unrealism, and a publishable diagnostic.

### 5.4 Per-shop output schema

```text
ProbeReport
├── target            : Target (name, base_url, label, data_dir?)
├── rubric_version    : str   (e.g. "1.0")
├── rubric_hash       : str   (sha256 hex of rubric.yaml)
├── runner_version    : str
├── runtime           : BrowserMeta
├── timestamp         : datetime (UTC)
├── pages             : tuple[PageSample, …]   (1 home + 5 col + 5 pdp + 1 search + 1 cart)
├── observation       : ObservationBlock
│   ├── shape         : { page_type → { modality → ShapeMetrics } }
│   └── info_slots    : { page_type → { slot_id → { modality → SlotVerdict } } }
├── action            : ActionBlock
│   ├── space         : { page_type → { modality → ActionSpaceMetrics } }
│   └── control_slots : { page_type → { slot_id → { modality → SlotVerdict } } }
├── transition        : { page_type → { transition_id → TransitionResult } }
├── modality_consistency : { page_type → float ∈ [0, 1] }
└── total_judge_cost_usd : float
```

`SlotVerdict = { present: bool, name_used: str | null, evidence_locator: str | null, judge_model: str, judge_cost_usd: float }`

`TransitionResult = { action_found: bool, action_executed: bool, state_changed: bool, state_changed_as_expected: bool, latency_ms: int, evidence_path: str | null }`

`ShapeMetrics` and `ActionSpaceMetrics` carry the continuous metrics
listed in §5.2 — exact fields enumerated in the Pydantic schema, all
optional (a metric absent on a particular modality is `None`).

### 5.5 Cohort report

`<out>/figures/` writes three rollup tables, one per family:

- `observation_fidelity.md` — per page type and modality:
  - shape: Mann-Whitney p, Cliff's δ, sandbox median vs real IQR for
    each metric.
  - info_slots: real-baseline coverage at k=⌈3/5⌉ (majority) and
    k=⌈4/5⌉ (near-universal); sandbox shops' coverage with bootstrap
    CI; real shops' leave-one-out baseline coverage.
- `action_fidelity.md` — same layout, on action.space and
  action.control_slots.
- `transition_fidelity.md` — per page type:
  - per-transition `(found, executed, state_changed,
    state_changed_as_expected)` rates, sandbox vs real, with χ² per
    bit.

Plus `summary.md` — three single-number headlines (one per family) and
a strip plot of per-shop totals.

The headline cohort-level metric per family:

```
RBC_majority(shop) = | { slot ∈ majority_baseline : shop passes slot } | / | majority_baseline |
```

where `majority_baseline = { slot : pass_rate_real(slot) ≥ 3/5 }`.
RBC is reported for every shop; the cohort claim is that
`mean(RBC_sandbox)` lies within the leave-one-out range
`[min, max] of RBC_real_LOO` per family.

### 5.6 Rubric format

A rubric is a YAML file with a `version` string and a list of
`entries`. Each entry carries a `family` discriminator that picks the
runner; the other fields depend on `family`:

```yaml
version: "1.0"
entries:

# observation.shape — mechanical, both modalities, on every page type
- id: observation.shape
  family: observation
  kind: shape
  page_types: [homepage, collection, product, search, cart]
  modalities: [a11y, screenshot]

# observation.info_slot — judge, one slot per entry
- id: observation.product.title
  family: observation
  kind: info_slot
  page_type: product
  modalities: [a11y, screenshot]
  prompt: prompts/info_slots/product_title.md
  description: |
    PDP exposes a clearly-identifiable product title.

# action.space — mechanical
- id: action.space
  family: action
  kind: space
  page_types: [homepage, collection, product, search, cart]
  modalities: [a11y, screenshot]

# action.control_slot — judge
- id: action.product.add_to_cart
  family: action
  kind: control_slot
  page_type: product
  modalities: [a11y, screenshot]
  prompt: prompts/control_slots/product_add_to_cart.md

# transition — scripted Playwright
- id: transition.product.add_to_cart
  family: transition
  kind: scripted
  page_type: product
  expected_change: cart_count_increment
  script: scripts/product_add_to_cart.py
```

The shipped rubric will live at
`packages/shop_arena/src/shop_probe/rubric/rubric.yaml`. The loader
hashes raw bytes; the digest is embedded in every report and is the
cache key.

### 5.7 What carries over from v0.4

- The capture infrastructure (`shop_probe.capture.bundle`) — already
  snapshots screenshot + DOM per canonical page; needs only an a11y
  tree dump (`page.accessibility.snapshot()`) added.
- The Playwright runner (`shop_probe.probes._runner`) — extends
  naturally to scripted transitions.
- The judge harness (Anthropic + OpenAI clients in
  `shop_probe.agent`) — retargeted at modality-specific inputs.
- The CLI shape: one `eval` subcommand, per-shop file cache, content-
  addressed rubric-hash invalidation.

What is removed:

- The `coverage_core` / `coverage_modern` / `coverage_advanced` tiers.
  Tier weighting was a v0.4 patch for "core matters more"; in v1.0,
  page-type and family already encode priority and tiers add nothing.
- The 11 cross-cutting categories (`a11y`, `dynamics`, `floating`,
  `i18n`, …). Every concern is reabsorbed under a page type and a
  family.
- The min-max **scale envelope**. Replaced by Mann-Whitney + Cliff's δ
  on the continuous metrics in `observation.shape` and `action.space`.
- **Catalog cardinality** as a fidelity metric (`catalog_products`,
  `catalog_collections`). Catalog size is a configurable generation
  parameter, not a fidelity property of a shop. Removed from the
  rubric. Demo benchmarks cap at 200 products / 20 collections.
- The 75-entry v3 rubric YAML. Replaced from scratch.

---

## 6. Alternative — keep v0.4's selector-first structure and patch

Rejected. The dominant problems with v0.4 (custom-markup bias,
binary-pass-fail collapse, category sprawl) cannot be fixed by adding
or removing probes. They are structural: a selector-shaped rubric
cannot make a modality-specific or transition-specific claim. The
incremental cost of v1.0 over a v0.5 patch is small (the capture
pipeline, runner, and judge harness all carry over), and the
incremental value is the entire fidelity headline.

---

## 7. Milestones

| Milestone | Output |
| --- | --- |
| **M1 — Page-type sampling** | Deterministic 1+5+5+1+1 sampler over a target's catalog (or, for real shops, sitemap heuristics). Adds `pages.yaml` config per benchmark. |
| **M2 — Observation.shape (mechanical)** | All `observation.shape` and `action.space` metrics computed per modality on the sampled pages. End-to-end Mann-Whitney + Cliff's δ rollup table. |
| **M3 — A11y-tree judge** | Modality-aware judge harness for `info_slots` and `control_slots` over `a11y`. ~30 slots × 12 pages × 8 shops per benchmark. |
| **M4 — Screenshot judge + cross-modal consistency** | Same slots run on `screenshot`. `mc_rate` rollup. |
| **M5 — Transitions** | All ~15 scripted transitions per shop. `transition_fidelity.md` rollup. |
| **M6 — Cohort report v1** | RBC + LOO + bootstrap CI; three per-family headline numbers + summary strip plot. Replaces `group_comparison.md` / `per_shop_table.md`. |
| **M7 — Migration cleanup** | Remove v0.4 rubric / category code paths; update CLI docs and README; archive v0.4 evidence layout under `docs/archive/`. |

---

## 8. Appendix

### 8.1 Layout

```
packages/shop_arena/src/shop_probe/
├── cli.py                  # `eval` subcommand, per-shop cache
├── report.py               # ProbeReport + ObservationBlock / ActionBlock / TransitionResult
├── targets.py              # Bench, Target schemas
├── bench.py                # benchmark.yaml loader
├── capture/                # 5-page screenshot + a11y + DOM bundle
├── pages/                  # canonical page-type sampler
├── observation/
│   ├── shape.py            # mechanical metrics, both modalities
│   └── info_slots.py       # judge runner over info slots
├── action/
│   ├── space.py            # action-space mechanical metrics
│   └── control_slots.py    # judge runner over control slots
├── transition/             # scripted Playwright transitions
├── judge/                  # Anthropic + OpenAI clients, modality-aware
├── rubric/                 # rubric.yaml + loader + schema
├── fidelity.py             # cohort rollup: RBC, LOO, Mann-Whitney, Cliff's δ
└── report_writer/          # observation_/action_/transition_fidelity tables
```

### 8.2 Cohort metric definitions

Given `n_real` real shops and a real-cohort majority quorum
`k = ⌈n_real / 2 + 1⌉` (default `3` for `n_real = 5`):

```
majority_baseline_F = { slot ∈ family F : pass_rate_real(slot) ≥ k / n_real }
RBC_F(shop)         = | { slot ∈ majority_baseline_F : shop passes slot } |
                    / | majority_baseline_F |
```

Per family `F`, the cohort report includes:

- `mean(RBC_F over sandbox shops)` with bootstrap-over-slots 95% CI
- `[min, max](RBC_F_LOO over real shops)` — the leave-one-out
  within-real envelope

Claim shape (per family):

> *"Sandbox shops cover X% of the real-cohort majority baseline on
> family F, within the real shops' own leave-one-out range
> [Y, Z]%."*

Continuous metrics (`observation.shape`, `action.space`): per metric,
report `(mean_real, IQR_real, median_sandbox, MannWhitneyU, p_value,
CliffDelta)`. Effect-size thresholds: `|δ| < 0.147` negligible,
`< 0.33` small, `< 0.474` medium, else large.

### 8.3 Verification commands

```bash
cd packages/shop_arena
uv run pyright src/shop_probe                       # 0 errors expected
uv run pytest tests/shop_probe                      # green

# Smoke run: produces N reports + per-family figures.
uv run --package shop-arena shop-probe eval \
    --benchmark outputs/shop_probe/benchmark.yaml \
    --out /tmp/sp_smoke

# Re-run is a full cache-hit; no LLM calls.
uv run --package shop-arena shop-probe eval \
    --benchmark outputs/shop_probe/benchmark.yaml \
    --out /tmp/sp_smoke
```

### 8.4 Open questions

- **Slot weighting.** Default is uniform within a family. We may
  need to weight controls (e.g. `add-to-cart`) higher than
  observations (e.g. `ratings`) for headline figures. Decide before
  M6; defer until rollups are inspected.
- **Visual judge model.** A11y judge is cheap; screenshot judge is
  ~5× more expensive per call. Prefer a single multimodal model
  (e.g. `openai:gpt-5`) for both modalities so cross-modal consistency
  is unbiased by judge identity. Validate with a small inter-judge
  agreement audit at M4.
- **Real-cohort size.** Demo benchmark has `n_real = 5`, leaving the
  RBC bootstrap CIs wide. Target `n_real ≥ 10` for headline runs.
  Real shop selection criteria (variety of theme, vertical, market)
  are out of scope here; tracked in
  `docs/specs/shop_arena/shop_explore.md`.
- **Authenticated / transactional probes.** v0.4's `--include-auth`
  flag is preserved at the CLI but currently unused; only the
  cart-checkout transition needs it, and the demo benchmark stops at
  `click checkout → URL changes`. Re-evaluate at M5.

### 8.5 Migration from v0.4

The v0.4 spec is at
[`docs/archive/specs/shop_arena/shop_probe_v0.4.md`](../../archive/specs/shop_arena/shop_probe_v0.4.md);
the v0.4 implementation plans at
[`docs/archive/impl/web_probe_implementation.md`](../../archive/impl/web_probe_implementation.md)
and
[`docs/archive/impl/web_probe_v2_capture_judge_implementation.md`](../../archive/impl/web_probe_v2_capture_judge_implementation.md).
The v0.4 `rubric/rubric.yaml` is retired; the new rubric is authored
from scratch under M3 / M4.
