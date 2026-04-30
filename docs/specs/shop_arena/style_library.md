# Style Library (`packages/shop_arena/src/shop_arena/gen/style_library`)

Status: **Spec (draft)** · Version: **0.1**
Owners: ShopArena

> A curated catalog of **style guides** — markdown design-system
> documents (with YAML frontmatter) compiled once per Shopify theme
> from the theme's source + live demo store, and consumed by `shop_arena.gen`
> as optional render-phase context to steer visual treatment of
> generated Hydrogen storefronts.

---

## 1. Overview

`shop_arena.explore` produces an anonymized Shop Manual that captures
**structure, IA, and feature behavior** of a live storefront. By design,
it does **not** capture visual identity (palette, typography, density,
imagery direction, motion) — visual identity is the most identity-
coupled signal a brand has, and the published manual must stay
brand-free so downstream consumers can rebuild a sandbox without leaking
the source.

`shop_arena.gen` therefore needs a *separate* source of visual identity to
produce a coherent Hydrogen storefront. This spec defines that source:
a small, repo-committed library of **style guides** distilled from
Shopify's free first-party themes. Each guide is a markdown document
with a structured frontmatter, compiled once via a multimodal LLM
pipeline that ingests both the theme's source code (for tokens) and a
Playwright capture of the theme's live demo store (for gestalt).

Three design choices shape the module:

- **Curated catalog, not per-run synthesis.** Style is a gestalt that
  does not merge cleanly across seed shops. Rather than synthesize
  style at run time, `shop_arena.gen` *selects* one pre-coherent guide from
  a library that Shopify designers have already curated. Selection is
  well-defined; cross-seed gestalt synthesis is not. See §6 for the
  rejected alternatives.
- **Hybrid representation: prose + frontmatter.** The compiled artifact
  is a markdown document (gestalt, voice, component descriptions —
  consumed by LLM render steps) with a YAML frontmatter (palette /
  font / spacing tokens — consumed mechanically by Tailwind theme
  config and CSS variables). The two halves answer different questions
  and the consumers are different. See §5.2.
- **Compile-time cost, run-time near-zero.** Compilation is a one-time,
  per-theme pipeline that runs offline; the output is committed. Per
  `shop_arena.gen` run, style steering is just one extra context block in
  existing render-phase LLM prompts. The catalog is an asset, not a
  dependency.

`shop_arena.explore`'s schema, prompts, and synthesis are **not changed** by
this spec. The Shop Manual stays brand-free and visual-identity-free
exactly as today.

---

## 2. Terminology

- **Style Guide** — one compiled artifact: a markdown file
  (`<id>.style.md`) with a YAML frontmatter and a fixed canonical H2
  section structure. Distilled from one Shopify theme.
- **Style Library** — the committed catalog of style guides shipped
  with the repo at
  `packages/shop_arena/src/shop_arena/gen/style_library/presets/`.
- **Style Compilation** — the offline pipeline that turns a
  `(theme source, theme demo)` pair into a style guide. Implemented as
  a standalone CLI (`style-compile`).
- **Style Steering** — `shop_arena.gen`'s consumption of a style guide. A
  guide is injected into render-phase LLM prompts as system-prompt
  context.
- **Frontmatter** — the YAML header of a style guide. Closed pydantic
  schema; mechanically validated.
- **Theme demo** — Shopify's hosted preview store for a given free
  theme (e.g. `theme-dawn-demo.myshopify.com`,
  `theme-sense-demo.myshopify.com`).
- **Compile evidence** — the Playwright artifacts (screenshots, a11y
  snapshots) captured during compilation, committed alongside the
  style guide for reproducibility.

---

## 3. Current Status

Nothing exists. Concretely:

- `packages/shop_arena/src/shop_arena/gen/templates/hydrogen/` ships a
  default Hydrogen template; its visual surface (Tailwind config, CSS
  variables, component styling) is whatever the template ships with —
  no per-shop steering.
- `shop_arena.gen.config` has no `style_guide` field.
- `shop_arena.gen.cli` has no `--style-guide` flag.
- `shop_arena.explore.capabilities.Capabilities` has no `style` section, and
  per the previous design discussion (and §6 of this spec) it stays
  that way.

The closest existing surface is `shop.tone` (an anonymized list of tone
tags captured by `shop_arena.explore`), which this spec uses as the input to
auto-selection. No code change to `shop_arena.explore` is required.

---

## 4. Desired Status

### 4.1 I/O contract

