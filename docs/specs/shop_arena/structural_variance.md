# URL-based structural variance

Status: **Implemented**
Version: **0.3**
Date: 2026-07-26

## Overview

Structural variance measures how much independently generated storefronts differ
when they were produced from the same Shop Manual. Each sample is a hosted shop
URL. The evaluator uses rendered browser state, not generated source files or
SandboxShop data files.

The feature extends `shop_arena.env_eval` with a cohort command:

```bash
shop-env-eval compare <url> <url> [<url> ...]
```

For each URL, the command builds a deterministic navigation graph and extracts
the accessibility-role profile of one discovered representative for each
available typical page type: homepage, collection, product detail page, policy,
cart, and search. It reports Navigation and Role Profile distances for every
shop pair, including the Role Profile components for every shared page type.

The comparison is always LLM-free. It does not load model credentials or expose
model and rubric options. It measures output-to-output variance only; fidelity
to the source Shop Manual is a separate concern because the manual is not an
input.

## Terminology

- **Sample** — one hosted shop URL and its EnvEval run.
- **Cohort** — two or more samples compared in one invocation.
- **Structural snapshot** — the normalized, content-independent representation
  derived from one EnvEval run and written as `structure.json`.
- **URL node** — a canonical page-class node such as `/`,
  `/collections/<*>`, or `/products/<*>`.
- **Representative page** — the single deterministic URL selected by EnvEval
  for one typical page type: homepage, collection, product, policy, cart, or
  search. Unavailable types are omitted.
- **Role profile** — an order-independent summary of the roles and shape in one
  representative page's accessibility tree.
- **Pairwise distance** — a number in `[0, 1]`; `0` means identical under the
  metric and `1` means maximally different.
- **Structural variance** — the arithmetic mean of all pairwise distances in a
  cohort. The report also includes median, p90, minimum, and maximum.

## Current Status

EnvEval emits the source artifacts used by this comparison:

- canonical URL nodes and directed edges in `transition/graph.json`;
- per-page accessibility trees under `observation/`;
- discovered representative pages and shop identity in `metrics.json`;
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
4. make no LLM calls and require no LLM credentials;
5. remain order-independent because the primary question is what UI semantics
   are present, not their exact accessibility-tree traversal order;
6. preserve every completed per-URL EnvEval run if a later sample fails.

## Proposal

### CLI and output

The CLI surface is:

```bash
shop-env-eval compare URL URL [URL ...] [--out PATH]
                      [--viewport WIDTHxHEIGHT] [--max-hops N]
                      [--rediscover]
```

The comparison always constructs each `EvalConfig` with `no_rubric=True`.
Consequently the screenshot rubric and `/pages/<slug>` classifier are stubbed,
and the comparison makes no LLM calls. Rubric and model options are deliberately
absent from the compare CLI and `CompareConfig`.

Samples run serially to bound browser and local-server resource usage. The
default output directory is
`outputs/shop_env_evals/comparisons/<run_id>/`. An explicit `--out` makes the
child EnvEval run directories resumable through the existing EnvEval rules.

```text
<comparison_dir>/
├── runs/
│   ├── 000-<host>/
│   │   ├── metrics.json
│   │   ├── transition/
│   │   ├── observation/
│   │   └── structure.json
│   └── 001-<host>/...
└── variance.json
```

The command prints the `variance.json` path on stdout.

### Structural snapshot

`structure.json` is a closed Pydantic document containing:

- source URL and EnvEval version;
- sorted canonical URL-node ids;
- sorted canonical URL-to-URL edges represented by source, target, and action
  type, excluding concrete href labels;
- one page-structure record per available representative page type selected by
  EnvEval. Other crawled URL nodes remain in the navigation graph but do not
  contribute Role Profile samples.

A page-structure record contains:

- representative page type and canonical page id;
- an accessibility-role count histogram (normalized when compared);
- semantic node count;
- interactive node count;
- semantic maximum depth.

