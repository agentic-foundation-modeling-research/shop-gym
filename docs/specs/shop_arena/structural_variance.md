# URL-based structural variance

Status: **Implemented**
Version: **0.5**
Date: 2026-07-27

## Overview

Structural variance measures how much independently generated storefronts differ
when they were produced from the same Shop Manual. Each sample is a hosted shop
URL. The evaluator uses rendered browser state, not generated source files or
SandboxShop data files.

```bash
shop-env-eval compare <url> <url> [<url> ...]
```

For each URL, the command extracts the accessibility-tree profile of one
discovered representative for each available typical page type: homepage,
collection, product detail page, policy, cart, and search. It computes one
cohort mean per page type, then reports every shop's distance from that mean.

Only two order-independent measurements are retained:

- **Element Type Distribution** — the normalized distribution of AXTree roles
  such as `button`, `link`, `heading`, and `main` after wrapper/text roles are
  removed;
- **Maximum Depth** — the deepest semantic AXTree path after those wrappers are
  collapsed.

The deterministic comparison remains LLM-free. An optional visual-judge layer
can compare the same representative pages from screenshots. Visual results are
reported separately for every requested judge model and never modify or combine
with the deterministic AXTree measurements. The comparison measures
output-to-output variance only; fidelity to the source Shop Manual is separate
because the manual is not an input.

## Terminology

- **Sample** — one hosted shop URL and its EnvEval run.
- **Cohort** — two or more samples compared in one invocation.
- **Structural snapshot** — the content-independent representation derived
  from one EnvEval run and written as `structure.json`.
- **Representative page** — the single deterministic URL selected by EnvEval
  for one typical page type. Unavailable types are omitted.
- **Element type** — a normalized accessibility role retained from the AXTree.
  The name emphasizes the kind of UI element rather than its text or identity.
- **Cohort mean** — the mean normalized element distribution and mean maximum
  depth for one page type across shops where that page type is available.
- **Sample distance** — one shop's deviation from the cohort mean, in `[0, 1]`.
  `0` means the shop equals the mean for that measurement.
- **Structural variance** — the mean sample-to-cohort-mean distance. The report
  also includes median, p90, minimum, and maximum across shops.
- **Visual judge** — an explicitly requested vision-capable LLM that compares
  all available cohort screenshots for one representative page type in one
  call.
- **Shared visual design** — the dominant or common layout and styling visible
  across a page-type cohort. It is an LLM judgment target, not a literal mean
  image and not the mathematical AXTree cohort mean.
- **Visual distance** — a judge-assigned sample deviation from the shared visual
  design in `[0, 1]`, where `0` means visually indistinguishable design and `1`
  means no meaningful visual design is shared.

## Current Status

EnvEval emits the source artifacts used by this comparison:

- discovered representative pages and shop identity in `metrics.json`;
- per-page accessibility trees under `observation/`;
- a closed `structure.json` snapshot for every comparison sample;
- a closed `variance.json` report from `shop-env-eval compare`.

The URL-cohort comparison is implemented in
`shop_arena.env_eval.structure`.

## Desired Status

One command accepts at least two hosted shop URLs, evaluates them with shared
browser settings, and writes a closed-schema structural-variance report. The
measurement must:

1. depend only on behavior observable through the supplied URLs;
2. ignore content values such as product titles, accessible names, hostnames,
   generated ids, CSS classes, and concrete catalog handles;
3. compare equivalent representative page types even when routes differ;
4. make no LLM calls or load credentials unless a visual judge model is
   explicitly requested;
5. remain order-independent because the question is which element types are
   present, not their exact traversal order;
6. report each shop's deviation from a shared cohort mean;
7. preserve every completed per-URL EnvEval run if a later sample fails;
8. optionally judge visual deviation once per representative page type and
   report every judge model independently.

## Proposal

### CLI and output

The CLI surface is:

```bash
shop-env-eval compare URL URL [URL ...] [--out PATH]
                      [--viewport WIDTHxHEIGHT] [--max-hops N]
                      [--visual-judge-model MODEL]...
                      [--rediscover]
```