**Style Library** (committed asset):

```
packages/shop_arena/src/shop_arena/gen/style_library/
├── presets/
│   ├── dawn.style.md
│   ├── sense.style.md
│   ├── crave.style.md
│   ├── studio.style.md
│   └── ...
├── evidence/
│   ├── dawn/
│   │   ├── screenshots/
│   │   │   ├── 01-homepage.png
│   │   │   ├── 02-pdp.png
│   │   │   ├── 03-cart-drawer.png
│   │   │   ├── 04-collection.png
│   │   │   ├── 05-search.png
│   │   │   ├── 06-button-hover.png
│   │   │   └── 07-mobile-nav.png
│   │   └── snapshots/
│   │       └── ...
│   └── ...
└── README.md
```

Each `<id>.style.md` is a self-contained, human-reviewable design
document. The `evidence/<id>/` subtree exists for reproducibility and
is referenced by the guide's frontmatter (`evidence_sha`).

**Style Compile CLI**:

```
style-compile <theme-id> \
    --source <path-or-git-url> \
    --demo <demo-url> \
    --out style_library/presets/<theme-id>.style.md \
    [--mode {hybrid|source-only|live-only}]
```

Exit 0 iff a schema-validated style guide is written.

**Style Steering** (shop_arena.gen integration):

```
shop-gen \
    --seeds <manual_dir>... \
    --out <out_dir> \
    [--style-guide <path-to-style.md>]   # explicit; v0 only
```

If `--style-guide` is set, the named file's prose body and frontmatter
are threaded into render-phase LLM prompts as ground truth for visual
treatment. If not set, `shop_arena.gen` runs as today (template defaults).

### 4.2 Success criteria

| ID | Criterion |
| -- | --------- |
| SC1 | Every committed `<id>.style.md` parses against the closed frontmatter pydantic schema and contains every canonical H2 section in §A.1. |
| SC2 | Every committed style guide passes a deterministic anonymization scrubber (no real third-party brand mentions; theme name itself is allowed in `frontmatter.id` and `frontmatter.source` only). |
| SC3 | `style-compile` is reproducible: same `(source SHA, evidence SHA, model version, prompts SHA)` → byte-identical guide modulo LLM nondeterminism, which is bounded by low-temp + cassette tests. |
| SC4 | `shop-gen --style-guide PATH` is purely additive: a run without the flag produces byte-identical output to a run on the same inputs before this spec landed. |
| SC5 | Catalog v0 ships with ≥ 3 compiled style guides covering distinct aesthetic positions (default neutral, editorial light, bold maximalist) so steering tests have meaningful contrast. |

---

## 5. Proposal

### 5.1 Architecture

Two independent halves; neither depends on the other at run time:

```
                      offline (one-time per theme)
┌──────────────────────────────────────────────────────────────────┐
│  Style Compilation Pipeline (style-compile CLI)                  │
│                                                                  │
│   theme repo (pinned SHA)        theme demo store                │
│           │                              │                       │
│           ▼                              ▼                       │
│   1. Mechanical extraction      1'. Playwright capture           │
│      settings_*.json + base.css     homepage / PDP / cart /      │
│      → frontmatter tokens           collection / search / button │
│      (no LLM)                       hover / mobile nav           │
│                                     → evidence/<id>/             │
│                                     (no LLM, reuses              │
│                                      pi-playwright wrapper)      │
│           │                              │                       │
│           └──────────────┬───────────────┘                       │
│                          ▼                                       │
│   2. Per-section multimodal LLM compilation                      │
│      one call per canonical H2; per-section input routing        │
│      (§5.4); model = claude-opus-4-7                             │
│                                                                  │
│   3. Text-only synthesis                                         │
│      one LLM call merges parts → cohesive style.md prose body    │
│                                                                  │
│   4. Frontmatter injection (mechanical, from step 1)             │
│           │                                                      │
│           ▼                                                      │
│   style_library/presets/<id>.style.md  (committed)               │
└──────────────────────────────────────────────────────────────────┘

                      per-run (every shop-gen invocation)
┌──────────────────────────────────────────────────────────────────┐
│  Style Steering (shop_arena.gen render phase)                          │
│                                                                  │
│   --style-guide PATH                                             │
│           │                                                      │
│           ▼                                                      │
│   1. Load + validate (frontmatter against schema)                │
│   2. Frontmatter → Hydrogen Tailwind config + CSS variables      │
│      (mechanical; deterministic)                                 │
│   3. Prose body → injected into render-phase prompts as          │
│      "## Visual identity" ground-truth context                   │
│           │                                                      │
│           ▼                                                      │
│   <out_dir>/hydrogen/  (styled per the guide)                    │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Style Guide format

Every `<id>.style.md` has the same shape: a YAML frontmatter, then a
fixed canonical H2 section sequence.

#### 5.2.1 Frontmatter

Closed pydantic v2 schema; extra fields rejected.

```yaml
---
id: dawn                          # str, [a-z0-9_-]+, matches filename stem
name: "Dawn"                      # str, human-readable theme name (allowed PII; this is the source theme, not a third party)
source:                           # SourceRef
  kind: github
  repo: "Shopify/dawn"
  sha: "9f3c2a1..."               # exact pinned commit
  license: "MIT"