The role histogram lowercases role names and drops presentational, text-only,
root-web-area, and generic wrapper roles. Accessible names and browser-assigned
ids never enter the snapshot. AXTree child order is not stored.

### Pairwise distances

For two snapshots `A` and `B`, the report contains two metrics:

1. **Navigation** — the equal mean of the Jaccard distances between their URL-
   node sets and canonical URL-edge sets.
2. **Role Profile** — an equal mean of four order-independent components,
   calculated for every shared representative page type and then averaged
   across those pages.

For one shared page, the Role Profile components are:

```text
role_distribution = 0.5 * sum_role(abs(p_A(role) - p_B(role)))
node_count         = abs(nodes_A - nodes_B) / max(nodes_A, nodes_B, 1)
interactive_ratio  = abs(interactive_A / max(nodes_A, 1)
                         - interactive_B / max(nodes_B, 1))
maximum_depth      = abs(depth_A - depth_B) / max(depth_A, depth_B, 1)
score              = mean(role_distribution, node_count,
                          interactive_ratio, maximum_depth)
```

`p_A` and `p_B` are normalized role histograms. If both histograms are empty,
their role-distribution distance is `0`; if only one is empty, it is `1`.
Jaccard distance for two empty sets is `0`.

The pair-level Role Profile contains the mean of each component across shared
page types, followed by their equal-weight mean as `score`. Every pair also
contains the same five values for each shared page type, together with the
canonical ids used on the left and right.

The report intentionally has no order-aware Composition metric, Interaction
metric, blended Overall score, or LLM-derived score. Navigation and Role Profile
remain first-class rather than being blended because they answer different
questions.

For `n` samples, each reported cohort summary uses all unordered pairs. Its
mean is:

```text
2 / (n * (n - 1)) * sum(distance(i, j) for i < j)
```

### Error behavior

- Fewer than two URLs is a CLI/configuration error.
- Invalid or missing graph, metrics, or representative-page accessibility-tree
  artifacts fail loudly with a structural-comparison error. Missing optional
  page types are omitted.
- Two snapshots with no shared representative page type cannot produce a Role
  Profile and fail loudly.
- If sample `k` fails, completed child runs `0..k-1` remain resumable, but no
  partial `variance.json` is written.

## Alternative

Comparing raw DOM trees or generated React component files was rejected because
CSS wrappers, framework implementation choices, content values, and build-tool
output dominate those representations without necessarily changing website
structure.

An order-aware AXTree traversal distance was implemented in v0.2 as
Composition, then removed in v0.3. It over-penalized layouts that contained the
same semantic UI elements in a different order, while this use case primarily
cares about what the generated website includes.

An LLM section classifier was also rejected. It could produce labels such as
`hero` or `featured_collection`, but its own run-to-run variance would be mixed
into the quantity being measured.

## Execution Table

| Requirement | Implementation surface | Verification |
| --- | --- | --- |
| Closed snapshot/report schemas | `shop_arena.env_eval.structure.schema` | schema rejection tests |
| URL-run snapshot extraction | `shop_arena.env_eval.structure.snapshot` | graph/AXTree fixture tests |
| Pairwise deterministic distances | `shop_arena.env_eval.structure.distance` | exact component tests |
| Cohort orchestration | `shop_arena.env_eval.structure.compare` | mocked evaluator tests |
| LLM-free URL CLI | `shop_arena.env_eval.cli compare` | CLI and forced-`no_rubric` tests |
| User documentation | root and EnvEval READMEs | command and formula examples |

## Appendix

### Interpretation

Low variance means generations converge on similar navigation and accessible UI
structure; it does not mean that structure is correct. A separate manual-
fidelity evaluation is required to detect a cohort of consistently wrong shops.

Role Profile is order-independent, but maximum depth still captures coarse page
shape. Navigation separately captures which canonical page classes and links
exist across the site.
