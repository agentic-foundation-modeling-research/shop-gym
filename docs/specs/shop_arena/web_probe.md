# ShopProbe / `web_probe` (`packages/shop_arena/src/shop_probe`)

Status: **Spec (proposed)** · Version: **0.1**
Owners: ShopGym

> A reproducible measurement tool that scores any deployed
> Shopify-shaped storefront on three independent axes — **capability
> coverage**, **surface area**, and **agent indistinguishability** — to
> quantify the structural fidelity of a generated SandboxShop relative
> to its source storefront, and against external benchmark
> environments.

---

## 1. Overview

The ShopGym paper validates that SandboxShops are reliable proxies for
real storefronts using **behavioral fidelity** — agreement on a 108-task
instruction-following benchmark run on each (source, sandbox) pair.
That answer is necessary but not sufficient: a reviewer can ask whether
agreement on a fixed task set generalizes, or whether the sandbox is
just narrow enough to look the same on those specific tasks.

`web_probe` is the **structural fidelity** complement. It runs against
a deployed URL — sandbox or source — and emits a typed report that
quantifies the storefront on three orthogonal axes:

- **Axis A — Capability coverage.** Closed, versioned rubric of ~80
  programmatic probes ("does this storefront have predictive search,
  filter URL-state sync, accordion PDP description, …"). Deterministic
  Playwright probes. Per-category and weighted total. *Answers: does
  it have the modern-web features a real Shopify storefront has?*
- **Axis B — Surface area.** Quantitative crawl-derived metrics:
  distinct templates, interactables per template, forms/fields,
  routes, catalog combinatorics, DOM size. *Answers: is the
  action/observation space rich enough to be non-trivial for an
  agent?*
- **Axis C — Agent indistinguishability.** A blinded LLM judge over
  agent trajectories produced on each target, scoring whether the
  trajectory looks like it came from a real Shopify storefront.
  *Answers: from an agent's point of view, is the sandbox
  distinguishable from a real shop?*

Three independent axes converging on the same conclusion — sandbox
matches source — is the structural-fidelity claim that complements the
108-task behavioral result.

A secondary benefit is that `web_probe` ships *with* the paper as a
benchmark artifact: external researchers can run the same rubric
against their own storefronts or generated environments and get
comparable numbers.

---

## 2. Terminology

- **Target** — a deployed storefront under test. Identified by a base
  URL and a label (`sandbox/run123`, `source/1`, `mock_shop`, etc.).
- **Probe** — a single deterministic Playwright function that returns
  `{passed, evidence, details}` for one rubric leaf.
- **Rubric** — a versioned YAML file enumerating all probes, their
  category, weight, and level (`core` / `modern` / `advanced`). The
  rubric is the closed taxonomy the paper makes claims against.
- **ProbeReport** — closed pydantic JSON document emitted per target
  per run; combines axis A (probe results), axis B (surface metrics),
  and axis C (judge results) plus runtime metadata.
- **Trajectory** — saved evidence from one agent run on one target:
  screenshots, accessibility-tree snapshots, agent reasoning, network
  log, action trace.
- **Pair** — a (source, sandbox) tuple. ShopGym v1 generates 3 pairs;
  pair-level fidelity is the headline metric.
- **Cohort** — the full set of targets compared in the paper:
  3 sandbox + 3 source + 2–3 prior-work environments.
- **Coverage** — axis A rubric score, ∈ [0, 1].
- **Surface** — axis B raw counts, no normalization implied.
- **Indistinguishability** — axis C judge accuracy at the pairwise
  task; 0.5 = chance (= indistinguishable).
- **Fidelity** — pair-level summary across the three axes; reported as
  three numbers, not collapsed to one (see §5.7).

---

## 3. Current Status

- `shop_explore` emits `manual/capabilities.json` (closed v0.1 schema,
  ~33 leaves). It is **content extraction for the manual pipeline**,
  not a measurement instrument: flags are LLM-synthesized from
  prefetch + browser snapshots, scoped to the ShopArena generation
  rubric, and not designed to be diffed across targets.
- `shop_gen` consumes those manuals and produces `shop_backend`-hostable
  SandboxShops + a Hydrogen/React frontend. The deployed sandbox
  serves real HTML over HTTP, indistinguishable in shape from a Shopify
  storefront.
- ShopGuru produces a 108-task instruction-following benchmark. Run on
  both source and sandbox, this gives **behavioral fidelity**. No
  structural fidelity instrument exists today.
- No reproducible probe runner. No judge protocol. No cohort baseline
  against prior-work environments (WebShop, Mock Shop, WebArena
  shopping).

---

## 4. Desired Status

A small Python module — `packages/shop_arena/src/shop_probe` (sibling to
`shop_gen` and `shop_explore` inside the `shop-arena` distribution) —
exposing one CLI:

```bash
shop-probe run <base_url> \
  --label sandbox/run123 \
  --rubric v1 \
  --axes A,B,C \
  --judge claude-sonnet-4-5 \
  --out reports/sandbox_run123.json
```

That command:

1. Drives Playwright through every probe in `rubric/v1.yaml` against
   the URL, saving per-probe evidence.
2. Crawls a fixed-depth subset of the storefront and computes
   axis-B surface metrics.
3. (If `C` enabled) Runs an agent harness over a fixed task list
   against the URL, saving Trajectories; later, the same CLI in
   `judge` mode consumes paired trajectories from a sandbox/source
   pair and emits indistinguishability scores.
4. Emits one `ProbeReport` JSON validated against a closed pydantic
   schema, plus an `evidence/` subtree.

A second command aggregates reports across the cohort and emits the
paper figures:

```bash
shop-probe report \
  --cohort cohort.yaml \
  --out figures/
```

The tool is **deployment-agnostic** — it takes a URL and assumes a
Shopify-shaped storefront (`/`, `/collections/*`, `/products/*`,
`/cart`, `/search`, `/policies/*`, `/pages/*`). It does not know
whether the target is a real Shopify shop, a SandboxShop served by
`shop_backend`, or another vendor's storefront.

---

## 5. Proposal

### 5.1 Package layout

```
packages/shop_arena/
  pyproject.toml                # shared with shop_gen / shop_explore
  src/shop_probe/
    __init__.py
    cli.py
    config.py
    targets.py                  # Target, Cohort schemas
    report.py                   # ProbeReport closed pydantic schema
    fidelity.py                 # per-pair fidelity aggregation
    rubric/
      v1.yaml                   # frozen, hashed
      schema.py                 # RubricEntry pydantic model
      loader.py
    probes/                     # axis A
      _runner.py                # Playwright orchestration
      site_shell.py
      homepage.py
      collection.py
      product.py
      search.py
      cart.py
      i18n.py
      floating.py
      dynamics.py
      a11y.py
      media.py
    surface/                    # axis B
      crawler.py
      metrics.py
    judge/                      # axis C (v1 = pairwise only)
      tasks/v1.yaml             # ~10 tasks, versioned
      agent.py                  # harness plan/exec loop wrapper
      trajectory.py             # closed pydantic schema
      pairwise.py               # blinded A/B judge
      prompts/v1/
        pairwise.md
        system.md
    report_writer/
      figures.py                # radar, bar, scatter, Turing chart
      tables.py                 # per-pair fidelity table
  tests/
```

`web_probe` ships as a **sibling module of `shop_gen` and `shop_explore`**
inside the `shop-arena` distribution (it shares `pyproject.toml` with them
and exposes the `shop-probe` console script). Earlier drafts placed it as
a standalone `packages/shop_probe` package; the consolidation keeps the
`shop_arena` group of measurement / generation tools in one wheel without
changing the module-level boundary (`shop_probe.*` imports are unchanged).

### 5.2 Target & cohort

A target is a base URL + label + flags:

```python
class Target(BaseModel):
    label: str                  # "sandbox/hardware_run123", "source/hardware", "real/aloyoga"
    base_url: str
    kind: Literal["sandbox", "source", "real_unpaired"]
    pair_id: str | None         # set on `sandbox` and `source` rows that share a pair
    notes: str | None
```

The v1 cohort:

| Kind | Targets | Count |
|---|---|---|
| `sandbox` | SandboxShops served by `shop_backend`, each calibrated on one paired `source` | 3 |
| `source` | the production storefronts the sandboxes were calibrated on (hardware, hexclad, aloyoga) | 3 |
| `real_unpaired` | additional production storefronts with no corresponding sandbox; characterize the real-shop distribution | 3 |

Total: **9 targets** = 3 sandbox/source pairs + 3 unpaired real shops.

The 6 real shops together (3 paired sources + 3 unpaired) form a small **real-shop reference population**. Two methodological consequences flow from this:

- **Axes A & B — population baseline.** For each metric, we report not only `sandbox(i) vs source(i)` but also where the sandbox falls within the [min, max] envelope of all 6 real shops. The fidelity claim escalates from *"sandbox matches its source"* to *"sandboxes fall inside the natural variance of real Shopify storefronts"*.
- **Axis C — intra-real control.** The unpaired real shops let us run *control* trajectory pairs `(real_A, real_B)` through the same blinded judge as the *experimental* pairs `(sandbox, source)`. Control accuracy is the **noise floor**: if a judge picks one real shop as "synthetic" 60% of the time when forced to pick, then judge accuracy on experimental pairs is only meaningful relative to that floor. See §5.5 step 7 and §5.7.

Prior-work environments (Mock Shop, WebShop, WebArena-Shopping) are explicitly **out of v1** to keep the cohort focused on the per-pair and population fidelity claims; they may be added as a paper supplement (see §5.9).

### 5.3 Axis A — Capability coverage (rubric)

Rubric is a YAML file, frozen and hashed per version. Schema:

```yaml
- id: product.gallery.thumbnails
  category: product
  level: modern                       # core | modern | advanced
  weight: 2                           # 1..3
  probe: probes.product.gallery_has_thumbnails
  description: PDP gallery exposes a thumbnail strip that swaps the main image.
  authenticated: false
  transactional: false
```

v1 categories and target probe counts (auth + checkout omitted per
v1 scope):

| Category | Probes | Examples |
|---|---|---|
| `site_shell` | 8 | sticky header, mega menu, mobile drawer, footer groups |
| `homepage` | 7 | hero, feature grid, testimonials, multiple section types |
| `collection` | 10 | sidebar filters, accordion filters, sort popover, URL-state sync, active-filter chips, pagination/infinite-scroll/load-more |
| `product` | 14 | gallery type, image swap on variant, radio/swatch/dropdown selectors, qty spinner, accordion description, recommendations, reviews, breadcrumbs |
| `search` | 7 | header trigger, predictive listbox, grouped results, ARIA combobox, full results page, query echo, no-results state |
| `cart` | 6 | drawer vs page, line-item edit, qty change, promo code, AJAX badge update, empty state |
| `i18n` | 5 | locale switcher, currency switcher, market routing, language-filtered country list, translated copy |
| `floating` | 4 | cookie consent, age gate, newsletter popup, chat widget |
| `dynamics` | 8 | loading skeleton, toast/snackbar, optimistic update, debounced input, URL ↔ state sync, browser-back consistency, AJAX endpoints discoverable |
| `a11y` | 8 | combobox role, listbox role, dialog role + focus trap, live regions, skip-to-content, alt text coverage %, focus visible |
| `media` | 5 | lazy-load images, video on PDP, lightbox/zoom, swatch image swap, srcset/responsive |

**Total: ~82 probes** (~60 after dropping `level: advanced` for v1
scope; advanced probes ship in v1.1).

Score per category = `Σ weight·passed / Σ weight`. Weighted total =
weighted mean across categories. We additionally report
`coverage_core`, `coverage_modern`, `coverage_advanced` separately so
the paper can distinguish "every shop has this" from "modern 2025
sites have this."

Each probe:

- Has a hard timeout (default 10 s).
- Runs in an isolated Playwright context with a fixed viewport
  (1280×800), pinned UA, headless.
- Emits structured evidence: screenshot path, DOM-snapshot path, the
  CSS/role selector used to assert.
- Has retries=0 by default; flake is captured at the suite level via
  N=3 reruns (see §5.8 reproducibility).

### 5.4 Axis B — Surface area

A separate crawler walks the target up to a fixed depth (default
`depth=2` from the homepage, plus full enumeration of
`/collections/*` and a sampled `/products/*` set up to N=20) and
records:

```python
class SurfaceMetrics(BaseModel):
    distinct_templates: int           # by structural fingerprint
    routes_crawled: int
    interactables_per_template_median: float
    interactables_per_template_p95: float
    forms_total: int
    form_fields_total: int
    catalog_products: int
    catalog_collections: int
    catalog_variants: int
    filter_x_sort_state_space: int
    median_dom_kb_gz: float
    accessibility_nodes_per_template_median: float
```

Surface is **descriptive, not normative.** It is reported alongside
coverage but is not folded into the headline fidelity score (a tiny
catalog can still be high-fidelity). For pair-level fidelity (§5.7) we
report ratios `surface(sandbox) / surface(source)` per metric.

### 5.5 Axis C — Agent indistinguishability (judge)

v1 ships **one judge axis only**: blinded pairwise Turing with an intra-real control condition.

Pipeline:

1. **Tasks.** `judge/tasks/v1.yaml` enumerates ~10 tasks tuned for *judge diagnosticity* — visually rich, multi-page, interaction-heavy (e.g., *"filter the bestsellers collection by Product Type, open the third PDP, switch to a different variant, add 2 to cart, switch locale"*). These are **separate from the 108 ShopGuru benchmark tasks**, run on an independent agent invocation; see §5.5.1 for the rationale.
2. **Agent runner.** Wraps `packages/harness` plan/exec loop with a Playwright runtime against the target URL. Saves a `Trajectory`: ordered (action, observation, reasoning) tuples plus screenshots and accessibility-tree snapshots.
3. **Trajectory anonymization.** Strip URL, brand strings, theme identifiers, OG metadata, favicon, distinctive product names. Replace catalog identifiers with stable hashes. Keep only the structural and interactional surface visible to the agent.
4. **Pair construction.** Two pair populations are built per task:
   - **Experimental pairs** — one `(sandbox_i, source_i)` per pair_id (3 per task).
   - **Control pairs** — one `(real_a, real_b)` sampled without replacement from the 6 real shops (3 per task; mix paired-source and unpaired).
5. **Pairwise judge.** For each pair, present both trajectories to the judge in randomized A/B order with the prompt: *"One of these is from a real Shopify storefront, the other is synthetic; which is real?"* with required evidence citation. Note: **the prompt is identical for experimental and control pairs**, and the judge does not know which condition it is in. For control pairs, no answer is correct — the judge's pick distribution is the diagnostic.
6. **Position-bias check.** Re-run with A/B swapped. Drop pairs where the judge flips on swap. Report drop rate.
7. **Scoring.** Two numbers:
   - `judge_accuracy_experimental` — fraction of `(sandbox, source)` calls where the judge picks the source. Range [0, 1]; 0.5 is naively "indistinguishable".
   - `judge_accuracy_control` — fraction of `(real, real)` calls where the judge picks a designated "real" position consistently. Used as a **noise floor**: the meaningful indistinguishability claim is `|experimental − control| ≤ ε` rather than `experimental ≈ 0.5` in absolute terms.

v1 uses **one OpenAI flagship model** as judge (e.g., `gpt-5`, exact version pinned at run time and embedded in every report; temperature 0). Because ShopGym's generation pipeline is Claude-driven, a non-Anthropic judge is **cross-lab by construction** — this directly addresses the "judging Claude with Claude" critique without needing a multi-judge ensemble in v1. A second judge family (e.g., Claude or Gemini) for triangulation is deferred to v1.1 (see §5.9).

Required guardrails:

- Pin model + version + temperature in the report metadata.
- Save full prompt + full response per pairwise call.
- Force evidence citation: every "real / synthetic" call must cite specific screenshot indices or snapshot lines. Discard calls without evidence.
- Position-randomized + position-swapped re-run; drop unstable pairs.
- The agent and the judge use **distinct prompts and contexts** — never share state, never share model invocations.

#### 5.5.1 Why axis C uses a separate task list from the 108-task benchmark

The 108-task ShopGuru benchmark is the *behavioral fidelity* instrument and lives **outside** `web_probe`. Axis C is the *perceptual fidelity* instrument and lives **inside** `web_probe`. Reusing benchmark traces for the judge would couple these two instruments and create a confound: when an agent fails on the sandbox but succeeds on the source (or vice versa), the trajectory shapes diverge for reasons unrelated to the storefront's realism, and the judge picks up on the *failure pattern* rather than on the storefront. By running an independent task list with the same harness, the 108-task behavioral evaluation and axis C remain orthogonal in the paper. The agent *implementation* is shared; the *task list*, *invocation*, and *saved traces* are independent.

### 5.6 ProbeReport schema (closed)

```python
class ProbeResult(BaseModel):
    id: str
    passed: bool | None              # None = not_applicable
    evidence: list[EvidenceRef]
    notes: str | None
    duration_ms: int

class CategoryScore(BaseModel):
    category: str
    weight_passed: float
    weight_total: float
    coverage: float

class JudgeCall(BaseModel):
    task_id: str
    pair_label: tuple[str, str]      # (sandbox_label, source_label)
    judge_pick: Literal["A", "B", "abstain"]
    truth: Literal["A", "B"]
    swap_consistent: bool
    evidence_cited: bool
    confidence: float
    prompt_hash: str
    response_text: str

class ProbeReport(BaseModel):
    target: Target
    rubric_version: str
    rubric_hash: str
    runner_version: str
    runtime: BrowserMeta
    timestamp: datetime
    # Axis A
    probe_results: list[ProbeResult]
    categories: list[CategoryScore]
    coverage_core: float
    coverage_modern: float
    coverage_advanced: float
    coverage_weighted: float
    # Axis B
    surface: SurfaceMetrics
    # Axis C — pairwise lives at pair level, see PairFidelity below
    judge_calls: list[JudgeCall]     # empty for unpaired targets
    # Stability
    rerun_index: int
    flake_rate_per_probe: dict[str, float]
```

`extra="forbid"` everywhere; this is the contract the paper figures
read.

### 5.7 Per-pair fidelity

For each (source, sandbox) pair we report **three numbers, not one**, plus the cohort-level intra-real control:

```python
class PairFidelity(BaseModel):
    pair_id: str
    coverage_gap: dict[str, float]        # per-category, source - sandbox
    coverage_gap_weighted: float          # ∈ [-1, 1]; 0 = parity
    surface_ratio: dict[str, float]       # per-metric, sandbox / source
    surface_ratio_geomean: float          # geometric mean across metrics
    sandbox_in_real_envelope: dict[str, bool]  # per-metric: is sandbox(i) in [min, max] of 6 real shops?
    judge_accuracy_experimental: float    # fraction of (sandbox, source) calls picked correctly
    judge_n_pairs: int
    judge_dropped: int                    # swap-inconsistent or no-evidence

class CohortFidelity(BaseModel):
    pairs: list[PairFidelity]
    judge_accuracy_control: float         # intra-real noise floor; cohort-level, not per pair
    judge_indistinguishability_gap: float # mean(experimental) - control; 0 = indistinguishable
    real_shop_population: dict[str, tuple[float, float]]  # per-metric (min, max) over 6 real shops
```

Headline paper claim format (with placeholder numbers):

> Across 3 paired storefronts, ShopArena SandboxShops achieve a mean capability coverage gap of **−0.04** (sandbox slightly under source) and surface-area geometric mean ratio of **0.78**, with all 3 sandboxes falling inside the [min, max] envelope of 6 production Shopify storefronts on **9 of 11** surface metrics. A blinded GPT-5 judge picks the source over the sandbox at **0.56** (95% CI [0.50, 0.62]) — within ε = 0.04 of the **0.52** intra-real control accuracy on `(real, real)` pairs — making sandboxes statistically no more distinguishable from their source than two real Shopify storefronts are from each other.

Three numbers per pair plus one cohort-level noise floor. Each defensible on its own; collapsing to a single weighted score is rejected (see §6).

### 5.8 Reproducibility

- Pin Playwright + Chromium + Python versions in `pyproject.toml` and
  embed them in every report.
- Every probe and every prompt has a `version` and a content hash;
  hashes go into the report header.
- Rubric YAML is frozen per version. Changes bump the version; the
  paper cites a specific version.
- Run each target N=3 times; report `flake_rate_per_probe` and gate
  paper claims on flake < 1% per probe.
- Save **HAR captures** of every crawl so reviewers can re-score
  offline against frozen network responses if the live target
  changes.
- Save **all** screenshots and a11y snapshots — these are the
  evidence trail for both rules and judge.

### 5.9 What's intentionally **out** of v1

- **Auth probes** (login, signup, password reset, account pages). The rubric leaves the `authenticated: true` flag for v1.1.
- **Transactional probes** (checkout, payment, order confirmation). Same.
- **Quality-dimension Likert judge** (visual coherence, copy realism, error plausibility). Deferred to v1.1; pairwise + intra-real control carries the v1 judge claim.
- **Multi-judge ensemble.** v1 = one judge model (GPT-5). Cross-lab adversariality is already provided *by construction* because the generation pipeline is Claude-driven. A second judge family (Claude or Gemini) for triangulation is a v1.1 / supplement workstream.
- **Prior-work environment baselines** (Mock Shop, WebShop, WebArena-Shopping). Out of v1 cohort; can be added as a paper supplement table without re-running the per-pair primary results.
- **Human calibration of the judge.** Strongly recommended for a paper supplement (Spearman ρ between human and LLM judge over a ~50-trace subset) but tracked as a separate workstream — see §7 M7.
- **Performance probes** (LCP, INP, bundle size). Out of scope; not the fidelity question.

---

## 6. Alternatives considered

- **LLM-only evaluation (no rubric).** Rejected: not reproducible
  enough for a paper, hard to defend in review, brittle over model
  upgrades.
- **Rule-only evaluation (no judge).** Rejected: rules cannot detect
  copy-realism, coherence-across-pages, or "AI-shaped" UX. Misses
  the most interesting failure modes of generated content.
- **Reuse `shop_explore/capabilities.json`.** Rejected: that schema
  is content extraction for the manual pipeline, not measurement.
  Coupling the two would force one to evolve at the other's pace.
  Separate `web_probe` rubric, separate version, separate package.
- **Single collapsed fidelity score.** Rejected: hides which axis
  the sandbox fails on. Three numbers, reported separately, are
  easier to defend in review and more diagnostic for engineering.
- **Put `web_probe` inside `shop_arena`.** Rejected: different deps,
  different lifecycle, different consumers; sibling package per
  CLAUDE.md cohesion rules.
- **Multi-judge ensemble in v1.** Tempting for triangulation but unnecessary at v1: a single OpenAI judge against a Claude-driven generation pipeline is already cross-lab, which addresses the headline reviewer concern. The marginal value of a second judge is in calibration / sensitivity analysis, which fits a v1.1 / supplement workstream rather than blocking the primary result.
- **Reusing 108-task benchmark traces for the judge.** Tempting for cost reasons but rejected: behavioral and perceptual fidelity become correlated through shared traces (see §5.5.1). Independent task list, shared harness implementation.

---

## 7. Milestones

| ID | Deliverable | Gates |
|---|---|---|
| **M1** | Package skeleton; `Target`, `ProbeReport`, `RubricEntry` pydantic schemas; `rubric/v1.yaml` with 20 `core`-level probes (site_shell, collection, product, cart subset); CLI `shop-probe run` for axis A only; tests for rubric loading + report serialization. | Unit tests green; `shop-probe run --axes A` against a localhost SandboxShop produces a valid `ProbeReport`. |
| **M2** | Axis B: surface crawler + `SurfaceMetrics` schema; `shop-probe run --axes A,B`; cohort YAML + the 3 ShopArena pairs configured. | Surface metrics emitted for all 3 sandbox targets; values manually sanity-checked. |
| **M3** | Pilot run on 1 (source, sandbox) pair: full axis A + B; per-pair fidelity table for pair 1; identify rubric gaps and bump probe count toward 60. | One full pair report produced; gaps logged as v1.1 candidates. |
| **M4** | Axis C v1: agent runner wrapping harness plan/exec loop + Playwright; `Trajectory` schema; `judge/tasks/v1.yaml` with ~10 judge-diagnostic tasks (independent of ShopGuru benchmark tasks); blinded pairwise judge with one pinned OpenAI flagship model (e.g. `gpt-5`); position-swap stability check; intra-real control pair construction. | Pairwise judge runs on pair 1 with ≤5% swap-inconsistency rate; HAR captures + screenshots saved; control-pair construction validated against the 6-real-shop list. |
| **M5** | Full cohort run: 9 targets (3 sandbox + 3 paired source + 3 unpaired real). N=3 reruns of axes A and B; full pairwise judge across experimental and control pairs. Flake report. | All targets in `cohort.yaml` produce reports with `flake_rate < 1%`; control accuracy reported as the noise floor for axis C. |
| **M6** | Aggregation: `shop-probe report` emits per-pair fidelity table, radar chart of axis A (sandboxes overlaid on the real-shop envelope), surface bar chart with real-shop distribution shown as range bars, and Turing chart with experimental and control accuracies side-by-side and bootstrap CIs. | Figures 1–4 of the paper rendered from `cohort/` reports without manual editing. |
| **M7** *(stretch / v1.1)* | Second judge family (Claude or Gemini) for cross-judge agreement; Likert quality dimensions; ~50-trace human-judge calibration; prior-work envs as supplement. | Cross-judge κ reported; Spearman ρ between human and LLM judge reported per dimension. |

M1–M3 are the foundation and unblock paper figures for axis A and B.
M4–M5 unblock the Turing claim. M6 produces every paper figure
from versioned reports.

---

## 8. Appendix

### 8.1 Example probe (Python)

```python
# packages/shop_arena/src/shop_probe/probes/product.py
from __future__ import annotations
from playwright.async_api import Page
from shop_probe.probes._runner import ProbeContext, ProbeOutcome

async def gallery_has_thumbnails(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """PDP gallery exposes a thumbnail strip that swaps the main image."""
    await page.goto(ctx.sample_product_url, wait_until="domcontentloaded")
    thumbs = page.locator('[role="tablist"] [role="tab"], .product-gallery__thumbnail')
    n = await thumbs.count()
    if n < 2:
        return ProbeOutcome(passed=False, notes=f"only {n} thumbnails")
    main_before = await page.locator(".product-gallery__main img").get_attribute("src")
    await thumbs.nth(1).click()
    await page.wait_for_timeout(200)
    main_after = await page.locator(".product-gallery__main img").get_attribute("src")
    return ProbeOutcome(
        passed=main_before != main_after,
        evidence=[ctx.snapshot("after-thumb-click"), ctx.screenshot("after-thumb-click")],
        notes=None if main_before != main_after else "main image did not swap",
    )
```

### 8.2 Cohort YAML (sketch)

```yaml
version: 0.1
# Public-repo cohort uses *.example.invalid placeholders; the operator
# deployment substitutes the real merchant URLs at run time.
pairs:
  - id: pair_1
    source:  { label: source/1,  base_url: https://source-1.example.invalid }
    sandbox: { label: sandbox/1, base_url: https://shop-arena-<hash>-126018801413.us-central1.run.app }
  - id: pair_2
    source:  { label: source/2,  base_url: https://source-2.example.invalid }
    sandbox: { label: sandbox/2, base_url: TBD }
  - id: pair_3
    source:  { label: source/3,  base_url: https://source-3.example.invalid }
    sandbox: { label: sandbox/3, base_url: TBD }
real_unpaired:  # for population baseline (axes A, B) and intra-real control pairs (axis C)
  - { label: real/1, base_url: https://real-1.example.invalid }
  - { label: real/2, base_url: https://real-2.example.invalid }
  - { label: real/3, base_url: https://real-3.example.invalid }
```

### 8.3 Pairwise judge prompt (sketch)

```
SYSTEM
You are evaluating whether an agent trajectory was recorded on a real
Shopify-powered storefront or on a synthetically generated sandbox
storefront. You will see two trajectories executed against two
different storefronts on the same task. Exactly one is real; the
other is synthetic.

USER
Task: {task_description}

Trajectory A: {anonymized_trajectory_a}
Trajectory B: {anonymized_trajectory_b}

Decide which trajectory is from the real storefront. You MUST cite
specific screenshot indices or snapshot lines as evidence for every
factual claim. If you cannot cite evidence, output "abstain".

Respond as JSON:
{
  "pick": "A" | "B" | "abstain",
  "confidence": 0.0..1.0,
  "evidence": [
    {"trajectory": "A"|"B", "ref": "screenshot_07" | "snapshot_12:L34", "claim": "..."}
  ],
  "rationale": "..."
}
```

### 8.4 Paper figures sourced from `web_probe`

| Figure | Source axis | Description |
|---|---|---|
| Per-pair fidelity table | A + B + C | One row per pair, three numbers per row + cohort-level intra-real control row |
| Radar chart | A | Per-category coverage; the 6-real-shop envelope is shaded, sandboxes overlaid as polygons — visually answers "do sandboxes fall inside the real-shop distribution?" |
| Surface bar chart | B | Per-metric: sandbox value, source value, and the [min, max] range over the 6 real shops as a range bar |
| Turing chart | C | Experimental judge accuracy per pair AND intra-real control accuracy, with bootstrap 95% CIs; the relevant claim is `|experimental − control| ≤ ε`, not `experimental ≈ 0.5` |

### 8.5 Open questions (to resolve before M5)

Resolved:

- ~~Which 3 source storefronts are the v1 cohort?~~ → **decided; concrete URLs are kept out of the public repo and substituted at deploy time. Selection rationale: one Shopify-operated reference storefront, two heavily-customised merchant sites spanning theme/catalog/i18n axes.**
- ~~Where do prior-env baselines run?~~ → **Prior envs are out of v1**; supplement-only.
- ~~Is the judge agent the same as the 108-task benchmark agent?~~ → **Independent task list, shared harness implementation** (§5.5.1).
- ~~Cross-lab judge in v1.1 vs paper supplement?~~ → **GPT-5 is the v1 judge; cross-lab is satisfied by construction.** Second judge family is v1.1 (M7).

Closed in §8.6 (cohort v0.1):

1. **The 3 unpaired real shops.** Selection criteria: Shopify-powered, publicly browseable, span the theme/catalog/i18n space (one Dawn-based, one heavily customized, one with multi-market). Candidates need confirmation before M5.
2. **Bot detection on real merchant storefronts** (the two non-Shopify-operated paired sources, `source-2` / `source-3`). The Shopify-operated reference source (`source-1`) is unlikely to gate; merchant sites may serve different DOM to Playwright. Mitigation needs decision: (a) cooperating-merchant access, (b) residential proxy + slow probes + cached HAR, or (c) skip the merchant and pick alternates. Affects axes A and B for those targets.
3. **Sandbox URLs for `pair_2` and `pair_3`.** Only the `pair_1` sandbox is currently deployed. Need deployments for the other two before the cohort is complete.
4. **Anonymization sufficiency for axis C.** Whether structural-only anonymization is enough to defeat brand-recognition by a frontier judge model. If a small ablation shows the judge is using brand cues, anonymization rules need to be tightened before M5.

### 8.6 v0.1 cohort decisions

Closes the four §8.5 open questions for cohort version **0.1**. The
operative `cohort.yaml` ships with these decisions wired in;
`tests/test_cohort.py` validates structural invariants. Cohort version
bumps in lockstep with this section.

Concrete merchant URLs and pair identifiers are scrubbed in the public
repo and replaced with `*.example.invalid` placeholders and numeric
`pair_<n>` ids; the operator deployment maps the placeholders to the
real targets at run time.

#### 8.6.1 Three unpaired real shops (closes Q1)

**Decision.** The v0.1 unpaired-real population is

| Slot | Label | URL | Selection axis |
|---|---|---|---|
| Stock-leaning OS 2.0 / Dawn-derivative | `real/1` | https://real-1.example.invalid | "close-to-default Shopify shop"; smaller catalog. |
| Heavily customised | `real/2` | https://real-2.example.invalid | Shopify Plus; bespoke theme; AJAX-rich UX. |
| Multi-market | `real/3` | https://real-3.example.invalid | Hydrogen-based; locale switcher; multi-currency. |

These three together span the theme / catalog / i18n axes §8.5 Q1 calls
for and complement the three paired sources (`source-1.example.invalid`,
`source-2.example.invalid`, `source-3.example.invalid`) so the
6-real-shop reference population (§5.2) is balanced.

**Selection criteria.** Each row must be:

1. Shopify-powered (verified at M5 dry-run via the standard
   `cdn.shopify.com` asset signature on `/`).
2. Publicly browseable headlessly (no auth wall for `/`,
   `/collections/*`, `/products/*`).
3. Diverse on theme (Dawn-shaped vs. heavily customised) **and** on
   catalog combinatorics (small vs. large; single-market vs.
   multi-market).
4. Stable enough that re-runs across an N=3 reproducibility sweep
   produce flake < 1% per probe.

**Alternates** (used only if (1)–(4) fail on the M5 dry-run, in order):

1. Shopify Plus / heavy-customisation alternate. Replaces `real/2`.
2. Small-CPG / Dawn-shaped alternate. Replaces `real/1`.
3. Multi-market apparel alternate. Replaces `real/3`.

Any swap bumps the cohort version to **0.1.1** and updates this section
in lockstep.

#### 8.6.2 Bot-detection mitigation for `source-2` / `source-3` (closes Q2)

**Decision.** Apply §8.5 Q2 option **(b)** — residential proxy +
slowed probes + cached HAR — uniformly to both targets. Option **(c)**
(skip the merchant, pick alternates) is the documented fallback if
option (b) yields > 5% probe failure rate on the M5 dry-run.

| Lever | Configuration |
|---|---|
| Egress | Residential proxy (provider chosen at deploy time; pinned in `BrowserMeta.notes`). Probe traffic must look like a residential client, not a datacentre IP. |
| Pacing | `≥ 1 s` floor between probe requests on these two targets (overrides the 10 s timeout default; default 0 s pacing). |
| Caching | Mandatory HAR capture per crawl (already required by §5.8); HARs are persisted alongside per-run reports so reviewers can re-score offline if the live target later blocks. |
| User-Agent | Pinned via `BrowserMeta.user_agent` (default `ShopProbe/0.1 (Chromium/<version>)`). Not rotated — reproducibility beats stealth at v0.1. |
| Concurrency | The `source-2` and `source-3` probes run **serially** (one Playwright context at a time per target). |

**Why not option (a) — cooperating-merchant access?** v0.1 is an
open-source paper artifact; relying on merchant cooperation would make
the result non-reproducible by external researchers and would couple
ShopProbe to merchant SLA.

**Why not always option (c)?** `source-2` and `source-3` are the two
paired sources for `pair_2` and `pair_3` — swapping them would break
the `(source, sandbox)` calibration relationship that the sandbox
build pipeline depends on. Option (c) is reserved for the unpaired
population in §8.6.1.

**Acceptance.** The first dry-run records per-probe success rate
against `source-2` and `source-3`; if either exceeds 5% failure
attributable to bot blocking (HTTP 403 / interstitial DOM), the
cohort drops to fallback (c), the dropped target's pair is removed
from the M5 cohort, and a v0.1.1 revision documents the swap.

#### 8.6.3 Sandbox URLs for `pair_2` and `pair_3` (closes Q3)

**Decision.** Both sandboxes are pending `shop-gen` deployment. They
deploy the same way `pair_1`'s sandbox already deploys:

1. Run `shop-gen` against the source (one storefront at a time;
   produces `outputs/shops/mock_<n>/`).
2. Deploy the generated Hydrogen storefront to the existing Cloud Run
   service (URL prefix
   `https://shop-arena-<hash>-126018801413.us-central1.run.app`).
3. Wire the deployed URL into `cohort.yaml` (replaces `TBD`), bump the
   cohort patch version to **0.1.1**, and trigger the M5 cohort run.

Until step 2 lands, the cohort.yaml `sandbox.base_url` for these two
pairs is the literal string `TBD`; the loader (`shop_probe.cohort`)
accepts it because §5.2 only requires `base_url` to be a non-empty
string.

**Fallback.** If either deployment slips past M5 timeline, the
M5 cohort run drops to **2 pairs** (`pair_1` + one of {`pair_2`,
`pair_3`}) plus the 3 unpaired real shops, and the v0.1.1 revision
documents the reduction. Two pairs is still sufficient for the §5.7
per-pair fidelity table; the radar / surface / Turing charts (§8.4)
render with whatever pairs are populated.

#### 8.6.4 Anonymization-sufficiency ablation for axis C (closes Q4)

**Decision.** v1 anonymization (lexical rewrites over the
`Trajectory` text fields) is **sufficient** to defeat brand-recognition
on the closed leak-vector list it is designed to cover; out-of-scope
vectors (pixel content of screenshots, HAR response bodies,
accessibility-snapshot text inside on-disk evidence files) are
acknowledged as **v1.1 work**. M4–M5 axis-C judging proceeds with the
v1 anonymizer; if M4's swap-consistency check shows the judge flips on
swaps for >5% of pairs, the v1.1 vectors are escalated.

The reproducible ablation script lives at
[`scripts/anonymization_ablation.py`](../../../packages/shop_arena/scripts/anonymization_ablation.py).
Headline finding (excerpted):

> Across the 10-pattern v1 leak inventory (source domain, brand
> strings, theme identifiers, distinctive product titles), the
> anonymizer leaks **0 / 38** occurrences from the brand-loaded
> `pair_1` fixture trajectory (residual leakage rate 0.0%). Catalog
> handles in URL paths are hashed with a stable per-pair salt,
> preserving cross-step structure for the judge while removing
> brand identity. Out-of-scope vectors (pixel bytes, HAR bodies,
> on-disk a11y snapshot text) are not rewritten in v1; they are
> tracked as a v1.1 workstream.

#### 8.6.5 Summary of changes against `cohort.yaml`

| Field | Before T5.1 | After T5.1 |
|---|---|---|
| `real_unpaired[*].label` | `real/TBD_1`, `real/TBD_2`, `real/TBD_3` | `real/1`, `real/2`, `real/3` |
| `real_unpaired[*].base_url` | `TBD` | `https://real-1.example.invalid`, `https://real-2.example.invalid`, `https://real-3.example.invalid` |
| `pairs.pair_2.source.notes` | bot-detection TBD | option (b) chosen + fallback documented |
| `pairs.pair_3.source.notes` | bot-detection TBD | option (b) chosen + fallback documented |
| `pairs.pair_2.sandbox.base_url` | `TBD` | `TBD` (deployment-tracked; plan documented in §8.6.3) |
| `pairs.pair_3.sandbox.base_url` | `TBD` | `TBD` (deployment-tracked; plan documented in §8.6.3) |

The `pair_1` sandbox URL is unchanged — it is the single sandbox already
deployed at v0.1 cut.

#### 8.6.6 Versioning

- **0.1** — first cut with these decisions wired in.
- **0.1.1** — bump triggered by either (a) `pair_2` / `pair_3` sandbox
  deployment landing, (b) a bot-detection-driven fallback to
  alternates, or (c) the anonymization v1.1 escalation. Each 0.1.x
  patch updates §8.6.1–§8.6.4 in lockstep with `cohort.yaml`.
- **1.0** — paper-time freeze, post-M5 cohort run.