demo:                             # DemoRef
  url: "https://theme-dawn-demo.myshopify.com"
  evidence_sha: "sha256:..."      # hash of evidence/<id>/ directory tree
compiled_with:                    # CompileRef
  model: "anthropic/claude-opus-4-7"
  prompts_sha: "sha256:..."       # hash of prompts/ at compile time
  pipeline_version: "0.1"
  ts: "2026-04-27T00:00:00Z"
mode: "hybrid"                    # enum: hybrid | source-only | live-only
tone_tags:                        # list[str], free-form, capped at 5
  - minimal
  - neutral
  - editorial-light
palette:                          # PaletteTokens
  background: "#ffffff"
  foreground: "#121212"
  accent_primary: "#121212"
  accent_secondary: null
  surface_muted: "#f3f3f3"
  border: "#e1e1e1"
fonts:                            # TypographyTokens
  heading:
    stack: "Assistant, sans-serif"
    weight: 400
    scale_factor: 1.25
    case: "sentence"              # enum: sentence | title | upper
  body:
    stack: "Assistant, sans-serif"
    weight: 400
    scale_factor: 1.0
density: "airy"                   # enum: compact | comfortable | airy
corner_radius: "subtle"           # enum: none | subtle | prominent
button_shape: "rounded"           # enum: square | rounded | pill
motion_intensity: "subtle"        # enum: none | subtle | prominent
imagery_style: "lifestyle"        # enum: lifestyle | studio | editorial | ugc | illustrative | mixed
---
```

The frontmatter schema lives at
`packages/shop_arena/src/shop_arena/gen/style_library/schema.py`. All
enum-typed fields use closed string enums. `palette.*` accepts `null`
for slots the theme leaves unset; downstream consumers fall back to
template defaults for null slots.

#### 5.2.2 Canonical sections

Every guide must contain these H2 sections in this order. Synthesis
(step 3 of compile) enforces the order; missing sections are a compile
error.

| H2 | Source signal it answers from | Notes |
| -- | ----------------------------- | ----- |
| `## Visual identity` | Screenshots (gestalt) + tokens | 2–4 sentences: the theme's design statement in plain prose. |
| `## Typography` | Tokens + a typography-focused screenshot | Type pairing, hierarchy, common cases, weight discipline. |
| `## Color & contrast` | Tokens + homepage screenshot | Palette role assignment (where each slot is used), contrast posture (light/dark/inverted accents). |
| `## UI components` | Component CSS slices + interaction screenshots | Per-component H3 blocks: Buttons, Cards, Form controls, Drawers, Modals, Navigation, Badges. Each H3 follows a fixed bullet template (Variants / Anatomy / States / Spacing). |
| `## Layout & spacing` | Tokens + multi-section screenshot | Spacing scale, container widths, grid posture, breakpoint behavior. |
| `## Motion` | CSS transitions + hover-state screenshots | Transition durations, easing posture, what animates and what doesn't. |
| `## Imagery` | Screenshots only | Subject matter, treatment (full-bleed, framed, masked), aspect-ratio bias. |
| `## Voice` | Screenshots (visible copy) only | Headline cadence, capitalization discipline, microcopy register. |

Component H3 blocks share a fixed bullet template — the same discipline
that makes shop_arena.explore parts mergeable:

```markdown
### Buttons

- **Variants:** primary (filled), secondary (outline), ghost (text-only).
- **Anatomy:** label only; icon-leading variant for cart/wishlist actions.
- **States:** rest, hover (1px lift + shadow), active (sink), disabled (50% opacity).
- **Spacing:** 12px vertical, 24px horizontal; full-width on mobile.
```

### 5.3 Compile pipeline

