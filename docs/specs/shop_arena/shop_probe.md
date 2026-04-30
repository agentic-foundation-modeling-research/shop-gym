# ShopProbe (`packages/shop_arena/src/shop_probe`)

Status: **Spec (current)** · Version: **0.2**
Owners: ShopGym
Last updated: **2026-04-30**

> A reproducible measurement tool that scores any deployed
> storefront on three independent axes — **capability coverage**,
> **surface area**, and **agent indistinguishability** — to quantify
> the structural fidelity of a generated SandboxShop relative to a
> population of real Shopify storefronts.

---

## 1. Overview

The ShopGym paper validates that SandboxShops are reliable proxies
for real storefronts using **behavioral fidelity** — agreement on a
108-task instruction-following benchmark run on each (source, sandbox)
pair. That answer is necessary but not sufficient: a reviewer can ask
whether agreement on a fixed task set generalizes, or whether the
sandbox is just narrow enough to look the same on those specific tasks.

`shop_probe` is the **structural fidelity** complement. It runs against
a deployed URL — sandbox or real — and emits a typed `ProbeReport`
that quantifies the storefront on three orthogonal axes:

- **Axis A — Capability coverage.** Closed, versioned rubric of 74
  probes covering core / modern / advanced tiers. The 66 core+modern
  entries are deterministic Playwright presence probes; the 8 advanced
  entries are **capture-judge** entries (LLM verdict over a screenshot
  + accessibility-tree bundle). Per-category and weighted total scores.
  *Answers: does it expose the modern-web features a real Shopify
  storefront has?*
- **Axis B — Surface area.** Quantitative crawl-derived metrics:
  distinct templates, interactables per template, forms / fields,
  routes, catalog combinatorics, DOM size. *Answers: is the
  action / observation space rich enough to be non-trivial for an
  agent?*
- **Axis C — Agent indistinguishability.** A blinded LLM judge
  classifies one shop at a time as `sandbox` or `real`; group accuracy
  on each population is the headline number. *Answers: from an
  agent-trace point of view, can a judge tell the sandboxes from the
  real shops?*

The pipeline runs over two flat populations — `sandboxes:` and
`reals:` — defined in a `bench.yaml`. Group-vs-group fidelity is the
headline metric; pair semantics are intentionally absent.

A secondary benefit is that ShopProbe ships *with* the paper as a
benchmark artifact: external researchers can run the same rubric
against their own storefronts or generated environments and get
comparable numbers.

---

## 2. Terminology

- **Target** — a deployed storefront under test. Identified by a
  filename-friendly `name`, a `base_url`, and a `label ∈ {sandbox,
  real}`.
- **Bench** — a `bench.yaml` file enumerating two flat populations:
  `sandboxes: tuple[Target, ...]` and `reals: tuple[Target, ...]`. No
  pair join key; both groups are independent.
- **Probe** — a single deterministic Playwright function returning
  `ProbeOutcome(passed, evidence, notes, duration_ms, extra)` for one
  rubric leaf. Used by core / modern entries.
- **Capture-judge probe** — rubric entry with `level: capture_judge`
  whose inline `capture_judge` block carries `pages: tuple[PageRef, ...]`
  and `judge_prompt: str`. Dispatched through the shared page bundle
  + a single Anthropic Messages-API call, not through a per-entry
  Playwright coroutine.
- **PageRef** — `Literal["home", "collection", "product", "cart",
  "search"]`. The fixed 5-page surface every advanced probe references.
- **Page bundle** — the 5 captures collected once per shop run. Each
  capture persists `screenshot.png` + `a11y.json` under
  `<evidence_root>/_bundle/<page>/`.
- **Page capture** — `(page_ref, url, screenshot_rel,
  accessibility_rel, applicable, notes)`. `applicable=False` records
  pages we couldn't reach (404, navigation timeout, missing sample
  URL); the judge skips them.
- **Capture judge** — `agent/judge.py:run_capture_judge(captures,
  bundle_root, judge_prompt, *, model, client) -> JudgeVerdict`. One
  Messages-API call with N image content blocks (one per applicable
  capture) interleaved with each page's accessibility-tree JSON, then
  the rubric prompt and a closing JSON-shape instruction. Returns
  `JudgeVerdict(passed, reasoning, cost_usd, model_id)`.