The comparison always constructs each `EvalConfig` with `no_rubric=True`.
Consequently the screenshot rubric and `/pages/<slug>` classifier are stubbed,
so the child EnvEval runs remain deterministic and make no LLM calls. The
repeatable `--visual-judge-model` option is the only comparison-specific LLM
surface. When it is absent, the command does not load project credentials,
construct clients, or make LLM calls. When present, project credentials are
loaded only after configuration validates.

Samples run serially to bound browser and local-server resource usage. The
default output directory is
`outputs/shop_env_evals/comparisons/<run_id>/`. An explicit `--out` makes the
child EnvEval run directories resumable through the existing EnvEval rules.

```text
<comparison_dir>/
├── runs/
│   ├── 000-<host>/{metrics.json,structure.json,...}
│   ├── 001-<host>/{metrics.json,structure.json,...}
│   └── 002-<host>/{metrics.json,structure.json,...}
├── visual/
│   └── 000-<model>/
│       ├── homepage.json
│       ├── collection.json
│       └── result.json
└── variance.json
```

The command prints the `variance.json` path on stdout.

### Structural snapshot

`structure.json` is a closed Pydantic document containing the source URL,
EnvEval version, and one page record per available representative page type.
Each page record contains:

- representative page type and canonical page id;
- an AXTree element-type count histogram;
- semantic maximum depth.

The histogram lowercases accessibility roles and drops presentational,
text-only, root-web-area, and generic wrapper roles. Accessible names,
browser-assigned ids, and AXTree child order never enter the snapshot.

### Cohort mean

For page type `t`, let `S_t` be the shops where that representative page is
available. Each shop's element histogram is normalized into a probability
distribution `p_i,t`. The published centroid is:

```text
mean_distribution_t(role) = mean(p_i,t(role) for i in S_t)
mean_depth_t               = mean(depth_i,t for i in S_t)
```

A missing page type does not contribute a zero profile; it is omitted from that
page type's mean. `variance.json` records `sample_count` for every mean page so
consumers can see how many shops contributed. If an AXTree has no retained
elements, its implicit no-element probability mass is included in the
total-variation calculation without being exposed as a synthetic element type.

### Distance from the mean

For shop `i` and page type `t`:

```text
element_type_distribution =
    0.5 * sum_role(abs(p_i,t(role) - mean_distribution_t(role)))

maximum_depth =
    abs(depth_i,t - mean_depth_t) / max(depth_i,t, mean_depth_t, 1)
```

Element Type Distribution is total-variation distance. Maximum Depth uses a
relative difference so the value is scale-independent. Both are in `[0, 1]`.

The shop-level component values are the means across that shop's available
representative pages. `variance.json` contains:

- the cohort mean for each available page type;
- one aggregate and per-page distance record for every shop;
- distribution summaries across the shop distances.

The deterministic profile intentionally has no Navigation, node-count,
interactive-ratio, order-aware Composition, Interaction, Overall, or pairwise
metric.

### Optional visual judge

For page type `t`, let `S^V_t` contain the samples with a captured representative
screenshot. A visual comparison is meaningful only when `|S^V_t| >= 2`; page
types available in fewer than two samples are omitted from visual judging. For
each requested model `m`, the comparison makes exactly one call per eligible
page type and supplies all screenshots in sample-index order.

The prompt asks the judge to compare only visually observable design:

- layout and component arrangement;
- visual hierarchy;
- typography;
- color palette;
- spacing and density;
- visual component treatment.

It explicitly instructs the judge to ignore product identity, product names and
other text semantics, and differences in the depicted product images. Image
placement, aspect ratio, cropping, and framing remain part of visual design.

For model `m`, page type `t`, and sample `i`, the judge returns a distance
`d^m_i,t` from the cohort's shared visual design plus a rationale. The response
must contain each expected sample index exactly once and every distance must be
in `[0, 1]`. The implementation, rather than the model, computes equal-weight
aggregates:

```text
page_visual_distance^m_t =
    (1 / |S^V_t|) * sum(i in S^V_t, d^m_i,t)

sample_visual_distance^m_i =
    (1 / |T^m_i|) * sum(t in T^m_i, d^m_i,t)

model_visual_distance^m =
    (1 / |T^m|) * sum(t in T^m, page_visual_distance^m_t)
```

`T^m` is the set of page types successfully judged by model `m`, and `T^m_i`
is the successful subset containing sample `i`. This gives page types equal
weight even when page availability differs. The report keeps models separate;
it never averages scores across judge models.

Every page artifact records its model, prompt version, temperature, screenshot
references, raw response, and parse errors. A malformed response is preserved
with a null page distance and excluded from aggregates rather than being
converted to zero. With no successful page, the model-level visual distance is
null. `variance.json` has an empty `visual_judges` array when no model is
requested.

### Error behavior

- Fewer than two URLs is a CLI/configuration error.
- Invalid or missing metrics or representative-page accessibility-tree
  artifacts fail loudly. Missing optional page types are omitted.
- When visual judging is requested, a missing screenshot for an otherwise
  selected representative page fails loudly.
- Unsupported models, missing credentials, and provider-call failures fail the
  command. A completed malformed model response is instead quarantined in its
  page artifact with parse errors.
- A snapshot with no representative page cannot be compared.
- If sample `k` fails, completed child runs `0..k-1` remain resumable, but no
  partial `variance.json` is written.

## Alternative

Comparing raw DOM trees or generated React component files was rejected because
CSS wrappers, framework implementation choices, content values, and build-tool
output dominate those representations without necessarily changing website
structure.

Pairwise distance was used through v0.3, then replaced by distance from a cohort
mean in v0.4. Pairwise output grows quadratically as shops are added and does
not directly answer which shop deviates from the cohort's shared center.

Navigation, node count, and interactive ratio were also removed in v0.4 because
the intended analysis only needs element-type distribution and maximum depth.

An order-aware AXTree traversal distance was implemented in v0.2 as
Composition, then removed in v0.3 because it over-penalized layouts containing
the same semantic elements in a different order.

An LLM section classifier was rejected for the deterministic metric because its
own run-to-run variance would be mixed into AXTree structure. The optional
visual judge is deliberately separate, model-labelled, and auditable so its
subjectivity cannot be mistaken for a deterministic measurement.

Pixel-wise screenshot distance was rejected because product imagery and text
rendering dominate raw pixels even when two shops share the same visual design.

## Execution Table

| Requirement | Implementation surface | Verification |
| --- | --- | --- |
| Closed snapshot/report schemas | `shop_arena.env_eval.structure.schema` | schema rejection tests |
| URL-run snapshot extraction | `shop_arena.env_eval.structure.snapshot` | six-page AXTree fixture tests |
| Mean and sample distances | `shop_arena.env_eval.structure.distance` | exact three-shop tests |
| Cohort orchestration | `shop_arena.env_eval.structure.compare` | mocked evaluator tests |
| Optional visual judge | `shop_arena.env_eval.structure.visual` | fake-client schema and aggregation tests |
| Conditional-LLM URL CLI | `shop_arena.env_eval.cli compare` | CLI, credential-loading, and forced-`no_rubric` tests |
| User documentation | root and EnvEval READMEs | command and formula examples |

## Appendix

### Interpretation

A low pair of sample distances means that shop is structurally close to the
cohort center; it does not mean the structure is correct. A separate manual-
fidelity evaluation is required to detect a cohort of consistently wrong shops.

The centroid changes when a shop is added or removed, so all sample deviations
must be recomputed for the new cohort. This is intentional: each distance
describes the shop relative to the exact cohort in that report.

Visual distance is a calibrated judge opinion, not a metric-space distance: it
need not satisfy symmetry or the triangle inequality. Comparing absolute values
across judge models is therefore not supported. Repeat evaluations should pin
the model id and prompt version, and should retain the raw page artifacts.