Four steps, mirroring `shop_arena.explore`'s pattern (deterministic prefetch
→ per-task LLM → synthesis):

#### 5.3.1 Step 1 — Mechanical extraction (no LLM)

Inputs:

- `settings_schema.json` (theme repo)
- `settings_data.json` (theme repo)
- `assets/base.css` (or theme-equivalent token block)
- A small allowlist of `snippets/component-*.css` files for component
  surface inventory

Output: a `_extracted.json` blob and a partially-populated frontmatter
dict. No LLM, deterministic.

#### 5.3.2 Step 1' — Playwright capture (no LLM)

Inputs:

- `demo` URL (e.g. `theme-dawn-demo.myshopify.com`)

Reuses `pi-playwright` exactly as `shop_arena.explore` does. Captures a
**curated, style-focused interaction set** — narrower than
shop_arena.explore's full executor task list:

| # | State | Purpose |
| - | ----- | ------- |
| 1 | Homepage | Overall composition, hero treatment, section rhythm |
| 2 | PDP | Gallery, variant controls, type hierarchy, CTA |
| 3 | Cart drawer (with 1 product added) | Drawer style, line-item anatomy, totals layout |
| 4 | Collection | Card grid, filter chrome, sort UX |
| 5 | Search results (or predictive) | Search treatment if exposed |
| 6 | Button hover | Interaction feel, motion intensity |
| 7 | Mobile nav (open) | Off-canvas pattern, density posture |

Output: `evidence/<id>/screenshots/NN-<state>.png` plus paired a11y
snapshots. Committed; the directory tree's hash lands in
`frontmatter.demo.evidence_sha`.

#### 5.3.3 Step 2 — Per-section multimodal compilation

One LLM call per canonical H2 section in §5.2.2. Each call's input is
*routed*: only the evidence the section can actually answer from is
passed in. See §5.4 for the routing table.

Model: `anthropic/claude-opus-4-7` (multimodal, low temperature). Pinned
in `frontmatter.compiled_with.model` so future re-compiles are
auditable.

Each call writes `parts/<section>.md` under a temp compile workspace,
following the same parts-style pattern shop_arena.explore uses internally.

#### 5.3.4 Step 3 — Synthesis

One text-only LLM call merges `parts/*.md` into one cohesive
`style.md` body, applying:

- Canonical H2 ordering enforcement (§5.2.2)
- Voice consistency (rejection of contradictory claims across parts)
- Anonymization scrub (no real third-party brand mentions; theme's own
  name is allowed only via the `id`/`name`/`source` frontmatter slots,
  not in the prose)

Prompt structure mirrors `shop_arena.explore`'s `synthesize_manual.md`:
inputs first (the merged frontmatter + parts), then a strict output
contract.

#### 5.3.5 Step 4 — Frontmatter injection

Mechanical step: prepend the YAML frontmatter (built from step 1's
extracted tokens + step 1's source/demo metadata + step 2's prompt SHA
+ pipeline timestamp) to the prose body.

Validation:

- Frontmatter parses against pydantic schema → fail-loud on any drift.
- Prose contains every canonical H2 section → fail-loud on any miss.
- Anonymization scrubber clean → fail-loud on any third-party brand
  match.

Output: `style_library/presets/<id>.style.md`.

### 5.4 Per-section input routing

Per §5.2.2 each H2 section has different input needs. The compile
pipeline routes inputs accordingly to keep token cost bounded and
output quality high.

| H2 section | Frontmatter tokens | CSS slices | Screenshots | Notes |
| ---------- | :----------------: | :--------: | :---------: | ----- |
| Visual identity | ✓ | — | 1 (homepage) | Gestalt question; mostly screenshot-driven. |
| Typography | ✓ (fonts) | base.css type rules | 1 (PDP — densest text) | Tokens authoritative; screenshot for context. |
| Color & contrast | ✓ (palette) | — | 1 (homepage) | Tokens authoritative; screenshot for role assignment. |
| UI components | — | component-*.css subset | 4 (PDP, cart drawer, button hover, mobile nav) | CSS for surface inventory; screenshots for state truth. |
| Layout & spacing | ✓ (density) | base.css spacing | 2 (homepage, collection) | Mixed — measurement + visual rhythm. |
| Motion | — | base.css transitions | 1 (button hover) | CSS for what animates; screenshot for emergent feel. |
| Imagery | — | — | All screenshots | Source code is silent on imagery direction. |
| Voice | — | — | All screenshots (visible copy) | Source code can't answer this; screenshots only. |