- **Structural affordance** — UI capability detectable from a single
  page state without interaction (e.g. "the collection page exposes a
  sort dropdown with ≥2 options"). The advanced-tier judge prompts
  ask only about structural affordances.
- **Rubric** — versioned YAML enumerating probes (deterministic +
  capture-judge), their category, weight, and level. Frozen and
  hashed; `rubric_version` + `rubric_hash` embed in every report.
- **ProbeReport** — closed pydantic JSON document emitted per target
  per run; combines axis A (probe results), axis B (surface metrics),
  and axis C (per-shop judge calls) plus runtime metadata.
- **GroupSummary / BenchComparison** — stage-2 aggregates: each group
  rolls up to a `GroupSummary`; the two summaries plus deltas form a
  `BenchComparison` that drives every paper figure.
- **Trajectory** — saved evidence for axis C: ordered (action,
  observation, reasoning) tuples plus screenshots and accessibility
  snapshots; per-shop, not pairwise.
- **`passed=None` / not-applicable** — `ProbeOutcome.passed` carries
  `True | False | None`. `None` means the probe ran but the storefront
  does not expose the surface required to assert a result (e.g. a
  capture-judge entry whose requested bundle pages are all
  `applicable=False`). The runner excludes `None` results from
  coverage aggregation.
- **Coverage** — axis A rubric score, ∈ [0, 1].
- **Surface** — axis B raw counts, no normalization implied.
- **Indistinguishability** — `|judge_accuracy(sandbox) -
  judge_accuracy(real)|`. Closer to 0 means the judge cannot tell the
  populations apart.

---

## 3. Current Status

Implemented surface (current):

```
rubric/v1.yaml   (61 probes) ─── core + modern, deterministic, presence-only
rubric/v1.1.yaml (66 probes) ─── v1 + 5 auth/checkout entries (account.*, checkout.*)
rubric/v2.yaml   (74 probes) ─── 66 v1.1 verbatim + 8 capture_judge advanced entries
                                 (this spec — see §5.3.3)
```

What ships in source today:

- **Stage-1 runner** (`shop-probe run`) — Playwright orchestration,
  isolated context, fixed 1280×800 viewport, pinned UA, 10 s probe
  timeout. Emits `ProbeReport` JSON + an `evidence/` subtree.
- **Stage-1 axes A + B** — deterministic probes implemented across
  `probes/{site_shell,homepage,collection,product,search,cart,i18n,
  floating,dynamics,a11y,media,account,checkout}.py`; surface crawler
  in `surface/{crawler,metrics}.py`.
- **Stage-1 axis C** — per-shop Turing-test classifier
  (`judge/{run.py,anonymize.py}`). One Anthropic Messages-API call per
  shop; report carries `judge_calls: tuple[JudgeCall, ...]`. No
  pairwise / swap protocol.
- **Bench loader** (`bench.py`, `bench.yaml`) — two flat populations,
  unique names across the union, label agreement enforced.
- **Stage-2 reporting** (`shop-probe report`) — `compute_bench_comparison`
  yields a `BenchComparison`; figure renderers emit
  `figures/{group_comparison.md, per_shop_table.md, radar.svg,
  surface.svg, turing.svg}`.
- **Rerun aggregation** (`shop-probe aggregate-reruns`) — keys by
  `(label, name, rubric_version, rubric_hash, runner_version)`;
  median across reruns; per-probe flake rate.
- **End-to-end driver** (`shop-probe eval`) — fans out across targets +
  reruns, then runs the report stage once.

Not yet shipped (this spec):

- **v2 advanced tier (capture-judge).** `rubric/v2.yaml` with 8
  capture-judge entries; `capture/` subpackage; `agent/judge.py`
  rewritten around the bundle; CLI dispatcher routes
  `level: capture_judge` entries through the new judge. Implementation
  plan: `docs/impl/shop_probe_v2_capture_judge_implementation.md`.
- **Cross-judge cross-lab triangulation, Likert quality dimensions,
  human-judge calibration, prior-work env baselines.** Tracked in §5.9.

Retired surface (deleted from source / docs):

- **Pair-based cohort.** `Cohort`, `Pair`, `PairFidelity`,
  `compute_pair_fidelity`, `judge/pairwise.py`, `judge/swap.py`. The
  axis C pipeline is per-shop classification; group-vs-group is the
  headline.
- **v1.2 deterministic advanced.** 8 selector-union probes asserting
  interaction outcomes (sort changes order, filter narrows, …).
  Retired because the selector unions ended up biased toward Hydrogen
  DOMs — sandbox group beat real group `0.238` vs `0.028` on
  `coverage_advanced` while presence-only coverage tracked within
  `~0.05` on the same shops. Retired in v2.
- **v1.3 agent-driven advanced.** 8 LLM-agent + LLM-judge entries
  driven by `harness.run_plan_exec_loop` against the
  `playwright-browser` skill. Never produced a verdict in cohort runs:
  the spawned `claude_code` runtime did not have the
  `playwright-browser` skill installed, so every agent invocation hit
  `Skill("playwright-browser")` → `Unknown skill` and burned the full
  180 s timeout. Retired in v2.

---

## 4. Desired Status

After the v2 capture-judge tier lands:

```
rubric/v2.yaml (74) ─── 66 deterministic entries (verbatim from v1.1) +
                        8 capture_judge entries (level: capture_judge,
                        pages ⊂ {home, collection, product, cart, search},
                        judge_prompt asking a structural-affordance
                        question). Total advanced-tier weight = 14.
```

Per-cohort flow:

- `shop-probe run` (axis A) opens one `ProbeRunner`, walks the
  homepage to discover sample collection / product URLs, then calls
  `capture_bundle(...)` once. The bundle persists under
  `<evidence_root>/_bundle/<page>/{screenshot.png, a11y.json}`.
- Deterministic entries dispatch through
  `probes._runner.ProbeRunner.run`.
- Capture-judge entries call `run_capture_judge(captures, bundle_root,
  prompt, model)` with the bundle slice the entry asks for. Verdicts
  populate a `ProbeOutcome` whose `evidence` references the bundle
  files (`kind="screenshot"`, `kind="a11y"`).

Reporting:

- `ProbeResult` carries `judge_cost_usd` + `judge_model` for every
  capture-judge probe. `ProbeReport.total_judge_cost_usd` aggregates
  across the 8 capture-judge probes per shop. The axis-C per-shop
  classifier writes its own `JudgeCall` rows; their cost lives on
  `JudgeCall.cost_usd`.
- `coverage_advanced` rolls up the 8 capture-judge entries (slot
  stability for cross-version comparison).

CLI:

- `--rubric v2` is the default. Older rubrics are no longer resolvable
  from disk — the v1, v1.1, and any legacy advanced YAMLs are
  retired in lockstep with this spec. `v2.yaml` is the only rubric
  the loader knows about.
- `--judge-model TEXT` (default `claude-opus-4-7`) feeds the
  capture-judge model. The axis-C Turing classifier keeps its own
  `--turing-judge-model` knob.
- `eval` forwards `--judge-model` into spawned `run` invocations.

Cost / latency budget (axis A advanced tier only; deterministic
probes, surface crawl, and axis C are unchanged):

| Unit | Cost | Latency |
|---|---|---|
| One bundle capture (5 pages, headless Chromium) | $0.00 | ~10 s |
| One capture-judge call (Opus, ≤2 images + a11y JSON) | ~$0.05 | ~5 s |
| One probe (1 judge call) | ~$0.05 | ~5 s |
| Full cohort (7 × 8 probes + 7 bundle passes) | ~$3 | ~6 min |

Sonnet 4.6 cuts cohort cost ~5× via `--judge-model
claude-sonnet-4-6`.

Success criterion for the next cohort: `shop-probe eval` against the
shipped 7-shop bench completes in **< 15 min** (vs. the ~3 h the
retired agent-driven path took on the same bench), and the
sandbox-vs-real gap on `coverage_advanced` reflects a real fidelity
delta rather than rubric-shape bias (i.e. it varies across cohorts
rather than tracking the rubric's selector union).

---

## 5. Proposal

### 5.1 Package layout

```
packages/shop_arena/
  pyproject.toml                # shared with shop_gen / shop_explore
  src/shop_probe/
    __init__.py
    cli.py                      # run / report / aggregate-reruns / eval
    targets.py                  # Target, TargetLabel
    bench.py                    # Bench, load_bench
    report.py                   # ProbeReport closed pydantic schema
    fidelity.py                 # GroupSummary, BenchComparison
    rubric/
      v2.yaml                   # frozen, hashed; 74 entries
      schema.py                 # RubricEntry, RubricLevel, CaptureJudgeTask
      loader.py
    probes/                     # axis A — deterministic
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
      account.py                # auth-gated
      checkout.py               # auth-gated
    capture/                    # axis A — page bundle for capture-judge
      __init__.py
      bundle.py                 # PageBundle, PageCapture, capture_bundle
    agent/                      # axis A — capture-judge call
      __init__.py
      env.py                    # .env loader + credential check
      judge.py                  # JudgeVerdict, run_capture_judge
    surface/                    # axis B
      crawler.py
      metrics.py
    judge/                      # axis C — per-shop Turing classification
      run.py
      anonymize.py
      tasks/v1.yaml
      prompts/v1/
        classifier.md
        system.md
    report_writer/
      figures.py                # radar, surface, Turing chart
      tables.py                 # group comparison, per-shop tables
  tests/
```

ShopProbe ships as a sibling module of `shop_gen` and `shop_explore`
inside the `shop-arena` distribution. They share `pyproject.toml` and
the `shop-probe` console script.

### 5.2 Bench

```python
TargetLabel = Literal["sandbox", "real"]

class Target(BaseModel):
    name: str                   # filename-friendly identifier; unique across the bench
    base_url: str
    label: TargetLabel
    notes: str | None = None

class Bench(BaseModel):
    version: str
    sandboxes: tuple[Target, ...]
    reals: tuple[Target, ...]
    # Validators:
    #   - all sandboxes have label == "sandbox"
    #   - all reals have label == "real"
    #   - names unique across union(sandboxes, reals)
```

`bench.yaml` shape:

```yaml
version: "0.2"
sandboxes:
  - { name: shop_alpha, base_url: https://shop-arena-<hash>.run.app, label: sandbox }
  - { name: shop_beta,  base_url: https://shop-arena-<hash>.run.app, label: sandbox }
reals:
  - { name: real_a, base_url: https://real-a.example.invalid, label: real }
  - { name: real_b, base_url: https://real-b.example.invalid, label: real }
  - { name: real_c, base_url: https://real-c.example.invalid, label: real }
```

The current shipped bench has 4 sandboxes + 3 reals (7 targets).
External researchers point `--bench` at their own file to reproduce
or extend.

### 5.3 Axis A — Capability coverage

Rubric is a YAML file, frozen and hashed per version. Two entry
shapes — deterministic and capture-judge — share the same envelope:

```yaml
# Deterministic (level: core | modern)
- id: product.gallery.thumbnails
  category: product
  level: modern
  weight: 2
  probe: probes.product.gallery_has_thumbnails
  description: PDP gallery exposes a thumbnail strip that swaps the main image.
  authenticated: false
  transactional: false

# Capture-judge (level: capture_judge)
- id: collection.sort.changes_order
  category: collection
  level: capture_judge
  weight: 2
  description: Capture-judge — collection page exposes a sort control with multiple options.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [collection]
    judge_prompt: |
      Does the collection page expose a sort control (dropdown,
      segmented buttons, or similar) with two or more selectable
      sort options?
```

Schema invariants:

- `RubricLevel = Literal["core", "modern", "capture_judge"]` (no
  `"advanced"` literal; `coverage_advanced` rolls up
  `capture_judge` entries — see §5.6).
- Exactly one of `{probe, capture_judge}` is set per entry; the
  validator enforces this in lockstep with `level`.
- `weight ∈ {1, 2, 3}`; each rubric is content-addressable (SHA-256
  over raw YAML bytes; the hash is pinned in tests and embedded in
  every report header).

#### 5.3.1 Categories and probe counts (v2)

| Category | Probes | Examples |
|---|---|---|
| `site_shell` | 6 | sticky header, mega menu, mobile drawer, footer groups |
| `homepage` | 5 | hero, feature grid, testimonials, multiple section types |
| `collection` | 12 | sidebar filters, accordion filters, sort popover, URL-state sync, active-filter chips, pagination/infinite-scroll/load-more, **+4 capture-judge** |
| `product` | 12 | gallery type, image swap on variant, radio/swatch/dropdown selectors, qty spinner, accordion description, recommendations, reviews, breadcrumbs, **+2 capture-judge** |
| `search` | 6 | header trigger, predictive listbox, grouped results, ARIA combobox, full results page, **+1 capture-judge** |
| `cart` | 6 | drawer vs page, line-item edit, qty change, promo code, AJAX badge update, empty state |
| `i18n` | 3 | locale switcher, currency switcher, market routing |
| `floating` | 3 | cookie consent, age gate, newsletter popup |
| `dynamics` | 6 | loading skeleton, toast/snackbar, optimistic update, debounced input, **+1 capture-judge** |
| `a11y` | 6 | combobox role, listbox role, dialog role + focus trap, live regions, skip-to-content, alt text |
| `media` | 4 | lazy-load images, video on PDP, lightbox/zoom, srcset/responsive |
| `account` | 3 | login, signup, password reset (auth-gated) |
| `checkout` | 2 | shipping form, summary panel (transactional-gated) |

**Total: 74 probes** (66 deterministic core + modern + auth slice; 8
capture-judge advanced). Total capture-judge weight: **14**.

Score per category: `Σ weight·passed / Σ weight`. The four headline
numbers are `coverage_core`, `coverage_modern`, `coverage_advanced`
(rolls up `capture_judge`), and `coverage_weighted` (weighted mean
across categories).

#### 5.3.2 Deterministic probes (`level: core | modern`)

Each deterministic probe:

- Has a hard timeout (default 10 s).
- Runs in an isolated Playwright context with a fixed viewport
  (1280×800), pinned UA, headless.
- Emits structured evidence: screenshot path, DOM-snapshot path, the
  CSS / role selector used to assert.
- Has retries=0; flake is captured at the suite level via N=3 reruns
  (see §5.7 reproducibility).

The 5 auth + checkout entries (`account.*`, `checkout.*`) are gated
behind `--include-auth`; they ship under v1.1 conventions and are
unchanged in v2.

#### 5.3.3 Advanced tier — capture-judge

The advanced tier is **structural-affordance** judging, not
interaction verification. Per-shop flow (axis A path of
`shop-probe run`):

1. After the homepage walk discovers `sample_collection_url` and
   `sample_product_url`, the runner calls `capture_bundle(...)` once
   per shop and persists the 5 captures.
2. Each `level: capture_judge` rubric entry slices the bundle by
   `entry.capture_judge.pages` and calls `run_capture_judge(...)`. A
   single Anthropic Messages-API call combines, in order: per applicable
   capture, a text label + base64 PNG block + a fenced JSON block of
   the page's a11y tree; then the rubric's `judge_prompt`; then a
   closing instruction asking for `{"passed": bool, "reasoning":
   str}`.
3. The verdict projects onto a `ProbeOutcome`
   (`passed=verdict.passed`, `notes=verdict.reasoning` when failing,
   `extra={"judge_cost_usd": …, "judge_model": …}`); the dispatcher
   appends one `EvidenceRef` per applicable capture for both
   screenshot and a11y JSON.

URL resolution per `PageRef`:

| `page_ref` | URL |
|---|---|
| `home` | `base_url` |
| `collection` | `sample_collection_url` (None ⇒ `applicable=False`) |
| `product` | `sample_product_url` (None ⇒ `applicable=False`) |
| `cart` | `urljoin(base_url, "/cart")` |
| `search` | `urljoin(base_url, "/search?q=test")` |

`capture_bundle` never raises. Navigation timeouts, 4xx/5xx, and
`accessibility.snapshot` exceptions all materialise as
`PageCapture(applicable=False, notes=…)`.

When every requested capture for an entry is inapplicable, the
dispatcher returns `ProbeOutcome(passed=None,
notes="all requested bundle pages unavailable")` *without* an API call;
the entry is excluded from coverage aggregation. Otherwise the judge
sees the applicable subset and returns `True | False`.

The full set of 8 v2 capture-judge entries is in Appendix B.

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
coverage but is not folded into the headline coverage score. For
group-vs-group fidelity (§5.6) we report population means + envelopes
per metric.

### 5.5 Axis C — Agent indistinguishability (Turing classifier)

Per-shop classification, not pairwise. Pipeline:

1. **Tasks.** `judge/tasks/v1.yaml` enumerates ~10 tasks tuned for
   *judge diagnosticity* — visually rich, multi-page, interaction-heavy
   (e.g. "filter the bestsellers collection by Product Type, open the
   third PDP, switch to a different variant, add 2 to cart, switch
   locale"). These are **separate from the 108 ShopGuru benchmark
   tasks**, run on an independent agent invocation; see §5.5.1.
2. **Agent runner.** Wraps `packages/harness` plan / exec loop with a
   Playwright runtime against the target URL. Saves a `Trajectory`:
   ordered (action, observation, reasoning) tuples plus screenshots
   and accessibility-tree snapshots.
3. **Trajectory anonymization.** Strip URL, brand strings, theme
   identifiers, OG metadata, favicon, distinctive product names.
   Replace catalog identifiers with stable hashes. Keep only the
   structural and interactional surface visible to the agent.
4. **Per-shop classification.** Show the anonymized trajectory to the
   judge with the prompt: *"This trajectory was recorded against
   exactly one storefront. Is it a real Shopify-powered storefront,
   or a synthetically generated sandbox?"* Required JSON shape:
   `{predicted_label: "sandbox" | "real" | "abstain", confidence:
   float, evidence: [...], rationale: str}`. `abstain` calls are
   counted but never scored as correct.
5. **Group accuracy** (computed at stage 2):
   ```
   judge_accuracy(group) = Σ (c.predicted_label == r.target.label)
                          for r in group_reports for c in r.judge_calls
                          / Σ len(r.judge_calls) for r in group_reports
   ```
6. **Indistinguishability** = `|judge_accuracy(real) -
   judge_accuracy(sandbox)|`. Closer to 0 means the judge cannot
   distinguish the populations.

v2 uses one OpenAI flagship model as judge (e.g. `gpt-5`, exact
version pinned at run time and embedded in every report;
temperature 0). Because ShopGym's generation pipeline is
Claude-driven, a non-Anthropic judge is **cross-lab by construction** —
this addresses the "judging Claude with Claude" critique without a
multi-judge ensemble in v2.

Required guardrails:

- Pin model + version + temperature in the report metadata.
- Save full prompt + full response per call.
- Force evidence citation: every "real / synthetic" call must cite
  specific screenshot indices or snapshot lines. Calls without
  evidence are recorded as `abstain`.
- The agent and the judge use **distinct prompts and contexts** —
  never share state, never share model invocations.

#### 5.5.1 Why axis C uses a separate task list from the 108-task benchmark

The 108-task ShopGuru benchmark is the *behavioral fidelity*
instrument and lives **outside** ShopProbe. Axis C is the *perceptual
fidelity* instrument and lives **inside** ShopProbe. Reusing benchmark
traces for the judge would couple these two instruments and create a
confound: when an agent fails on the sandbox but succeeds on the real
shop (or vice versa), the trajectory shapes diverge for reasons
unrelated to the storefront's realism, and the judge picks up on the
*failure pattern* rather than on the storefront. By running an
independent task list with the same harness, the 108-task behavioral
evaluation and axis C remain orthogonal in the paper. The agent
*implementation* is shared; the *task list*, *invocation*, and *saved
traces* are independent.

### 5.6 ProbeReport schema (closed)

```python
class EvidenceRef(BaseModel):
    kind: Literal["screenshot", "snapshot", "har", "a11y"]
    path: str                        # relative to evidence_root
    notes: str | None = None

class ProbeResult(BaseModel):
    id: str
    passed: bool | None              # None = not_applicable
    evidence: tuple[EvidenceRef, ...] = ()
    notes: str | None = None
    duration_ms: int
    judge_cost_usd: float | None = None    # capture-judge probes only
    judge_model: str | None = None         # capture-judge probes only

class CategoryScore(BaseModel):
    category: str
    weight_passed: float
    weight_total: float
    coverage: float                  # weight_passed / weight_total

class JudgeCall(BaseModel):
    predicted_label: Literal["sandbox", "real", "abstain"]
    prompt_hash: str
    response: str
    latency_ms: float
    cost_usd: float
    model_id: str

class ProbeReport(BaseModel):
    target: Target
    rubric_version: str
    rubric_hash: str
    runner_version: str
    runtime: BrowserMeta
    timestamp: datetime
    # Axis A
    probe_results: tuple[ProbeResult, ...] = ()
    categories: tuple[CategoryScore, ...] = ()
    coverage_core: float
    coverage_modern: float
    coverage_advanced: float         # rolls up level == "capture_judge"
    coverage_weighted: float
    # Axis B
    surface: SurfaceMetrics | None = None
    # Axis C
    judge_calls: tuple[JudgeCall, ...] = ()
    # Stability
    rerun_index: int
    flake_rate_per_probe: dict[str, float] = {}
    # Cost rollup (axis A advanced tier only — axis C cost lives on JudgeCall)
    total_judge_cost_usd: float | None = None
```

`extra="forbid"` everywhere; this is the contract the paper figures
read.

### 5.7 Bench comparison

Stage 2 (`shop-probe report --bench bench.yaml --out OUT/`) loads
every shop's `ProbeReport`, splits them by `target.label`, and
computes:

```python
class GroupSummary(BaseModel):
    label: TargetLabel
    n_shops: int
    coverage_weighted_mean: float
    coverage_per_axis_mean: dict[str, float]      # core / modern / advanced
    surface_metric_means: dict[str, float]
    surface_metric_envelope: dict[str, tuple[float, float]]   # (min, max)
    judge_accuracy: float | None                  # share of judge calls predicting target.label
    judge_calls_total: int

class BenchComparison(BaseModel):
    sandbox: GroupSummary
    real: GroupSummary
    coverage_gap_weighted: float                  # real.mean - sandbox.mean
    coverage_gap_per_axis: dict[str, float]       # core / modern / advanced
    surface_ratio: dict[str, float]               # sandbox.mean / real.mean
    sandbox_in_real_envelope: dict[str, dict[str, bool]]   # sandbox name → metric → in-envelope?
    judge_indistinguishability: float | None      # |real.judge_acc - sandbox.judge_acc|
```

Headline paper claim format (with placeholder numbers):

> Across N sandbox storefronts and M real Shopify storefronts,
> ShopArena SandboxShops achieve a population coverage gap of
> **−0.04** (sandboxes slightly under reals on `coverage_weighted`)
> and a surface-metric geometric-mean ratio of **0.78**, with each
> sandbox falling inside the [min, max] envelope of the real-shop
> population on **9 of 11** surface metrics. A blinded GPT-5 judge
> classifies sandboxes correctly **0.56** (95% CI [0.50, 0.62]) and
> reals correctly **0.52** — an indistinguishability gap of **0.04**,
> within ε = 0.05 of chance.

Stage-2 figure outputs:

| File | Source axis | Description |
|---|---|---|
| `figures/group_comparison.md` | A + B + C | Group rows + delta row |
| `figures/per_shop_table.md` | A + B + C | One row per shop, used for stage-3 inspection |
| `figures/radar.svg` | A | Per-category coverage; the real envelope is shaded, sandboxes overlaid |
| `figures/surface.svg` | B | Sandbox dots + real-envelope rectangles per metric |
| `figures/turing.svg` | C | Two grouped bars: judge accuracy on sandbox group vs real group, plus indistinguishability gap |
| `figures/supplement_table.md` | A + B + C | Optional, when `--baselines-dir` provided |

A stage-3 `compare` subcommand (cherry-pick one shop, render against
others) is reserved in the CLI dispatch but not implemented; it is
forward-compatible with the stage-2 outputs.

### 5.8 Reproducibility

- Pin Playwright + Chromium + Python versions in `pyproject.toml`
  and embed them in every report header.
- Every probe and every prompt has a `version` and a content hash;
  hashes go into the report header.
- Rubric YAML is frozen per version. Changes bump the version; the
  paper cites a specific version + hash.
- Run each target N=3 times; report `flake_rate_per_probe` and gate
  paper claims on flake < 1% per probe. The
  `shop-probe aggregate-reruns` step takes the median across reruns
  and writes the canonical per-target report.
- Save **HAR captures** of every crawl so reviewers can re-score
  offline against frozen network responses if the live target
  changes. (`--record-har` is a per-run flag; off by default for
  cohort runs to bound disk usage.)
- Save **all** screenshots and accessibility snapshots — these are
  the evidence trail for both deterministic probes and capture-judge
  verdicts.
- The page bundle is part of the evidence trail: `_bundle/<page>/`
  ships in every cohort export so reviewers can re-judge offline.

### 5.9 What's intentionally **out** of scope

- **Interaction-delta verification on advanced tier.** Capture-judge
  probes inspect static page state. Behavioural fidelity for the 8
  advanced slots is intentionally relaxed; the v1.2 deterministic
  attempt and the v1.3 agent-driven attempt are both retired. If
  behavioural fidelity becomes a paper requirement, a v3 advanced
  tier can revisit this trade.
- **Multi-judge ensemble.** v2 = one OpenAI flagship model for axis C
  + one Anthropic flagship model for capture-judge. Cross-lab on
  axis C; capture-judge is intentionally same-lab as the generation
  pipeline (the question is whether the storefront *exposes* an
  affordance, not whether the trace looks real). Cross-judge
  triangulation is a v0.3 / supplement workstream.
- **Likert quality dimensions** (visual coherence, copy realism,
  error plausibility). Deferred; pairwise + intra-real control was
  retired alongside the pair semantics, and the per-shop Turing
  classifier carries the v2 indistinguishability claim.
- **Prior-work environment baselines** (Mock Shop, WebShop,
  WebArena-Shopping). Out of v2 cohort; can be added as a paper
  supplement table without re-running primary results.
- **Human calibration of the judge.** Recommended for a paper
  supplement (Spearman ρ between human and LLM judge over a ~50-trace
  subset) but tracked as a separate workstream.
- **Performance probes** (LCP, INP, bundle size). Out of scope; not
  the fidelity question.
- **Selector-DOM advanced probes.** Retired with v1.2.
- **Agent-driven advanced probes.** Retired with v1.3.

---

## 6. Alternatives considered

- **LLM-only evaluation (no rubric).** Rejected: not reproducible
  enough for a paper, hard to defend in review, brittle over model
  upgrades.
- **Rule-only evaluation (no judge).** Rejected: rules cannot detect
  copy realism, coherence across pages, or "AI-shaped" UX. Misses
  the most interesting failure modes of generated content.
- **Pair-based fidelity.** Original v0.1 proposed
  `(source, sandbox)` pairs with a pairwise Turing judge. Rejected:
  pair identity is brittle to maintain across runs, per-pair fidelity
  rows are noisy at small N, the pairwise / swap protocol is over-
  engineered, and most consumers want one group-vs-group answer.
- **Single collapsed fidelity score.** Rejected: hides which axis the
  sandbox fails on. Three numbers + one indistinguishability gap,
  reported separately, are easier to defend in review and more
  diagnostic for engineering.
- **Reuse `shop_explore/capabilities.json`.** Rejected: that schema
  is content extraction for the manual pipeline, not measurement.
  Coupling the two would force one to evolve at the other's pace.
- **Multi-judge ensemble in v2.** A non-Anthropic judge against a
  Claude-driven generation pipeline is already cross-lab on axis C;
  the marginal value of a second judge is calibration / sensitivity,
  which fits a v0.3 / supplement workstream.
- **Reusing 108-task benchmark traces for axis C.** Couples
  behavioral and perceptual fidelity through shared traces (§5.5.1).
  Independent task list, shared harness implementation.
- **Deterministic advanced probes (v1.2 attempt).** Rejected: selector
  unions ended up biased toward Hydrogen DOMs; sandbox-vs-real gap
  on `coverage_advanced` was a function of theme provenance rather
  than fidelity.
- **Agent-driven advanced probes (v1.3 attempt).** Rejected: the
  `playwright-browser` skill needed by the spawned `claude_code`
  runtime was not installed in the harness workspace; every
  invocation hit `Skill("playwright-browser") → Unknown skill` and
  burned the full timeout. Even with the skill present, the agent
  path's wall-clock cost and judge complexity (BEFORE/AFTER +
  trajectory + verdict) exceeded the value over a structural-
  affordance check.
- **Capture-judge with DOM input instead of accessibility tree.**
  Rejected: a11y trees compress to ~5–10 KB per page vs ~200 KB for
  a Hydrogen DOM, and the semantic axes (roles, names, levels) are
  exactly what affordance prompts ask about. DOM adds tokens without
  proportional signal.
- **Per-entry capture (not a shared bundle).** Rejected: 8× the
  navigation cost for the same 5 unique pages, with no fidelity gain
  — every capture-judge entry maps cleanly onto one of the 5 shared
  `PageRef`s.

---

## 7. Milestones

The historical milestones (M1–M5) shipped under the v0.1 spec are
preserved here as completed; M6–M7 cover the active v2 work.

| ID | Status | Deliverable |
|---|---|---|
| **M1** | shipped | Package skeleton; `Target`, `ProbeReport`, `RubricEntry` schemas; `rubric/v1.yaml` with 20 `core`-level probes; CLI `shop-probe run --axes A`. |
| **M2** | shipped | Axis B surface crawler + `SurfaceMetrics` schema; `--axes A,B`; bench wiring. |
| **M3** | shipped | Pilot run on a single sandbox + real shop; rubric expansion to 61 entries (v1) and 66 entries (v1.1 with auth slice). |
| **M4** | shipped | Axis C — per-shop Turing classifier; trajectory anonymization; per-shop judge call recorded on `ProbeReport.judge_calls`. |
| **M5** | shipped | Full bench run with N=3 reruns; `aggregate-reruns` + flake reporting; `report` stage producing all five figures from versioned reports. |
| **M6** | active | v2 capture-judge advanced tier. New `capture/` subpackage; `agent/judge.py` rewrite around `run_capture_judge`; `rubric/v2.yaml` (74 entries, 8 capture-judge); CLI `--rubric v2 --judge-model …`; `coverage_advanced` non-zero. Detailed task list: `docs/impl/shop_probe_v2_capture_judge_implementation.md`. **Gate:** sandbox cohort eval runtime drops to < 15 min on the shipped 7-shop bench. |
| **M7** | future | Cross-judge cross-lab triangulation (second judge family on axis C); Likert quality dimensions; ~50-trace human-judge calibration; prior-work envs as supplement. |

M6 is the active milestone; everything else has either shipped or is
deferred.

---

## 8. Appendix

### 8.1 Example deterministic probe (Python)

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
        evidence=(ctx.snapshot("after-thumb-click"), ctx.screenshot("after-thumb-click")),
        notes=None if main_before != main_after else "main image did not swap",
    )
```

### 8.2 Bench YAML (sketch)

```yaml
version: "0.2"
sandboxes:
  - { name: shop_alpha, base_url: https://shop-arena-<hash>.run.app, label: sandbox }
  - { name: shop_beta,  base_url: https://shop-arena-<hash>.run.app, label: sandbox }
reals:
  - { name: real_a, base_url: https://real-a.example.invalid, label: real }
  - { name: real_b, base_url: https://real-b.example.invalid, label: real }
  - { name: real_c, base_url: https://real-c.example.invalid, label: real }
```

### 8.3 Per-shop Turing classifier prompt (sketch)

```
SYSTEM
You are evaluating whether an agent trajectory was recorded on a real
Shopify-powered storefront or on a synthetically generated sandbox.
You will see exactly one trajectory; classify it.

USER
Task: {task_description}

Trajectory: {anonymized_trajectory}

Decide whether the storefront the trajectory ran against is real or
synthetic. You MUST cite specific screenshot indices or snapshot lines
as evidence for every factual claim. If you cannot cite evidence,
output "abstain".

Respond as JSON:
{
  "predicted_label": "sandbox" | "real" | "abstain",
  "confidence": 0.0..1.0,
  "evidence": [
    {"ref": "screenshot_07" | "snapshot_12:L34", "claim": "..."}
  ],
  "rationale": "..."
}
```

### 8.4 Capture-judge content layout

`agent/judge.py:run_capture_judge` produces (one screenshot, one a11y
block, one prompt block per applicable capture, then the rubric
question + closing instruction):

```python
[
    {"type": "text", "text": "home (https://shop.example.com/) — screenshot:"},
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "<…>"}},
    {"type": "text", "text": "home accessibility tree:\n```json\n{…}\n```"},
    # ... per applicable capture
    {"type": "text", "text": (
        "Rubric question:\n"
        "Does the homepage expose a header search input that opens a predictive\n"
        "results listbox after a few characters of input?\n\n"
        "Decide whether the storefront exposes the affordance described above.\n"
        "You are looking at static page captures — judge structural presence,\n"
        "not interaction. Respond with a single-line JSON object exactly of the\n"
        'form {"passed": <true|false>, "reasoning": "<one short sentence>"}.\n'
        "Do not wrap the response in Markdown."
    )},
]
```

Malformed responses fall back to `passed:\s*(true|false)`
string-match; the fallback path stamps `[fallback parse]` onto
`verdict.reasoning`.

### 8.5 The 8 v2 capture-judge rubric entries

YAML appended to `rubric/v2.yaml` after the 66 v1.1 entries.

```yaml
- id: collection.sort.changes_order
  category: collection
  level: capture_judge
  weight: 2
  description: Capture-judge — collection page exposes a sort control with multiple options.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [collection]
    judge_prompt: |
      Does the collection page expose a sort control (dropdown, segmented
      buttons, or similar) with two or more selectable sort options?
      Inspect the screenshot and the accessibility tree before answering.

- id: collection.filters.applies_to_results
  category: collection
  level: capture_judge
  weight: 2
  description: Capture-judge — collection page exposes filter controls bound to the result list.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [collection]
    judge_prompt: |
      Does the collection page expose at least one filter control
      (checkbox, segmented buttons, faceted sidebar, etc.) that, by its
      placement and labelling, narrows the visible product list?

- id: collection.pagination.advances
  category: collection
  level: capture_judge
  weight: 1
  description: Capture-judge — collection page exposes a pagination affordance.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [collection]
    judge_prompt: |
      Does the collection page expose a pagination affordance — next-page
      button, numbered page links, "load more" button, or visible
      scroll-pagination indicator?

- id: collection.filters.url_state_advances
  category: collection
  level: capture_judge
  weight: 2
  description: Capture-judge — collection page filter controls suggest URL-encoded state.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [collection]
    judge_prompt: |
      Do the filter controls on the collection page appear to encode their
      state in the URL? Look for filter facets that are anchor / link
      elements (vs. plain JS-only checkboxes), explicit "share filtered
      view" affordances, or visible hints that the URL changes on filter
      apply.

- id: product.variant.swap_updates_state
  category: product
  level: capture_judge
  weight: 2
  description: Capture-judge — product page exposes variant selectors.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [product]
    judge_prompt: |
      Does the product page expose a variant-selection control (color
      swatches, size dropdown, segmented buttons, radio group) with two
      or more selectable options?

- id: product.qty.spinner_increments
  category: product
  level: capture_judge
  weight: 1
  description: Capture-judge — product page exposes a quantity input with increment control.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [product]
    judge_prompt: |
      Does the product page expose a quantity input — a spinner with
      +/− buttons, a number input, or labelled stepper — that the
      shopper could use to increase the purchase quantity?

- id: search.predictive.populates_listbox
  category: search
  level: capture_judge
  weight: 2
  description: Capture-judge — site header exposes a search input that signals predictive results.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [home]
    judge_prompt: |
      Does the homepage header expose a search input (or a button that
      opens one) configured for predictive results — e.g. role=combobox /
      aria-autocomplete / aria-controls referencing a results listbox?
      Inspect the accessibility tree alongside the screenshot.

- id: dynamics.cart_count_badge_updates
  category: dynamics
  level: capture_judge
  weight: 2
  description: Capture-judge — site header exposes a cart count badge.
  authenticated: false
  transactional: false
  capture_judge:
    pages: [home, product]
    judge_prompt: |
      Do the home and product page headers expose a cart icon with a
      count badge or numeric indicator that would update when an item is
      added to the cart? The badge can be visible at zero (e.g. "0") or
      hidden until non-zero.
```

Total weight: 14 (collection 7 + product 3 + search 2 + dynamics 2).

### 8.6 Failure modes the design defends against

- **Selector-shape bias** (the v1.2 motivator). The capture-judge sees
  the full a11y tree + a screenshot; it picks the affordance, not
  the rubric. Real-shop themes with quirky sort UIs are first-class.
- **Missing sample URLs.** If `sample_collection_url` is undiscoverable,
  every collection-anchored bundle capture is `applicable=False`.
  Capture-judge entries that require only the collection page report
  `passed=None` (skipped from coverage); entries that fall back to
  other pages still run.
- **Page reachable but degenerate.** Storefront returns the homepage
  for `/cart` or `/search`. The judge sees the actual returned page
  and answers the prompt against it — same failure mode the equivalent
  v1.1 deterministic probes already tolerate.
- **Judge flake on borderline cases.** Vision Opus may flip on
  near-ambiguous affordances. v2 ships with `--reruns 1` as the
  default; flake rate is observable through the standard rerun
  aggregator. >5% flake on capture-judge entries triggers a follow-up
  (chain-of-thought prompt, judge-twice-and-agree). Out of scope for
  v2.
- **Outer-timeout starvation.** Capture-judge calls inherit the base
  10 s probe timeout; if the SDK call itself exceeds the budget, the
  runner's `asyncio.wait_for` fires and the probe records
  `passed=False, notes="timeout after 10s"` — same as a slow
  deterministic probe.
- **Unbounded cost.** Per-probe `judge_cost_usd` is recorded on every
  capture-judge result; `total_judge_cost_usd` is the cohort rollup.
  No enforcement.

### 8.7 Versioning

- **0.1** — initial spec; pair-based cohort; v1 + v1.1 deterministic
  rubrics. Retired.
- **0.2** *(this document)* — bench / population pipeline; per-shop
  Turing classifier; v2 capture-judge advanced tier. Replaces the
  pair semantics from v0.1 and the retired v1.2 / v1.3 advanced-tier
  attempts.
- **0.3** *(future)* — cross-judge triangulation, Likert quality,
  human-judge calibration, prior-work env supplement.
