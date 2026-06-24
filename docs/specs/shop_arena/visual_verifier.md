# Visual Verifier (`packages/shop_arena/src/shop_arena/gen/build/verifiers` + `final_eval`)

Status: **Implemented** · Version: **0.1**
Owners: ShopArena

> A new caller-owned **`visual_judge`** verifier that boots a transient
> dev server, asks the agent runtime to drive the **playwright skill**
> against the task's routes, and judges the rendered storefront against
> the merged `capabilities.json`. Plus a per-task retry cap on the
> exec → verify → exec loop, a configurable LLM-judge set, and an
> expanded all-pages visual sweep in the post-loop `final_eval` step.

---

## 1. Overview

`shop_arena.gen` v0.1.0 ships an exec → verify → exec loop driven by
[`harness/verifiers.md`](../harness/verifiers.md). The two LLM judges in
the v0.1 verifier set ([shop_gen.md §5.5.3](shop_gen.md#553-43-exec--verify-loop)) —
`quality_judge` and `cross_task_consistency` — both read **source files**
(`hydrogen/app/**/*.{tsx,ts,css}`). Neither one renders the site, so a
build-loop iteration can pass with code that compiles but a homepage
that looks wrong: misaligned hero, a broken image grid, a footer that
spans the page width. The `final_eval` step (spec §5.5.5) catches a
slice of this with a 5-step playwright smoke + LLM judge, but only
**after** the loop has exited and only across home / one collection /
one product / cart / checkout-redirect.

This spec adds three things:

1. **`visual_judge` verifier.** An LLM verifier that — for the task the
   executor just touched — boots a dev server, asks the configured
   agent runtime to use its **playwright skill** to render the relevant
   routes, captures screenshots, and judges them against
   `capabilities.json`. Runs **inside** the per-iteration verifier
   dispatch, gating `[x]` like every other verifier.
2. **Per-task retry cap on the exec → verify → exec loop.** A soft cap
   (default 3) on how many consecutive `visual_judge` FAILs the loop
   tolerates against one task before the verifier downgrades itself to
   `ADVISORY` and lets the run advance. Caller-side; no harness change.
3. **Expanded `final_eval`.** Replace the fixed 5-step smoke flow with
   an all-pages visual sweep using the same agent-runtime + playwright
   path; report stays advisory per spec §5.5.5.

The verifier is gated by a **configurable judge set**: callers select
which LLM judges (`visual_judge`, `quality_judge`,
`cross_task_consistency`) actually run. Rule verifiers (`tsc`, `build`,
`routes_200`, `data_in_use`, `nav_coverage`, and
`navigation_primitive_usage`) are unaffected and always run. The
`no_brand_leak` rule remains disabled in the current factory because
its allowlist scanner is too noisy for generated Hydrogen source.

This spec **augments** the v0.1 verifier set; `quality_judge` and
`cross_task_consistency` stay. Whether `quality_judge` is subsumed by
`visual_judge` is deferred to v0.2.

---

## 2. Terminology

- **Visual judge** — the new `visual_judge` verifier (§5.2). LLM-based,
  rendered-page driven.
- **Source judge** — the existing `quality_judge` and
  `cross_task_consistency` verifiers (source-file driven).
- **Judge set** — the subset of LLM judges enabled for a run, selected
  by name. Rule verifiers are not part of this set.
- **Task -> routes map** — the deterministic mapping from a `gen_*`
  task id to the route paths the visual judge should render. The
  `visual_fix` task maps to the union of all per-task routes.
- **Visual retry budget** — the per-task cap on consecutive
  `visual_judge` FAILs before the verifier downgrades itself to
  `ADVISORY`. Default 3, configurable via `--visual-retry-budget`.
- **Nested agent iteration** — a `ctx.runtime.run_iteration(...)` call
  the verifier makes from inside the parent loop's verifier dispatch.
  The runtime is the same instance the parent loop drives executor
  iterations with; the prompt and sub-workspace are verifier-owned.
- **Visual sweep** — the all-pages render+judge pass `final_eval` runs
  after the loop exits.

---

## 3. Current Status

- `VisualJudgeVerifier` is implemented in
  `packages/shop_arena/src/shop_arena/gen/build/verifiers/visual_judge.py`.
  It resolves task ids to page buckets, boots a Hydrogen dev server,
  runs a nested `ctx.runtime.run_iteration` against a verifier-owned
  workspace, parses `verdict.json`, applies score / critical-issue
  coercion, and promotes screenshots into verifier evidence.
- `visual_fix` is in the default visual-judge scope and uses page-bucket
  fan-out with a bounded worker count.
- Per-task visual retry budget is implemented by scanning sibling
  verifier telemetry; over-budget failures downgrade to non-blocking
  advisory results.
- `ShopGenConfig.judges`, CLI `--judges`, and
  `default_verifiers_factory(judges=...)` gate the LLM judges
  (`visual_judge`, `quality_judge`, `cross_task_consistency`) while
  rule verifiers remain mandatory.
- Production dev-server wiring uses `pnpm_dev_factory()` and the
  visual verifier is enabled only when the `pi-playwright` skill probe
  succeeds; otherwise it is omitted with a warning.
- `final_eval/visual_sweep.py` and `final_eval/step.py` implement the
  advisory all-pages visual sweep, reusing the visual-judge verdict
  schema and route/bucket helpers. Final-eval sweep concurrency is
  configured separately from in-loop `visual_fix` fan-out so the
  all-bucket sweep can run with a lower browser-process count.
- Tests cover prompt slots, task bucket routing, visual-judge parsing
  and evidence promotion, retry-budget behavior, judge-set selection,
  page-bucket fan-out, and final-eval visual sweep wiring.

---

## 4. Desired Status

### 4.1 I/O contract

**New library config** (additive on `ShopGenConfig`):

| Input                    | Notes                                                                                         |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| `judges`                 | `set[str]` selecting LLM judges. Default `{"visual_judge", "quality_judge", "cross_task_consistency"}`. Rule verifiers always run. |
| `visual_retry_budget`    | `int`. Max consecutive `visual_judge` FAILs against one task before downgrading to `ADVISORY`. Default 3.                          |
| `visual_judge_timeout_s` | `float`. Wall-clock budget for one `visual_judge` nested agent iteration. Default 300 s.                                           |
| `visual_judge_pass_threshold`  | `float`. Score threshold below which a `pass` verdict from the agent is coerced to `fail` (§9.3). Default 7.0.                            |
| `visual_judge_max_concurrency` | `int`. Page-bucket fan-out worker count for the in-loop `visual_fix` task (§5.2.1 step 5). Default 3.              |
| `final_eval_visual_max_concurrency` | `int`. Page-bucket fan-out worker count for the final-eval visual sweep (§5.6), decoupled from `visual_judge_max_concurrency` to bound concurrent headless browsers. Default 2. |

**New CLI surface** (additive):

```bash
shop-gen ... --judges visual_judge,quality_judge       # restrict the LLM-judge set
shop-gen ... --judges none                             # disable all LLM judges (rule verifiers still run)
shop-gen ... --visual-retry-budget 3                   # per-task cap on visual_judge FAILs
shop-gen ... --visual-judge-timeout 300                # per-call wall-clock budget
shop-gen ... --visual-judge-pass-threshold 7.0         # score threshold for pass→fail coercion
shop-gen ... --visual-judge-max-concurrency 3          # in-loop visual_fix fan-out worker count
shop-gen ... --final-eval-visual-max-concurrency 2     # final visual sweep fan-out worker count
```

**New on disk** (additive under existing `runs/build/iters/<id>/checks/verifiers/`):

```
runs/build/iters/<exec_id>/checks/verifiers/
├── visual_judge.json                # standard verifier telemetry (verdict, feedback, details)
└── visual_judge/                    # NEW; only present when visual_judge ran
    ├── work/                        # sub-workspace handed to ctx.runtime.run_iteration
    │   ├── prompt.md                # the prompt body (verbatim copy)
    │   ├── verdict.json             # the structured verdict the agent wrote
    │   └── iter/                    # the runtime's iter_dir (native.log, screenshots/, …)
    └── screenshots/                 # de-duplicated screenshots promoted from iter/screenshots/
```

**New under `<out_dir>/`** (advisory, human-reviewable):

```
<out_dir>/visual_eval/
├── screenshots/                     # final_eval all-pages sweep, per-page subdirs
│   ├── home/
│   ├── collections/<handle>/
│   ├── products/<handle>/
│   ├── pages/<handle>/
│   └── ...
└── report.md                        # advisory markdown summary (linked from final_eval.json)
```

The existing `final_eval.json` schema gains a `visual` subtree alongside
the v0.1 `smoke` + `judge` subtrees:

```jsonc
{
  "ok": true,
  "smoke":  { /* unchanged shape */ },
  "judge":  { /* unchanged shape — old smoke-table judge */ },
  "visual": {                                    // NEW
    "ok": true,
    "verdict": "pass",                           // pass | fail | error (advisory)
    "score": 7.8,                                // weighted average across page-bucket sub-runs (0–10)
    "category_scores": {                         // averaged across sub-runs; absent buckets dropped
      "structure": 8,
      "components": 7,
      "visual_tone": 8
    },
    "pages_judged": 18,
    "feedback": "…markdown…",
    "report_path": "visual_eval/report.md"
  }
}
```

### 4.2 Success criteria

| ID  | Criterion                                                                                                              |
| --- | ---------------------------------------------------------------------------------------------------------------------- |
| SC1 | `visual_judge` runs after a per-iteration executor pass on every task in its applicability set; on PASS the executor's `[x]` mark is preserved. |
| SC2 | A `visual_judge` FAIL rewrites `[x]` → `[~]` and surfaces its feedback under `{{verifier_feedback}}` in the next iteration's prompt. |
| SC3 | After `visual_retry_budget` consecutive FAILs against one task, the next `visual_judge` invocation against that task returns `ADVISORY` (not `FAIL`); telemetry records `details.retry_budget_exhausted = true`. |
| SC4 | The `visual_fix` task's `visual_judge` invocation walks every collection / product / page / cart / search route the task -> routes map declares (whole-app sweep). |
| SC5 | `--judges visual_judge,quality_judge` limits the registered LLM-judge tuple to those two; `--judges none` disables all LLM judges. Rule verifiers run unchanged in both cases. |
| SC6 | `final_eval`'s expanded sweep walks every page enumerated by `data/{collections,products,pages}.json` (capped per §5.6) and writes `visual_eval/screenshots/` + `visual_eval/report.md`; `final_eval.json` carries the `visual` subtree. The verdict is advisory. |
| SC7 | Empty-skill callers see a **single startup warning** logged from `default_verifiers_factory` (or the `final_eval/visual_sweep.py` driver); `visual_judge` is **omitted** from the verifier tuple, no per-task `visual_judge.json` is written, the loop continues with the remaining verifiers. `final_eval`'s visual sweep emits the same warning, skips the sweep, and writes `visual.error = "playwright skill not available"` to `final_eval.json`. `<out_dir>/visual_eval/` is not created. |
| SC8 | A `gen_homepage` iteration's `visual_judge` invocation resolves to the `homepage` bucket via `buckets_for_task("gen_homepage")` (§5.3 layer 1), renders only that bucket's routes (just `/`), and judges against `BUCKET_CAPABILITY_KEYS["homepage"]`. Capabilities outside the slice are not surfaced in the prompt; routes outside the slice are not loaded. Same property holds for every other per-task invocation. `gen_homepage_redo_3` resolves to the same bucket via the `_redo_<n>` strip. |

---

## 5. Proposal

### 5.1 Architecture (delta vs. shop_gen.md §5.5.3)

```
                       ┌──────────────────────────────────┐
   exec iter (task T)  │  agent subprocess (parent)       │
                       │   • edits hydrogen/              │
                       │   • marks T as [x]               │
                       └──────────────┬───────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            │       harness verifier dispatch (existing)         │
            │                                                    │
            │  rule: tsc · build · routes_200 · data_in_use ·    │
            │        nav_coverage · navigation_primitive_usage   │
            │                                                    │
            │  LLM:  quality_judge (source)                      │
            │        cross_task_consistency (source, on cons.)   │
            │        visual_judge   (NEW; rendered) ─────────┐   │
            └────────────────────────────────────────────────┼───┘
                                                             │
              ┌──────────────────────────────────────────────┴──────┐
              │  visual_judge.run(ctx)                              │
              │   1. resolve task scope (routes + cap slice)        │
              │   2. count prior FAILs (retry-budget check)         │
              │   3. boot dev server (shared factory, per-call)     │
              │   4. write prompt.md into sub-workspace             │
              │   5. ctx.runtime.run_iteration(...)   ◄──── NESTED  │
              │        agent uses playwright skill, screenshots,    │
              │        writes verdict.json                          │
              │   6. parse verdict.json → VerifierResult            │
              │   7. tear down dev server                           │
              └─────────────────────────────────────────────────────┘
```

### 5.2 The `visual_judge` verifier

Lives at `packages/shop_arena/src/shop_arena/gen/build/verifiers/visual_judge.py`.

**Scope is task-bounded.** Each invocation renders **only** the
routes the executor's `selected_task_id` is responsible for, judged
against the **capability slice** for that task (§5.3). A
`gen_homepage` iteration loads `/` and judges homepage-only
capabilities; it never opens `/products/...`. Whole-site coverage
is opt-in, only at `visual_fix` (§5.2.1 step 5 fan-out). The
property the harness gives us — `VerifierContext.selected_task_id`
matches the task the executor just edited — is what makes this
work without per-iteration configuration: the same verifier is
"narrow" or "broad" depending on which task triggered it. Callers
that want to restrict the verifier further (e.g. "only run
`visual_judge` on `gen_homepage` iterations") pass the
`applicable_tasks` constructor arg; that gates `applies_to(task_id)`
without changing the per-task scope.

```python
class VisualJudgeVerifier:
    name = "visual_judge"

    def __init__(
        self,
        *,
        data_dir: Path,                              # data/*.json source for bucket → routes (§5.3 layer 2)
        dev_server_factory: DevServerFactory,
        retry_budget: int = 3,
        timeout_s: float = 300.0,
        applicable_tasks: Iterable[str] | None = None,
    ) -> None: ...

    def applies_to(self, task_id: str) -> bool: ...
    def run(self, ctx: VerifierContext) -> VerifierResult: ...
```

Default applicability (mirrors `quality_judge` plus the
visual-only `gen_*` tasks the source judge can't see well):

```
gen_homepage, gen_navigation, gen_collections, gen_product,
gen_cart_search, gen_info_pages, visual_fix
```

#### 5.2.1 Run lifecycle

1. **Resolve task scope.** Strip the optional `_redo_<n>` suffix
   from `ctx.selected_task_id` (B1 prefix match — §5.3 layer 1)
   and look up the page-bucket set:
   `buckets = buckets_for_task(ctx.selected_task_id)`. From that
   single set the verifier derives both axes:
   - **Routes**:
     `routes = routes_for_buckets(buckets, data_dir)` — sorted
     union over `bucket_routes(b, data_dir)`, resolved at run-time
     from `data/*.json` so handles are real (§5.3 layer 2).
   - **Capabilities**:
     `cap_keys = union(BUCKET_CAPABILITY_KEYS[b] for b in buckets)`,
     used to filter `capabilities.json` into the prompt's
     `{capabilities_slice}` block (§5.3.1).
   For `visual_fix`, `buckets` is the full set. Empty bucket set
   (unknown task id) ⇒ `Verdict.ERROR` with explanatory feedback
   (advisory; no block).

2. **Count prior FAILs (retry-budget check).** Walk
   `runs/build/iters/exec-*/checks/verifiers/visual_judge.json` siblings,
   count entries with `task_id == ctx.selected_task_id` and
   `verdict == "fail"`. If the count is `>= retry_budget`, **return
   `ADVISORY`** with feedback that names the budget; do **not** boot a
   dev server, do **not** invoke the runtime. Persist
   `details.retry_budget_exhausted = true`. (§5.4 explains the choice.)

3. **Boot dev server** via the injected `DevServerFactory` (same
   protocol `Routes200Verifier` and `final_eval` use). One server per
   call, torn down on exit. No reuse across verifier invocations in
   v0.1.

4. **Stage the sub-workspace.** Under
   `iter_dir/checks/verifiers/visual_judge/work/`:
   - `prompt.md` — the rendered prompt body (verbatim copy of what
     the runtime receives).
   - `routes.json` — the route list, base URL, and capability slices
     the agent must judge against.
   - `iter/` — empty; the runtime owns it.

5. **Nested agent iteration(s).** For per-task invocations
   (`gen_homepage`, `gen_product`, …) the verifier issues **one**
   `ctx.runtime.run_iteration(run_dir=work, iter_dir=work/iter,
   prompt=prompt_body, timeout=self._timeout_s)`. For the
   `visual_fix` task — where the route union spans every page
   bucket (§9.1) — the verifier **fans out** one nested call per
   page bucket (`homepage`, `navigation`, `collections`, `product`,
   `cart_search`, `info_pages`) under a `ThreadPoolExecutor`
   (`max_workers = visual_judge_max_concurrency`, default 3). Each
   fan-out call gets its own sub-iter at `work/iter/<bucket>/` and
   writes a per-bucket `verdict.json`; merge happens in step 6. The
   runtime is the same instance the parent loop drives executor
   iterations with, so playwright skill availability is inherited.
   The verifier does **not** prepend the harness
   `<<<harness-control>>>` header — this is a one-shot, plan-less
   invocation.

6. **Parse + merge `verdict.json`.** Per-task invocations parse the
   single `work/verdict.json` directly. `visual_fix` parses each
   `work/iter/<bucket>/verdict.json`, applies the page-bucket
   weights in §9.5 to compute the merged `score`, averages each
   `category_scores` key across present buckets, concatenates
   `issues` sorted by severity, and writes the merged document to
   `work/verdict.json`. A single bucket FAILing is a FAIL of the
   merged verdict. Missing / malformed verdicts ⇒ `Verdict.FAIL`
   with explanatory feedback (counts toward the retry budget).

7. **Promote screenshots.** Hard-link or copy the runtime's
   `iter/screenshots/` into
   `iter_dir/checks/verifiers/visual_judge/screenshots/` so they're
   discoverable next to the verifier's telemetry. Keep the originals
   under `iter/` for replay parity.

8. **Return `VerifierResult`** with verdict, feedback, and
   `details = {routes, pages_judged, score, category_scores,
   buckets_run, retry_budget_exhausted: false, prior_fails}`. For
   per-task invocations `buckets_run` is a single-element list; for
   `visual_fix` it lists every fanned-out bucket.

#### 5.2.2 Why `run_iteration`, not `LLMCompleter`?

Both shapes are part of the runtime contract; `shop_arena.gen` already uses
`run_iteration` for executor iterations and `LLMCompleter.complete`
for one-shot text judges (existing `quality_judge` /
`cross_task_consistency`). Visual judging needs the former because:

- `LLMCompleter.complete(prompt: str) -> str` is text-only — it
  cannot pass screenshot bytes to the model.
- The agent needs the **playwright skill** to drive the browser, the
  filesystem tool to write screenshots, and (optionally) the ability
  to interact (open the mega-menu, scroll, hover) before judging.
  All three are tool-using behaviours that only `run_iteration`
  exposes.

The `pi` runtime already ships those tools and a multimodal LLM;
`run_iteration` is the existing path for using them. See §6 for
the rejected alternatives (direct `pw.js` subprocess, multimodal
`LLMCompleter` extension).

### 5.3 Task -> buckets -> (routes, capabilities)

Scope is resolved through a **two-layer** model: the task id maps
to a small, naming-stable set of page **buckets**; each bucket
resolves to a route slice (from `data/*.json`) and a capability
slice (static). The bucket axis is shared with the page-bucket
fan-out (§5.2.1 step 5), `BUCKET_CAPABILITY_KEYS` (§5.3.1), and
`PAGE_WEIGHTS` (§9.5) — one taxonomy, three uses.

#### Layer 1: task -> buckets (B1 prefix match)

```python
TASK_BUCKETS: dict[str, frozenset[str]] = {
    "gen_homepage":    frozenset({"homepage"}),
    "gen_navigation":  frozenset({"navigation"}),
    "gen_collections": frozenset({"collections"}),
    "gen_product":     frozenset({"product"}),
    "gen_cart_search": frozenset({"cart_search"}),
    "gen_info_pages":  frozenset({"info_pages"}),
    "visual_fix":      frozenset({"homepage", "navigation", "collections",
                                  "product", "cart_search", "info_pages"}),
}


def buckets_for_task(task_id: str) -> frozenset[str]:
    base = re.sub(r"_redo_\d+$", "", task_id)
    return TASK_BUCKETS.get(base, frozenset())
```

The verifier strips a trailing `_redo_<n>` before lookup, so
`gen_homepage_redo_3` resolves to the same buckets as
`gen_homepage`. Unknown task ids ⇒ empty bucket set ⇒
`Verdict.ERROR` from §5.2.1 step 1. The map is small (~8 keys)
and has no per-shop content, so it ships as a constant in
`build/verifiers/_task_routes.py`; tests monkey-patch the module
to override.

#### Layer 2: bucket → routes (data-driven)

Sourced from `data/{collections,products,pages}.json` at run-time
so the resolved routes always carry real handles:

```python
def bucket_routes(bucket: str, data_dir: Path) -> tuple[str, ...]:
    match bucket:
        case "homepage":     return ("/",)
        case "navigation":   return ("/", "/collections")
        case "collections":
            handles = read_handles(data_dir / "collections.json")[:1]
            return ("/collections", *(f"/collections/{h}" for h in handles))
        case "product":
            handles = read_first_product_per_collection(data_dir)[:1]
            return tuple(f"/products/{h}" for h in handles)
        case "cart_search":
            return ("/cart", f"/search?q={sample_search_token(data_dir)}")
        case "info_pages":
            handles = read_handles(data_dir / "pages.json")[:1]
            return (*(f"/pages/{h}" for h in handles), "/policies/privacy")
```

For multi-bucket invocations (`visual_fix`), the
verifier takes the **sorted union** of every bucket's routes. The
union is **deterministic** (sorted by route) and **capped**
(§5.6.1). The `visual_fix` per-iteration union and the final-eval
visual sweep share the same bucket axis but apply different caps:
the per-iteration `visual_fix` is tight (1 collection, 1 product)
while the sweep widens to §5.6.1's defaults (8 collections, etc.).

#### 5.3.1 Capability slicing

The same bucket axis keys the capability slice. Without slicing
the homepage judge would see "missing collection filters!" in
`capabilities.json` and spuriously FAIL — filters live on
`/collections/<handle>`, not on `/`.

```python
BUCKET_CAPABILITY_KEYS: dict[str, frozenset[str]] = {
    "homepage":    frozenset({"home.*", "navigation.header", "footer"}),
    "navigation":  frozenset({"navigation.*", "footer"}),
    "collections": frozenset({"collection.*"}),
    "product":     frozenset({"product.*"}),
    "cart_search": frozenset({"cart.*", "search.*"}),
    "info_pages":  frozenset({"page.*", "policies.*"}),
}
```

The verifier takes the **union** over `buckets` from Layer 1, then
filters `capabilities.json`:
`{k: v for k, v in capabilities.items() if any(fnmatch(k, p) for p in keys)}`
(shell-glob via `fnmatch`). Keys absent from the slice are
**never** surfaced in the prompt — the agent does not see them,
so it cannot penalise their absence.

### 5.4 Per-task retry budget (caller-side)

The user constraint: cap the exec → verify → exec retry loop at 3
attempts per task. The harness has no per-task retry counter (verifier
spec §7.2 says `max_iters` is the only budget); rather than amend
the harness for a single verifier, `visual_judge` enforces the cap
itself by reading **its own past verdicts** from sibling iter dirs.

Algorithm:

1. Glob `<run_dir>/iters/exec-*/checks/verifiers/visual_judge.json`
   excluding the current iter.
2. Filter for `verdict == "fail"` and `task_id == selected_task_id`.
3. Count.
4. If `count >= retry_budget`, return `ADVISORY` immediately (no dev
   server, no nested agent, no LLM call). Feedback explains the
   budget and points the human to the prior failures.

This makes the budget **strict per task**: if the agent oscillates
between tasks (`visual_fix` flips back to `gen_homepage` via the redo
flow, spec §5.7.3), each task accumulates its own count from the
shared `iters/` history. New redo task ids (`gen_homepage_redo_1`)
restart the count by construction (different `task_id`), which matches
user intent: a redo gets a fresh budget.

The cap is **soft**: ADVISORY surfaces feedback to the next iteration
without blocking. The executor can still self-correct on subsequent
turns; the loop simply stops retrying the visual judge against this
task. `quality_judge` / `cross_task_consistency` continue to gate
normally — they have no analogous budget.

`visual_retry_budget = 0` disables the budget entirely (every call
runs); `1` is "no retries". `--visual-retry-budget` exposes it on the
CLI; library callers set it on `ShopGenConfig`.

### 5.5 Configurable LLM-judge set

`ShopGenConfig.judges: set[str]` selects which LLM judges run. The
default factory (`build/loop.py::default_verifiers_factory`) reads
this set and only constructs the matching verifiers:

```python
def default_verifiers_factory(*, out_dir, sidecar, judges) -> tuple[Verifier, ...]:
    rule_verifiers = (
        TscVerifier(),
        BuildVerifier(),
        Routes200Verifier(...),
        DataInUseVerifier(...),
        NavCoverageVerifier(...),
        NavigationPrimitiveUsageVerifier(),
    )
    judge_verifiers: list[Verifier] = []
    if "visual_judge" in judges:
        if is_playwright_skill_available():           # §5.5.1 self-check
            judge_verifiers.append(VisualJudgeVerifier(...))
        else:
            logger.warning(
                "visual_judge requested but pi-playwright skill is "
                "not available on this machine; the verifier will be "
                "disabled. Install via `pnpm add -g pi-playwright` to "
                "enable. See visual_verifier.md §5.5.1.",
            )
    if "quality_judge" in judges:
        judge_verifiers.append(QualityJudgeVerifier())
    if "cross_task_consistency" in judges:
        judge_verifiers.append(CrossTaskConsistencyVerifier())
    return (*rule_verifiers, *judge_verifiers)
```

Defaults: `{"visual_judge", "quality_judge", "cross_task_consistency"}`
— the full set. CLI:

```bash
--judges visual_judge,quality_judge       # subset
--judges none                             # empty set (no LLM judges)
--judges all                              # explicit full set (= default)
```

Unknown judge names are a hard error from `cli.py`. Rule verifiers
are not selectable in v0.1 (every one is required for a valid build).

#### 5.5.1 Skill availability self-check

The factory runs a **one-time probe** for the `pi-playwright`
skill before constructing `VisualJudgeVerifier`, mirroring the
resolver already battle-tested in `shop_arena.explore.pipeline._resolve_playwright_skill_dir`
(tries `pnpm root -g`, then `npm root -g`; checks `SKILL.md` +
`scripts/pw.js` exist). Production wiring lifts that helper into a
shared module:

```python
# build/verifiers/_skills.py
def is_playwright_skill_available() -> bool:
    """True iff the pi-playwright skill is resolvable on this machine."""
    skill_dir = _resolve_playwright_skill_dir()
    if skill_dir is None:
        return False
    return (skill_dir / "scripts" / "pw.js").is_file()
```

When the probe returns `False`:

1. **One** `WARNING` is logged from the factory naming the missing
   skill and the install hint (`pnpm add -g pi-playwright`).
2. `VisualJudgeVerifier` is **omitted from the verifier tuple** —
   it is never constructed, never dispatched, never written to
   telemetry. The harness has no visibility into the verifier;
   `run.json`'s `verifier_runs` array does not include it.
3. The rest of the verifier tuple (rule verifiers + remaining
   judges) is returned unchanged. The loop runs to completion
   without `visual_judge` gating any task.
4. `final_eval/visual_sweep.py` runs the same probe at the start
   of its driver. On failure: same warning, sweep is skipped,
   `final_eval.json` carries `visual.error = "playwright skill
   not available"`, and `<out_dir>/visual_eval/` is **not**
   created (no empty dirs, no half-written `report.md`).

Why factory-side, not per-iteration: the alternative — the
verifier runs and returns `Verdict.ERROR` on every task because
the skill is missing — generated one ERROR per `gen_*` task,
i.e. N redundant warnings per run, and the harness logged each
one as a verifier problem. The probe is platform-level (the JS
package manager's global root is the same for every iteration),
so one check at startup is strictly more informative than N
checks at runtime.

The probe does **not** depend on the runtime instance — `pi`,
`claude_code`, and `replay` runtimes share the same skill
directory. Replay-runtime tests therefore behave the same as
production: if the test machine has the skill installed, the
verifier runs (the stub `AgentRuntime` fabricates a `verdict.json`
per §7 Q5); if not, the verifier is omitted. CI runners that
deliberately exclude the skill exercise the omit-and-warn path.

Forcing the verifier on without a working skill is **not
supported** in v0.1: the verifier literally cannot work without
playwright. If a caller wants to bypass the factory probe (e.g.
running against a custom skill location), they can construct
`VisualJudgeVerifier` directly and pass it via
`PlanExecLoopConfig.verifiers`; the verifier itself does not
re-run the probe in `__init__`.

### 5.6 Expanded `final_eval` (visual sweep)

The current 5-step smoke flow is **replaced** by an all-pages visual
sweep. The flow is:

1. Resolve the page set:
   - `/`
   - `/collections` and `/collections/<handle>` for every collection
     in `data/collections.json` (capped at 8 collections in v0.1; see
     §5.6.1).
   - 1 product per collection, by handle (capped at 1×8 = 8 PDPs).
   - Every entry in `data/pages.json` (capped at 6).
   - `/cart`, `/search?q=<sample_token>`.
2. Boot dev server via the same `DevServerFactory`.
3. Stage a sub-workspace under
   `<out_dir>/visual_eval/work/` with the resolved page set.
4. **Fan out `runtime.run_iteration(...)` per page bucket** with
   the visual-sweep prompt (§9.4) — same fan-out path as
   `visual_judge`'s `visual_fix` (§5.2.1 step 5). One sub-iter per
   bucket under a `ThreadPoolExecutor`
   (`max_workers = final_eval_visual_max_concurrency`); per-call
   timeout is `final_eval_visual_timeout_s = 1200` s by default, so
   wall-clock scales with the longest bucket, not the sum.
5. Parse the agent's `verdict.json`, promote screenshots into
   `<out_dir>/visual_eval/screenshots/<page>/`, write
   `<out_dir>/visual_eval/report.md`.
6. Merge the result into `final_eval.json` under the `visual` subtree
   (§4.1).

Every recoverable failure (missing dev server, missing playwright
skill, parse error) is captured in `visual.error` rather than
raised — `final_eval` stays advisory per shop_gen.md §5.5.5. The
skill check is the **same one-time probe** as the build-loop
factory's (§5.5.1); on failure the sweep is skipped, the warning
is logged once, `visual.error = "playwright skill not available"`
is written, and `<out_dir>/visual_eval/` is **not** created (no
empty dirs, no half-written `report.md`).

#### 5.6.1 Why caps?

The full catalog at v0.1 default scale is 200 products / 10
collections. Rendering and judging all of them at every viewport is
~2000 screenshots; the LLM context can't hold that prompt. v0.1
caps:

- `final_eval_max_collections = 8`
- `final_eval_products_per_collection = 1`
- `final_eval_max_pages = 6`
- `final_eval_viewports = (desktop, mobile)` — unchanged

Yields ≤ 24 page renders × 2 viewports = 48 screenshots, well within
the agent's iteration budget. The caps are configurable on
`ShopGenConfig`. Sampling is deterministic (first N by handle, sorted)
so reruns reuse the same evidence set.

### 5.7 Telemetry & artifacts

Per-iteration (existing checks dir, additive):

```
runs/build/iters/<exec_id>/checks/verifiers/
├── visual_judge.json                         # standard schema
└── visual_judge/
    ├── work/
    │   ├── prompt.md
    │   ├── routes.json
    │   ├── verdict.json
    │   └── iter/                             # native.log, screenshots/, …
    └── screenshots/                          # promoted copies (POSIX names)
        ├── <route_slug>__desktop.png
        └── <route_slug>__mobile.png
```

Final eval (new top-level dir):

```
<out_dir>/
├── final_eval.json                           # adds `visual` subtree
└── visual_eval/
    ├── work/                                 # sub-workspace (debugging)
    ├── screenshots/                          # human-reviewable
    └── report.md                             # markdown summary
```

The `<out_dir>/visual_eval/` directory is **published**; the
per-iteration `runs/build/iters/.../visual_judge/` artifacts are
debugging.

### 5.8 Module layout

```
packages/shop_arena/src/shop_arena/gen/
├── build/
│   └── verifiers/
│       ├── visual_judge.py                   # NEW — VisualJudgeVerifier
│       ├── _runtime_call.py                  # NEW — small helper: stage sub-workspace, run_iteration, parse verdict.json
│       └── _task_routes.py                  # NEW — TASK_BUCKETS + BUCKET_CAPABILITY_KEYS + bucket_routes() shared by visual_judge and routes_200 (§5.3, §9.1)
├── final_eval/
│   ├── visual_sweep.py                       # NEW — all-pages sweep driver (replaces playwright_smoke for the rendered-judging path)
│   └── prompts/
│       └── visual_sweep.md                   # NEW — final-eval visual sweep prompt
└── build/
    └── prompts/
        └── visual_judge.md                   # NEW — per-iteration visual judge prompt
```

`final_eval/playwright_smoke.py` stays in v0.1 as the smoke driver;
the LLM judge in `final_eval/step.py` now consumes the visual sweep's
output rather than the smoke screenshots' metadata table. The 5-step
smoke flow is preserved for backward-compat telemetry (`smoke`
subtree in `final_eval.json`).

### 5.9 CLI surface (delta on shop_gen.md §5.8)

```bash
shop-gen ... --judges <comma-list|all|none>          # default: all
shop-gen ... --visual-retry-budget <int>             # default: 3
shop-gen ... --visual-judge-timeout <seconds>        # default: 300
shop-gen ... --final-eval-visual-timeout <seconds>   # default: 1200
shop-gen ... --visual-judge-pass-threshold <float>   # default: 7.0 (§9.3 score → verdict coercion)
shop-gen ... --visual-judge-max-concurrency <int>    # default: 3   (in-loop visual_fix fan-out)
shop-gen ... --final-eval-visual-max-concurrency <int> # default: 2 (final visual sweep fan-out)
```

No new shape — these are additive flags; every other flag from
shop_gen.md §5.8 is unchanged.

---

## 6. Alternative

1. **Direct `pw.js` subprocess inside `visual_judge`.** Bypass the
   agent runtime; the verifier itself shells out to the playwright CLI
   on a fixed flow (open URL, screenshot at 2 viewports, exit), then
   asks an `LLMCompleter` (multimodal extension) to judge. Faster, no
   nested agent. **Rejected**: (a) requires a multimodal completion
   API the harness doesn't ship, (b) the agent can adapt the
   exploration (open mega-menu before snapping, scroll-to-bottom for
   long pages) which a fixed flow can't, (c) duplicates skill ownership
   — we'd have one playwright stack in `shop_arena.explore` (skill-driven)
   and another in `visual_judge` (CLI-driven).

2. **Multimodal `LLMCompleter` extension on the harness.** Generalize
   the existing `LLMCompleter.complete(prompt)` to take attachments
   (image bytes / paths). Cleaner long-term: every verifier that wants
   visual signal could use it. **Deferred**: scope creep for v0.1; it
   needs a harness API change, runtime adapter changes, and replay
   cassette format changes. Revisit at harness 0.4.

3. **Harness-side per-task retry budget.** Add
   `verifier_retry_budget: dict[str, int]` to `PlanExecLoopConfig`;
   the harness counts FAILs per `(task_id, verifier_name)` and
   downgrades the verdict on overflow. **Deferred**: amends an
   already-shipped harness API for one verifier's needs. The
   caller-side approach (§5.4) is local, transparent, and can be
   migrated to the harness in v0.2 without an API break.

4. **Replace `quality_judge` outright with `visual_judge`.** Source-
   level review still catches things rendering misses (orphaned
   imports, dead types, logic bugs that fall back to default UI).
   Keeping both in v0.1 lets us measure the overlap before deciding.
   See §7 Q1.

5. **Separate `visual_final_eval` step.** Add a Phase 6 step instead
   of amending Phase 5. **Rejected**: `final_eval` already owns the
   "post-loop advisory verdict" role; adding a sibling step splits
   the verdict file and the published artifact dir. Amending is
   surgically smaller.

6. **Skip task scoping; always render every page on every
   iteration.** Slow (≥ 30s per iteration extra) and noisy (every
   FAIL touches the whole catalog's prompt). **Rejected.**

---

## 7. Open Questions

1. **Should `quality_judge` survive past v0.2?** v0.1 keeps both
   judges per the user's instruction. If `visual_judge` consistently
   catches everything `quality_judge` catches (and faster, given fewer
   tokens), the source judge becomes redundant. Concrete signal:
   1 month of run telemetry where `quality_judge` PASS ∧
   `visual_judge` FAIL is empirically zero.

2. **`visual_judge` against `visual_fix` overlaps with the existing
   final visual sweep.** Both walk the union of all routes. v0.1
   accepts the duplication: the `visual_fix` verifier gates `[x]`,
   `final_eval` stays advisory, and the agent's prompt is the same
   shape. v0.2 may collapse them into one whole-app sweep.

3. **Sub-workspace immutability vs. seed-immutability**
   ([harness/seed_immutability.md](../harness/seed_immutability.md)).
   The verifier writes under
   `runs/build/iters/<id>/checks/verifiers/visual_judge/work/`, which
   is **inside** the harness's seed-protected `iters/` tree. This
   tree is owned by the harness for telemetry; verifier dispatch
   already writes here (`<name>.json`, `feedback.md`). Confirmed
   compatible: writes happen during dispatch, before the next
   iteration's seed-immutability check, and don't touch the seeded
   `artifact/` subtree.

4. **Model selection for visual judging.** v0.1 uses whatever
   `--model` the parent run picked. If that model is text-only, the
   nested `run_iteration` will simply fail to read the screenshots
   and report a verdict; the verifier returns FAIL or ERROR with a
   diagnostic. v0.2 may add `--visual-judge-model` to override.

5. **Replay-runtime parity.** The replay runtime
   ([harness/runtimes/replay.py](../../../packages/harness/src/harness/runtimes/replay.py))
   has no playwright skill and no multimodal LLM. CI tests of
   `visual_judge` use a stub `AgentRuntime` that fabricates a
   deterministic `verdict.json` instead of replaying real iterations.
   This mirrors the pattern `final_eval`'s `BrowserDriver` already
   uses. Confirmed acceptable; replay cassettes for the parent loop
   stay green.

6. **Reference-screenshot grounding for the visual judge.** Today's
   visual judge grounds against `capabilities.json` only — by
   design, since `shop_arena.explore` strips source-store URLs to preserve
   the anonymization invariant (no `store_url` / `source_url` field
   survives synthesis). A useful future signal would attach the
   anonymized prefetched screenshots from
   `shop_arena/explore/prefetch/runner.py` to the nested agent's prompt
   ("does the generated storefront feel faithful to the seed
   brand?"). Two prerequisites block this in v0.1: (a) a multimodal
   completer extension on the harness contract (§6 alt #2), and (b)
   an anonymization audit confirming the prefetched screenshots
   carry no leaked logos or brand text. v0.2 candidate. The
   first-pass implementation referenced in §9.6 took the simpler
   route of opening the live source URL — we explicitly reject that
   here.

---

## 8. Milestones (informative)

- **M1 — `visual_judge` verifier (no retry budget, no fan-out).** Done.
  New module `build/verifiers/visual_judge.py`. Stage sub-workspace,
  call `ctx.runtime.run_iteration`, parse `verdict.json` (schema
  §9.3), promote screenshots. Default applicability matches §5.2.
  Per-task invocations only — `visual_fix` page-bucket fan-out
  (§5.2.1 step 5) lands in M5. Unit tests with a stub `AgentRuntime`.
- **M2 — Per-task retry budget.** Done. Sibling-iter scan; ADVISORY
  downgrade on overflow. SC3 covered.
- **M3 — Configurable judge set.** Done. `ShopGenConfig.judges`,
  `default_verifiers_factory(judges=...)`, CLI `--judges`. SC5
  covered.
- **M4 — Task -> buckets -> routes/capabilities refactor.** Done. Land
  the 2-layer model in `build/verifiers/_task_routes.py`:
  `TASK_BUCKETS` constant + `buckets_for_task` (B1 prefix match,
  strips `_redo_<n>`); `bucket_routes(b, data_dir)` and
  `BUCKET_CAPABILITY_KEYS` for the data-driven and static slices.
  Lift the existing inline `_default_task_routes` out of
  `build/loop.py`; `Routes200Verifier` and `VisualJudgeVerifier`
  consume the shared module.
- **M5 — Expanded `final_eval` (visual sweep) + page-bucket
  fan-out.** Done. New `final_eval/visual_sweep.py`. Lands the page-bucket
  `ThreadPoolExecutor` fan-out for both `visual_fix` (in
  `visual_judge`) and the sweep, per §5.2.1 step 5 + §5.6.
  Injection seams keep CI deterministic. SC6 covered.
- **M6 — Production playwright wiring.** Done. Real `DevServerFactory`
  (`pnpm dev`) + real agent-runtime path. Replaces
  `_unconfigured_dev_server_factory` in both `Routes200Verifier` and
  the visual sweep. (This was already deferred from `shop_arena.gen` M5/M6;
  this milestone closes it.)
- **M7 — v0.1 release docs.** This spec and
  `docs/specs/README.md` now reflect the shipped code. Package version
  bumps are tracked outside this spec.

---

## 9. Appendix

### 9.1 Reference task -> buckets -> routes (resolved)

Production wiring lives in `build/verifiers/_task_routes.py`. The
`task -> buckets` map is a static constant (B1 prefix match strips
`_redo_<n>`); `bucket → routes` is computed from `data/*.json` at
verifier construction time so resolved routes always carry real
handles. `bucket → capability_keys` is static.

```python
import re
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


TASK_BUCKETS: dict[str, frozenset[str]] = {
    "gen_homepage":    frozenset({"homepage"}),
    "gen_navigation":  frozenset({"navigation"}),
    "gen_collections": frozenset({"collections"}),
    "gen_product":     frozenset({"product"}),
    "gen_cart_search": frozenset({"cart_search"}),
    "gen_info_pages":  frozenset({"info_pages"}),
    "visual_fix":      frozenset({"homepage", "navigation", "collections",
                                  "product", "cart_search", "info_pages"}),
}

BUCKET_CAPABILITY_KEYS: dict[str, frozenset[str]] = {
    "homepage":    frozenset({"home.*", "navigation.header", "footer"}),
    "navigation":  frozenset({"navigation.*", "footer"}),
    "collections": frozenset({"collection.*"}),
    "product":     frozenset({"product.*"}),
    "cart_search": frozenset({"cart.*", "search.*"}),
    "info_pages":  frozenset({"page.*", "policies.*"}),
}


def buckets_for_task(task_id: str) -> frozenset[str]:
    """Strip a trailing `_redo_<n>` and look up the bucket set."""
    base = re.sub(r"_redo_\d+$", "", task_id)
    return TASK_BUCKETS.get(base, frozenset())


def routes_for_buckets(
    buckets: Iterable[str],
    data_dir: Path,
    *,
    caps: BucketCaps | None = None,
) -> tuple[str, ...]:
    """Sorted union of `bucket_routes(b, data_dir, caps)` over buckets."""
    routes: set[str] = set()
    for b in buckets:
        routes.update(bucket_routes(b, data_dir, caps=caps))
    return tuple(sorted(routes))


def capabilities_for_buckets(
    buckets: Iterable[str],
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    """Filter capabilities.json by the union of bucket cap keys."""
    keys = frozenset().union(*(BUCKET_CAPABILITY_KEYS[b] for b in buckets))
    return {
        k: v
        for k, v in capabilities.items()
        if any(fnmatch(k, p) for p in keys)
    }
```

For multi-bucket invocations (`visual_fix`) the
route union is sorted (deterministic) and capped via the optional
`caps` argument. The build-loop verifier uses tight per-iteration
caps; final-eval's visual sweep passes wider caps from §5.6.1.

### 9.2 `visual_judge` prompt skeleton (informative)

`build/prompts/visual_judge.md`:

```markdown
You are a visual quality verifier for a hydrogen storefront.

The dev server is running at {base_url}. Use the **playwright skill**
to render every URL listed below at desktop (1280×800) and mobile
(375×667). Save each screenshot under `./screenshots/<slug>__<viewport>.png`.

After capturing screenshots, judge whether the rendered pages
surface the capabilities listed in the JSON below for the task
`{task_id}`. **Judge only what you have rendered.** The
capabilities slice has been pre-filtered for this task — do not
infer about pages you have not opened, and do not penalise the
absence of features that belong to a different bucket (e.g. cart
or product features when judging `gen_homepage`).

Capabilities slice for this task:
```json
{capabilities_slice}
```

Routes to render:
{route_list}

When you are done, write `./verdict.json` with the schema below.
Do not modify any other file. Do not call out to external APIs.

Verdict schema (§9.3):
```json
{verdict_schema}
```

Prior verifier feedback for this task (if any):
{prior_feedback_or_empty}
```

### 9.3 `verdict.json` schema (informative)

```jsonc
{
  "verdict": "pass" | "fail",                  // required; lowercase. PASS iff `score ≥ visual_judge_pass_threshold` AND no `severity: "critical"` issue.
  "score": 7.8,                                // required; 0–10 float. Overall page-bucket quality.
  "category_scores": {                         // optional; same 0–10 scale. Missing keys treated as "not assessed".
    "structure": 8,                            // page hierarchy + section ordering
    "components": 7,                           // component types present (cards, grids, hero, …)
    "visual_tone": 8                           // colour, typography, spacing, density
  },
  "feedback": "markdown body",                 // required on fail; "" allowed on pass
  "pages_judged": 4,                           // required; integer count of distinct (route, viewport) pairs the agent rendered + judged.
  "issues": [                                  // optional; one entry per blocking issue
    {
      "route": "/collections/outerwear",
      "viewport": "mobile",
      "screenshot": "screenshots/collections-outerwear__mobile.png",
      "severity": "critical" | "major" | "minor",  // "critical" forces verdict=fail regardless of score
      "summary": "filter bar overflows the viewport",
      "capability": "collection.filters"
    }
  ]
}
```

Parser is forgiving: a fenced ```json``` block or a bare top-level
object both work (mirrors
`shop_arena.gen.build.verifiers._judge.dispatch_judge`).

**Score → verdict mapping.** The agent emits both a `verdict` token
and a `score`; the verifier accepts the agent's binary verdict but
also enforces two invariants on top of it: (a) any
`severity: "critical"` issue forces `verdict=fail` regardless of
the agent's emitted token; and (b) `score < visual_judge_pass_threshold`
(default 7.0) coerces an emitted `pass` to `fail`. The score never
*upgrades* a `fail` to `pass` — it only tightens the gate. Category
scores are surfaced in `details` and `feedback.md` but do not gate.

### 9.4 Final-eval visual-sweep prompt skeleton (informative)

Same shape as §9.2 with three differences:

- Routes list is the all-pages `visual_fix` set (§5.6.1).
- Verdict feedback is **advisory** language ("flag any visual issues
  for human review"), not blocking.
- Sub-workspace is `<out_dir>/visual_eval/work/`, not under `iters/`.

### 9.5 Page-bucket weights (`visual_fix` fan-out)

Used by `VisualJudgeVerifier` to merge per-bucket `verdict.json`
documents into a `visual_fix` verdict, and by
`final_eval/visual_sweep.py` to compute the overall sweep score.

```python
PAGE_WEIGHTS: dict[str, float] = {
    "homepage":      0.25,
    "navigation":    0.20,
    "collections":   0.20,
    "product":       0.20,
    "cart_search":   0.08,
    "info_pages":    0.07,
}
```

Sourced from the first-pass implementation referenced in §9.6 and
tuned by hand — expect this table to evolve with telemetry. Buckets
absent from a fan-out (e.g. a shop with no info pages) are dropped
from both numerator and denominator so the weighted average stays
well-defined.

### 9.6 Reference materials

- [`shop_arena/shop_gen.md`](shop_gen.md) §5.5 — phase 4 build harness
  loop.
- [`shop_arena/shop_gen.md`](shop_gen.md) §5.5.5 — final eval contract.
- [`harness/verifiers.md`](../harness/verifiers.md) — the dispatch
  protocol this verifier plugs into. `VerifierContext.runtime` is
  documented as `AgentRuntime` (§5.2); this spec is the first verifier
  to use the full `run_iteration` path (existing LLM verifiers narrow
  to `LLMCompleter.complete`).
- [`harness/runtimes/base.py`](../../../packages/harness/src/harness/runtimes/base.py)
  — `AgentRuntime.run_iteration` contract.
- [`shop_arena/shop_explore.md`](shop_explore.md) §5.2 — playwright
  skill availability on the `pi` runtime.