### 5.5 Fallback paths

The default `--mode hybrid` requires both source and a hosted demo.
Two fallback modes degrade gracefully when one input is missing:

| Mode | Source | Demo | Used when | Quality posture |
| ---- | :----: | :--: | --------- | --------------- |
| `hybrid` | ✓ | ✓ | Default. All 12 free Shopify themes today. | Best — tokens authoritative, gestalt observed. |
| `source-only` | ✓ | — | Theme repo exists but no live demo (e.g. an internal theme, an unreleased theme). | Frontmatter tokens accurate; prose flatter (gestalt inferred from source alone). |
| `live-only` | — | ✓ | Demo URL provided but no source access (e.g. paid theme demo, a non-Shopify storefront we want to mimic). | Frontmatter tokens *measured-from-DOM* via `getComputedStyle()` (see §5.5.1) and so are approximate; prose strong. |

A short reference video (e.g. a screen recording of the demo) is **not**
in v0. Tracked under §7 as a future input mode.

#### 5.5.1 `live-only` measurement protocol

When source is unavailable, frontmatter tokens come from `pw.js eval`
on the demo:

- `palette.*` ← `getComputedStyle(document.body).backgroundColor` and
  similar, sampled across page types and reduced to a closed slot map.
- `fonts.*` ← `getComputedStyle(document.body, h1, button).fontFamily`.
- `density` ← derived from measured padding/line-height ratios via a
  small heuristic.

These values are **approximate** by definition; the frontmatter records
`mode: "live-only"` so consumers can apply tighter validation if they
care. Hex values from this path are still safe to commit because they
came from a Shopify-hosted demo store the theme designer published; we
are not exfiltrating private brand assets.

### 5.6 Style Steering — `shop_arena.gen` integration

Pure addition to `shop_arena.gen`. Three integration points; nothing else
moves:

#### 5.6.1 CLI

```
shop-gen --style-guide PATH ...
```

- Path is required to exist and to parse against the v0 frontmatter
  schema; otherwise exit 2 with a clear error.
- Exactly one `--style-guide` is allowed. Multiple → exit 2.
  Rationale: blending two style guides re-introduces the gestalt-merge
  problem we are explicitly avoiding.
- Default (no flag): `shop_arena.gen` runs exactly as today.

#### 5.6.2 Configuration & state

`shop_arena.gen.config.ShopGenConfig` grows one field:

```python
style_guide_path: Path | None = None
```

Loaded into `state.RunState` and surfaced in the run manifest under
`config_snapshot.style_guide` (path + frontmatter `id` + frontmatter
SHA), so re-runs and resumes can detect drift.

#### 5.6.3 Render-phase prompt injection

Phase 4 (build harness loop) prompts that emit Hydrogen prose
(component code, Tailwind extensions, CSS variable bindings) gain one
extra system-prompt section when `style_guide_path` is set:

```markdown
## Visual identity (style guide ground truth)

The merged manual is ground truth for **structure** (sections,
features, IA). The style guide below is ground truth for **visual
treatment** (palette, typography, components, motion, imagery). Where
they conflict, structure wins.

<verbatim style.md prose body>
```

The frontmatter is consumed mechanically in a separate, deterministic
step that emits:

- `hydrogen/tailwind.config.ts` — palette, font scale, density, radius
- `hydrogen/app/styles/tokens.css` — CSS variables for slot use
- `hydrogen/app/styles/typography.css` — font face imports + scale

These mechanical outputs land *before* the harness loop, so the loop's
LLM steps see a consistent token surface and can apply the prose
guidance against it.

#### 5.6.4 Conflict resolution

When the manual's structural facts and the style guide's component
guidance overlap (e.g. manual says `cart.type=drawer`, guide describes
a cart-page pattern), the prompt's "structure wins" rule applies. The
guide is treated as taste guidance, not a substitute spec; the
manual's `Capabilities` remain the only schema-validated ground truth
in Phase 4.

### 5.7 Module layout

```
packages/shop_arena/src/shop_arena/gen/style_library/
├── __init__.py
├── schema.py          # closed frontmatter pydantic models
├── compile/
│   ├── __init__.py
│   ├── cli.py         # `style-compile` entrypoint
│   ├── extract.py     # step 1: mechanical token extraction
│   ├── capture.py     # step 1': Playwright capture (reuses pi-playwright)
│   ├── compose.py     # step 2: per-section LLM calls (multimodal)
│   ├── synthesize.py  # step 3: text-only synthesis
│   ├── frontmatter.py # step 4: YAML injection + final validation
│   └── prompts/
│       ├── compose_visual_identity.md
│       ├── compose_typography.md
│       ├── compose_color.md
│       ├── compose_components.md
│       ├── compose_layout.md
│       ├── compose_motion.md
│       ├── compose_imagery.md
│       ├── compose_voice.md
│       └── synthesize.md
├── presets/           # committed catalog (asset)
│   ├── dawn.style.md
│   └── ...
├── evidence/          # committed evidence (asset)
│   └── <id>/
│       ├── screenshots/
│       └── snapshots/
├── steering.py        # shop_arena.gen integration: load + validate + render
└── README.md
```

`schema.py`, `steering.py`, and the prompts are the public surface
shop_arena.gen depends on. The `compile/` subtree is offline-only; `shop_arena.gen`
runs never import it.

### 5.8 CLI surface

#### 5.8.1 `style-compile`

```
style-compile <theme-id> \
    --source <path-or-git-url-with-sha> \
    --demo <demo-url> \
    --out <path-to-style.md> \
    [--mode {hybrid|source-only|live-only}] \
    [--evidence-dir <path>] \
    [--model <runtime/model>] \
    [--force]
```

- `--mode` defaults to `hybrid`. `source-only` skips step 1';
  `live-only` skips step 1.
- `--evidence-dir` defaults to a sibling `evidence/<theme-id>/` next to
  the output.
- `--force` overwrites an existing output (otherwise exit 2 to prevent
  silent re-compiles).

Exit codes:

| Code | Meaning |
| ---- | ------- |
| 0    | Compiled, validated, written. |
| 2    | CLI argument or input file error. |
| 3    | Pipeline produced output that failed schema or scrubber validation. |
| 4    | Demo unreachable in `hybrid`/`live-only`. |
| 5    | Source unreadable in `hybrid`/`source-only`. |

#### 5.8.2 `shop-gen` additions

Documented in §5.6.1. No other CLI changes.

---

## 6. Alternatives

### 6.1 Capture style in `shop_arena.explore`

Add a `Style` section to the closed `Capabilities` schema; add a
canonical `visual_style` task to the planner; add a `## Visual style`
H2 to synthesis; merge `Style` across seeds in `shop_arena.gen`'s
`merge_capabilities` step (Path 4 — single LLM "style synthesizer"
call).

**Rejected because:** style is a gestalt that does not merge cleanly.
Independent per-leaf merge of style enums produces aesthetically
incoherent combinations (e.g. `dark + warm + serif + dense + lifestyle`).
The "single LLM synthesizer call" workaround hides the problem rather
than solving it. The per-shop captured style is also low-signal — the
executor sees one shop's style, not a designed gestalt — and adds
~75 LOC across schema/prompts/synthesis for a feature that produces a
worse output than a curated catalog. See the design discussion log
(2026-04-27).

### 6.2 Swappable themes (Liquid theme catalog)

Vendor the 12 free Shopify themes wholesale; `shop_arena.gen` picks one and
customizes its `settings_data.json` per merged shop tone.

**Rejected because:** the existing `shop_arena.gen` target is a Hydrogen
storefront, not a Liquid theme. Adopting Liquid as a parallel render
target would double `shop_arena.gen`'s output surface for a feature that, at
its essence, only needs the theme's *style information* — not its
implementation. Extracting that information into a portable format
(this spec's `style.md`) gets the benefit at a fraction of the cost.

### 6.3 Pure-JSON style preset library

Same catalog idea, but each entry is a structured JSON config (palette
slot map, font slot map, density enum) applied mechanically to the
Hydrogen Tailwind config.

**Rejected because:** JSON loses the gestalt. Hydrogen render steps in
`shop_arena.gen` are LLM-driven and produce substantially better output from
prose design-system descriptions than from JSON configs they have to
re-interpret. The hybrid prose + frontmatter format in §5.2 keeps the
JSON-like benefits (deterministic, schema-validated, easy to consume
mechanically) while adding the prose layer where it materially improves
LLM output.

### 6.4 Pure-screenshot compilation (no source code)

Compile each style guide from screenshots alone (live-only mode).

**Considered, kept as a fallback (§5.5).** Source is the only authority
for exact tokens; a multimodal LLM eyeballing hex codes from screenshots
is unreliable and tends to hallucinate plausible-looking values. The
hybrid pipeline routes inputs (§5.4) so each section answers from the
input it can actually answer from. `live-only` stays available for
themes without source access, with the frontmatter recording `mode` so
downstream consumers can apply tighter validation.

### 6.5 Pure-source compilation (no screenshots)

Compile each style guide from the theme repo alone (source-only mode).

**Considered, kept as a fallback (§5.5).** Visual hierarchy and
imagery direction emerge only at render; source code is silent on both.
`source-only` is acceptable for themes with no live demo (e.g. internal
themes) but produces a flatter prose body. Available as a fallback for
the same reason live-only is.

---

## 7. Open Questions / Tensions Worth Flagging

1. **Auto-selection from merged tone tags.** v0 ships explicit
   `--style-guide PATH` only. An auto picker (`--auto-style`) that
   matches `merged_capabilities.shop.tone` against
   `frontmatter.tone_tags` is a natural follow-up but introduces an
   unbounded LLM tiebreak surface; deferred.

2. **Catalog versioning.** Shopify themes ship updates. Re-compiling a
   guide against a newer theme SHA produces a "different" guide; do we
   pin to a single SHA per id, or version (`dawn@v15.style.md`,
   `dawn@v16.style.md`)? v0 pins one SHA per id; revisit if theme
   churn becomes a real problem.

3. **Reference video as a third input mode.** A short MP4 (e.g.
   `pw.js video --output …` of a curated interaction sequence) would
   capture motion fidelity better than per-state screenshots. Multimodal
   LLMs increasingly accept video; deferred to v0.2.

4. **Cross-theme blending.** Operators may want to express "structure
   from Dawn, components from Crave." Explicitly **rejected for v0**
   because it re-opens the gestalt-merge problem the catalog approach
   exists to avoid. If genuinely needed later, the right shape is a
   *new compiled guide* — i.e. compile a hand-authored intermediate
   theme — not a runtime blend.

5. **Component coverage gaps.** `## UI components` lists Buttons,
   Cards, Form controls, Drawers, Modals, Navigation, Badges. Some
   themes may not expose all seven; the H3 block stays present with
   `_(not surfaced in this theme)_` rather than being silently omitted,
   so consumers can detect gaps.

6. **License surface.** All 12 free Shopify themes are MIT-licensed;
   the `frontmatter.source.license` field records that. A
   `style_library/LICENSES.md` collects the original copyright lines
   for the source themes whose tokens we extracted. Paid themes (out
   of scope for v0) would need explicit per-theme licensing review
   before live-only compilation lands.

7. **Determinism of LLM synthesis.** Steps 2 and 3 are non-deterministic
   in principle. Mitigations: low-temperature setting, a pinned model
   version in frontmatter, and (for unit tests) cassette-based replay
   of the LLM completer the same way `shop_arena.gen.manual_merge` tests do
   today. Catalog re-compiles are reviewed by hand before commit, so
   the asset surface stays stable.

---

## 8. Milestones (informative)

**M1 — Frontmatter schema + canonical sections (1 day)**

- `style_library/schema.py` with closed pydantic models for the
  frontmatter (§5.2.1).
- A canonical-sections constant + parser that validates an arbitrary
  `style.md` body (§5.2.2).
- Unit tests on a hand-authored `presets/_test_minimal.style.md`
  fixture.

**M2 — Compile pipeline, hybrid mode, single theme (3–5 days)**

- `style-compile` CLI + the four-step pipeline (§5.3).
- Reuses `pi-playwright` for step 1' (no new browser code).
- One end-to-end run against Dawn (`dawn.style.md`) committed.
- Fixture-based tests: deterministic step 1, mocked LLM for steps 2/3.

**M3 — Catalog v0 (2–3 days)**

- Compile and commit ≥ 3 contrasting style guides: `dawn`
  (default neutral), `sense` (editorial light), `crave` (bold
  maximalist). One human review pass per guide before commit.
- `style_library/LICENSES.md`.

**M4 — Style steering in `shop_arena.gen` (3–5 days, dependency: M3)**

- `shop_arena.gen.config.ShopGenConfig.style_guide_path`.
- `--style-guide PATH` CLI flag + validation.
- `style_library/steering.py` — load, validate, render frontmatter to
  Hydrogen Tailwind/CSS, expose prose body for prompt injection.
- Render-phase prompt extension in Phase 4 build loop.
- Cassette test: `shop-gen` run with `--style-guide` produces a
  Hydrogen Tailwind config that matches the guide's frontmatter palette
  byte-for-byte.

**M5 — Fallback modes (2 days, optional / deferred)**

- `--mode source-only` and `--mode live-only`.
- One regression test per mode against an existing theme that supports
  both (Dawn).

**M6 — Auto-selection (deferred)**

- `shop-gen --auto-style` that picks a guide from
  `merged_capabilities.shop.tone`.

---

## 9. Appendix

### 9.1 Canonical H2 section list

(See §5.2.2 for descriptions.)

1. `## Visual identity`
2. `## Typography`
3. `## Color & contrast`
4. `## UI components`
5. `## Layout & spacing`
6. `## Motion`
7. `## Imagery`
8. `## Voice`

### 9.2 Frontmatter pydantic model (sketch)

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Density(StrEnum):
    compact = "compact"
    comfortable = "comfortable"
    airy = "airy"


class CornerRadius(StrEnum):
    none = "none"
    subtle = "subtle"
    prominent = "prominent"


class ButtonShape(StrEnum):
    square = "square"
    rounded = "rounded"
    pill = "pill"


class MotionIntensity(StrEnum):
    none = "none"
    subtle = "subtle"
    prominent = "prominent"


class ImageryStyle(StrEnum):
    lifestyle = "lifestyle"
    studio = "studio"
    editorial = "editorial"
    ugc = "ugc"
    illustrative = "illustrative"
    mixed = "mixed"


class HeadlineCase(StrEnum):
    sentence = "sentence"
    title = "title"
    upper = "upper"


class CompileMode(StrEnum):
    hybrid = "hybrid"
    source_only = "source-only"
    live_only = "live-only"


class SourceRef(_Closed):
    kind: str             # e.g. "github"
    repo: str
    sha: str
    license: str


class DemoRef(_Closed):
    url: str
    evidence_sha: str


class CompileRef(_Closed):
    model: str
    prompts_sha: str
    pipeline_version: str
    ts: str               # ISO-8601 UTC


class PaletteTokens(_Closed):
    background: str | None = None
    foreground: str | None = None
    accent_primary: str | None = None
    accent_secondary: str | None = None
    surface_muted: str | None = None
    border: str | None = None


class FontSlot(_Closed):
    stack: str
    weight: int
    scale_factor: float
    case: HeadlineCase | None = None


class TypographyTokens(_Closed):
    heading: FontSlot
    body: FontSlot


class StyleGuideFrontmatter(_Closed):
    id: str
    name: str
    source: SourceRef | None = None
    demo: DemoRef | None = None
    compiled_with: CompileRef
    mode: CompileMode
    tone_tags: list[str] = Field(default_factory=list, max_length=5)
    palette: PaletteTokens
    fonts: TypographyTokens
    density: Density
    corner_radius: CornerRadius
    button_shape: ButtonShape
    motion_intensity: MotionIntensity
    imagery_style: ImageryStyle
```

`source` is optional only in `live-only` mode; `demo` is optional only
in `source-only` mode. A model-level validator enforces this.

### 9.3 Reference materials

- Free Shopify themes: <https://themes.shopify.com/themes?price=free>
- Theme demo URL pattern: `theme-<id>-demo.myshopify.com`
- `pi-playwright` skill: see `packages/harness/README.md`
- `shop_arena.explore` evidence layout (mirrored here): see
  [`shop_arena/shop_explore.md`](shop_explore.md) §5.4

### 9.4 Why `compile-once`, not per-shop synthesis

A per-shop runtime style synthesis (the rejected Path 4 from §6.1)
would generate a fresh style description for every `shop_arena.gen` run
based on merged seed signals. The compile-once approach inverts this:

| Aspect | Per-shop runtime synthesis | Compile-once catalog (this spec) |
| ------ | -------------------------- | -------------------------------- |
| Coherence | Risked on every run | Designed once, audited, frozen |
| Determinism | Low (LLM at run time) | High (asset is bytes on disk) |
| Cost | Per-run LLM tokens | One-time compile + free per-run reuse |
| Auditability | Inspect each run's manifest | Inspect the committed file |
| Scope of change | Touches every run's output | Only when the catalog updates |
| Failure blast radius | Per-run | Per-theme (and caught by review) |

The compile-once shape is one of `shop_arena.gen`'s broader patterns:
expensive, taste-driven decisions are compiled into committed assets
(see `brands/fake_brands.json`, `templates/hydrogen/`). The style
library is the same shape applied to visual identity.
