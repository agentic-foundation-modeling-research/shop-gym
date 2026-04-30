# ShopProbe v2 / capture-judge tier — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/shop_arena/shop_probe.md`](../specs/shop_arena/shop_probe.md) (§5.3.3 + Appendix 8.4–8.5)
Target module: `packages/shop_arena/src/shop_probe`

> Pure task list. Seven milestones land as seven git commits on
> `mz/dev-main`. No PRs in this batch.

---

## 1. Overview

Replace the broken v1.3 `agent_driven` advanced tier (8 probes that all
hit the 180 s harness timeout — see spec §Overview) with a
**capture-judge** tier: capture a fixed 5-page bundle once per shop
(home / collection / product / cart / search), then run one Anthropic
Messages-API call per rubric entry asking a structural-affordance
question against the bundle slice the entry references.

Make task-set extension a YAML-only edit: each `level: capture_judge`
rubric entry carries an inline `capture_judge:` block (`pages` ⊂
`PageRef`, `judge_prompt`). One generic dispatcher serves every entry —
no per-task wrapper coroutines, no agent runtime, no harness.

The retired v1.3 surface (`agent/runner.py`, `agent/config.py`, the four
`--agent-*` flags, `ProbeResult.agent_cost_usd`/`agent_model`,
`ProbeReport.total_agent_cost_usd`, `v1{,1,2,3}.yaml`) is deleted
outright. The v1.3 spec + impl docs are deleted in M6. v2 ships a single
rubric file and a single judge cost field.

## 2. Terminology

Uses the v2 spec's vocabulary verbatim. Key terms reintroduced for
convenience:

- **Page bundle** — fixed set of pages captured once per axis-A run,
  keyed by `PageRef = Literal["home", "collection", "product", "cart",
  "search"]`. Persists `screenshot.png` + `a11y.json` per page under
  `<evidence_root>/_bundle/<page>/`.
- **Page capture** — one row of the bundle: `(page_ref, url,
  screenshot_rel, accessibility_rel, applicable, notes)`.
- **Capture-judge probe** — rubric entry with `level: capture_judge`
  whose inline `capture_judge` block carries `pages` + `judge_prompt`.
- **Capture judge** — `agent/judge.py:run_capture_judge(captures,
  bundle_root, judge_prompt, *, model, client) -> JudgeVerdict`. One
  Messages-API call with N images + a11y JSON; reuses the existing
  `JudgeVerdict` shape.
- **Structural affordance** — UI capability detectable from a single
  page state without interaction (e.g. "the collection page exposes a
  sort dropdown with ≥2 options").

## 3. Current Status

`packages/shop_arena/src/shop_probe/`:
- `rubric/v1.yaml` (61), `v1.1.yaml` (66), `v1.2.yaml` (74 with
  deterministic advanced), `v1.3.yaml` (74 with broken `agent_driven`).
- `RubricLevel = Literal["core", "modern", "advanced", "agent_driven"]`.
- `RubricEntry.{probe, agent_task}` XOR validator + inline
  `AgentTaskInline` model.
- `agent/{runner.py, config.py, judge.py, env.py, __init__.py}` — runner +
  config are dead code post-v2; judge + env are kept and rewritten / reused.
- `cli.py` — five `--agent-*` flags (`runtime`, `model`, `step_budget`,
  `timeout_s`, `judge_model`); `_build_agent_config`; agent_driven
  dispatch via `runner.run_agent_entry`; `_aggregate_coverage` rolls
  `agent_driven` into `advanced`; `_aggregate_cost_totals` returns
  `(judge_total, agent_total)`.
- `probes/_runner.py` — `ProbeContext.agent_config`,
  `ProbeRunner.run_agent_entry`, `DEFAULT_AGENT_TIMEOUT_S=180`,
  `AGENT_BUFFER_S=30`.
- `report.py` — `ProbeResult.{judge_cost_usd, judge_model,
  agent_cost_usd, agent_model}`, `ProbeReport.{total_judge_cost_usd,
  total_agent_cost_usd}`.

Last cohort run on 2026-04-29 (`outputs/shop_probe/result_v1_3_2/`):
all 8 agent-driven probes × every shop hit the 180 s timeout. Per-target
wall time ~26 min; full cohort ~3 h. Spec §Overview pins the root cause
(`Skill("playwright-browser")` not installed in the spawned
`claude_code` runtime).

## 4. Desired Status

After M7: `--rubric v2` resolves a 74-entry rubric (66 v1.1 verbatim + 8
capture_judge). Each axis-A run captures the 5-page bundle once,
persists it under `<evidence_root>/_bundle/<page>/`, and dispatches each
capture-judge entry through one `run_capture_judge` call. Per-probe
`judge_cost_usd` recorded; `ProbeReport.total_judge_cost_usd` sums it
cohort-wide. v1.x rubrics + v1.3 spec/impl docs deleted; agent surface
deleted; the four `--agent-*` flags collapsed into one `--judge-model`.
Cohort wall time drops from ~3 h to **< 15 min** at default settings.

---

## 5. Proposal — Task list

### M1 · Schema + v2.yaml + rubric tests

**Goal:** schema swaps `agent_driven` → `capture_judge`; v2.yaml lands
hash-pinned; v1.x YAMLs + their tests are deleted in the same commit so
nothing references the old surface.

- [x] **T1.0** — Spec + impl docs already on disk
  (`docs/specs/shop_arena/shop_probe.md` §5.3.3 + Appendix 8.4–8.5,
  `docs/impl/web_probe_v2_capture_judge_implementation.md`).
  `docs/specs/README.md` already lists a single consolidated `shop_probe.md`
  row pointing at this impl plan; no further index churn needed.
  **Check:** spec + impl docs link to each other; README index renders.
- [ ] **T1.1** — `packages/shop_arena/src/shop_probe/rubric/schema.py`:
  - Replace `RubricLevel` literal: drop `"agent_driven"`, add
    `"capture_judge"`.
  - Add new literal `PageRef = Literal["home", "collection", "product",
    "cart", "search"]`.
  - Replace `AgentTaskInline` with `CaptureJudgeTask` (frozen,
    `extra="forbid"`):
    ```python
    class CaptureJudgeTask(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)
        judge_prompt: str = Field(min_length=1)
        pages: tuple[PageRef, ...] = Field(min_length=1, max_length=5)

        @model_validator(mode="after")
        def _check_unique_pages(self) -> "CaptureJudgeTask":
            if len(set(self.pages)) != len(self.pages):
                raise ValueError("capture_judge.pages must be unique")
            return self
    ```
  - Drop `RubricEntry.agent_task`; add
    `RubricEntry.capture_judge: CaptureJudgeTask | None = None`.
  - Update `_check_probe_xor_agent_task` (rename to
    `_check_probe_xor_capture_judge`) to enforce: `capture_judge` is set
    iff `level == "capture_judge"`; `probe` is set iff
    `level != "capture_judge"`.
  **Check:** strict pyright passes.
- [ ] **T1.2** — `packages/shop_arena/src/shop_probe/rubric/loader.py`:
  drop the `"v1"`, `"v1.1"`, `"v1.2"`, `"v1.3"` mappings; register
  `"v2"` → `v2.yaml`. **Check:** `load_rubric("v2")` returns a `Rubric`
  instance; `load_rubric("v1.3")` raises a clear "unknown rubric
  version" error.
- [ ] **T1.3** —
  `packages/shop_arena/src/shop_probe/rubric/v2.yaml`: copy the 66
  v1.1 entries verbatim from `v1.1.yaml` (preserving order +
  `authenticated`/`transactional` flags), bump `version: v2`, then
  append the 8 capture-judge entries from Appendix B below. Each entry
  has `level: capture_judge`, no `probe:`, with a fully populated
  `capture_judge:` block. Categories + weights match v1.2 advanced
  (collection ×4, product ×2, search ×1, dynamics ×1; total weight 14).
  **Check:** YAML round-trips through the loader; total entry
  count = 74.
- [ ] **T1.4** — Delete the retired rubric files:
  `packages/shop_arena/src/shop_probe/rubric/{v1,v1.1,v1.2,v1.3}.yaml`.
- [ ] **T1.5** — Tests:
  - Add `packages/shop_arena/tests/shop_probe/test_rubric_v2.py`:
    ```
    EXPECTED_V2_HASH = "<paste once tests run>"
    EXPECTED_V2_VERSION = "v2"
    EXPECTED_V2_PROBE_COUNT = 74
    EXPECTED_V2_CAPTURE_JUDGE_COUNT = 8
    EXPECTED_CAPTURE_JUDGE_IDS = frozenset({
        "collection.sort.changes_order",
        "collection.filters.applies_to_results",
        "collection.pagination.advances",
        "collection.filters.url_state_advances",
        "product.variant.swap_updates_state",
        "product.qty.spinner_increments",
        "search.predictive.populates_listbox",
        "dynamics.cart_count_badge_updates",
    })
    ```
    Assert: hash pin, version, total count, capture-judge count, the 8
    canonical IDs, every capture-judge entry has
    `authenticated=False`/`transactional=False` and a non-None
    `capture_judge` block, sum of capture-judge weights = 14.
  - Replace `tests/test_rubric_schema_agent.py` with
    `tests/test_rubric_schema_capture_judge.py` covering: capture_judge
    entry parses; capture_judge entry missing `capture_judge` block →
    ValidationError; core entry with `capture_judge` block →
    ValidationError; capture_judge with duplicate `pages` →
    ValidationError; capture_judge with empty `pages` → ValidationError.
  - Delete the v1.x rubric tests:
    `tests/shop_probe/test_rubric_v1.py`,
    `test_rubric_v1_1.py`, `test_rubric_v1_2.py`,
    `test_rubric_v1_3.py`.
  ```
  cd packages/shop_arena && uv run pytest \
      tests/shop_probe/test_rubric_v2.py \
      tests/test_rubric_schema_capture_judge.py -v
  cd packages/shop_arena && uv run pyright src/shop_probe/rubric/
  ```
  **Check:** all green; pyright + ruff clean.

**M1 acceptance:** v2.yaml loads, hash-pinned; capture_judge schema
round-trips; v1.x rubrics + their tests gone. Source tree no longer
imports `AgentTaskInline`.

**Commit:** `shop_probe(rubric): swap agent_driven for capture_judge; ship v2.yaml (M1)`

### M2 · Page bundle

**Goal:** New `capture/` subpackage produces a 5-row `PageBundle` per
shop, persisting screenshots + a11y JSON under `_bundle/<page>/`.

- [ ] **T2.1** —
  `packages/shop_arena/src/shop_probe/capture/__init__.py`:
  re-export `PageBundle`, `PageCapture`, `PageRef`, `capture_bundle`.
  **Check:** module imports without I/O.
- [ ] **T2.2** —
  `packages/shop_arena/src/shop_probe/capture/bundle.py`:
  - Frozen dataclasses (slots):
    ```python
    @dataclass(frozen=True, slots=True)
    class PageCapture:
        page_ref: PageRef
        url: str
        screenshot_rel: str | None
        accessibility_rel: str | None
        applicable: bool
        notes: str | None = None

    @dataclass(frozen=True, slots=True)
    class PageBundle:
        captures: tuple[PageCapture, ...]
        def get(self, page_ref: PageRef) -> PageCapture | None: ...
    ```
  - `async def capture_bundle(runner, *, base_url,
    sample_collection_url, sample_product_url, bundle_root) ->
    PageBundle`. One `runner.run(...)` call per page; the closure
    threaded into `runner.run` performs:
    1. `await page.goto(url, wait_until="domcontentloaded",
       timeout=15_000)`.
    2. `await page.screenshot(path=bundle_root / page_ref /
       "screenshot.png", full_page=False)`.
    3. `tree = await page.accessibility.snapshot(interesting_only=True)`;
       `(bundle_root / page_ref / "a11y.json").write_text(json.dumps(
       tree, sort_keys=True, ensure_ascii=False, separators=(",", ":")))`.
    4. Return `ProbeOutcome(passed=True)` so the runner records
       `duration_ms` (we discard the outcome — the bundle is what we
       care about).
  - URL resolution table:
    | page_ref | URL |
    |---|---|
    | `home` | `base_url` |
    | `collection` | `sample_collection_url` (None ⇒ `applicable=False`) |
    | `product` | `sample_product_url` (None ⇒ `applicable=False`) |
    | `cart` | `urljoin(base_url, "/cart")` |
    | `search` | `urljoin(base_url, "/search?q=test")` |
  - `capture_bundle` never raises. Wrap each per-page closure in
    `try / except (PlaywrightError, asyncio.TimeoutError, OSError) as
    exc:` → record `PageCapture(applicable=False,
    notes=f"{type(exc).__name__}: {exc}"[:200])`. Same for missing
    sample URLs (`notes="sample URL not discovered"`).
  - Use `runner.run` with a per-call `probe_id=f"_bundle/{page_ref}"`
    so existing isolated-context discipline + viewport + UA apply.
  **Check:** strict pyright passes; module import-safe.
- [ ] **T2.3** — `packages/shop_arena/tests/capture/__init__.py`
  (empty), `tests/capture/test_bundle.py`:
  - Stub Page/Context to feed canned a11y trees + screenshot bytes;
    assert all 5 captures land with `applicable=True`, files persisted
    under the temp `bundle_root`, JSON parseable, PNG header
    (`b"\x89PNG"`) present.
  - `sample_collection_url=None` → `collection` capture
    `applicable=False`, `notes` non-empty, no file written.
  - Stub raises `PlaywrightTimeoutError` on the cart goto → cart
    capture `applicable=False`, `notes` carries the type name; bundle
    iteration continues.
  - `accessibility.snapshot` raises → capture `applicable=False`,
    screenshot still written or absent (whichever side fired first;
    test asserts no exception leaks out of `capture_bundle`).
  ```
  cd packages/shop_arena && uv run pytest tests/capture/ -v
  cd packages/shop_arena && uv run pyright src/shop_probe/capture/
  ```
  **Check:** all green; ruff clean.

**M2 acceptance:** stub-driven bundle test green; `capture_bundle`
produces a 5-capture bundle from a stub Page; failures localized to
individual `PageCapture` rows; no I/O at import.

**Commit:** `shop_probe(capture): bundle 5-page screenshot + a11y stack (M2)`

### M3 · Capture judge

**Goal:** `agent/judge.py:run_capture_judge` issues one Messages-API
call with N image+a11y blocks; returns the existing `JudgeVerdict`
shape.

- [ ] **T3.1** —
  `packages/shop_arena/src/shop_probe/agent/judge.py` rewrite:
  - Keep `JudgeVerdict` dataclass, `_RATE_TABLE`, `_DEFAULT_RATE`,
    `_PASSED_FALLBACK_RE`, `_JSON_BLOCK_RE`, `_MAX_OUTPUT_TOKENS`,
    `_encode_image`, `_compute_cost`, `_extract_text`, `_parse_verdict`
    verbatim.
  - Drop `run_completion_judge` and `_build_user_content` (BEFORE/AFTER
    + trajectory shape — no caller in v2).
  - New
    ```python
    async def run_capture_judge(
        captures: tuple[PageCapture, ...],
        bundle_root: Path,
        judge_prompt: str,
        *,
        model: str = "claude-opus-4-7",
        client: AsyncAnthropic | None = None,
    ) -> JudgeVerdict: ...
    ```
    Body:
    1. `applicable = tuple(c for c in captures if c.applicable)`.
    2. If `not applicable`: return `JudgeVerdict(passed=False,
       reasoning="bundle pages unavailable", cost_usd=0.0,
       model_id=model)` — **no API call**.
    3. Lazy env load: `load_agent_env(); require_anthropic_credentials()`.
    4. `client = client or AsyncAnthropic()`.
    5. Build content list via new
       `_build_capture_judge_content(applicable, bundle_root,
       judge_prompt) -> list[dict[str, object]]`. Layout (top-to-bottom):
       - For each `PageCapture` in iteration order (matches
         `entry.capture_judge.pages` order from the dispatcher):
         - text label `f"{capture.page_ref} ({capture.url}) — screenshot:"`
         - image block from `bundle_root / capture.screenshot_rel`
         - text label
           ```
           {capture.page_ref} accessibility tree:
           ```json
           {a11y JSON, read from bundle_root / capture.accessibility_rel}
           ```
           ```
       - then text:
         ```
         Rubric question:
         {judge_prompt}

         Decide whether the storefront exposes the affordance described
         above. You are looking at static page captures — judge structural
         presence, not interaction. Respond with a single-line JSON object
         exactly of the form
         {"passed": <true|false>, "reasoning": "<one short sentence>"}.
         Do not wrap the response in Markdown.
         ```
    6. `response = await client.messages.create(model=model,
       max_tokens=_MAX_OUTPUT_TOKENS, messages=[{"role": "user",
       "content": content}])`.
    7. Parse via `_extract_text` + `_parse_verdict`; project cost via
       `_compute_cost`. Return `JudgeVerdict`.
  **Check:** strict pyright passes; module import-safe (no
  `AsyncAnthropic` constructed at import time).
- [ ] **T3.2** —
  `packages/shop_arena/src/shop_probe/agent/__init__.py`:
  drop the `AgentRuntimeConfig` re-export. Re-export
  `JudgeVerdict, run_capture_judge` from `judge`. Keep
  `load_agent_env, require_anthropic_credentials` re-exports from `env`.
  **Check:** import audit — `from shop_probe.agent import …` only
  surfaces the four names above.
- [ ] **T3.3** — Replace `tests/agent/test_judge.py` content:
  - Stub `AsyncAnthropic.messages.create` returning a typed
    `Message`-like object with `content=[TextBlock(text="...")]` +
    `usage.input_tokens=1234`, `usage.output_tokens=56`.
  - Cases:
    - 2 applicable captures → request body has 2 image blocks (assert
      `data` length > 0 each) + the `judge_prompt` substring; verdict
      `passed=True`, `cost_usd > 0`, `model_id="claude-opus-4-7"`.
    - 1 applicable + 1 inapplicable capture → request body has 1
      image block (only the applicable page).
    - All inapplicable → `passed=False`, `reasoning="bundle pages
      unavailable"`, `cost_usd=0.0`, **stub create not called**
      (`stub.create.call_count == 0`).
    - Stub returns `"yes the page has a sort dropdown"` (malformed) →
      verdict via fallback regex; `reasoning` prefixed
      `[fallback parse]`.
    - Stub returns `passed=true, reasoning='ok'` not wrapped in JSON →
      regex fallback fires; verdict still parsed.
  - Delete `tests/agent/test_runner.py`, `tests/agent/test_dispatch.py`
    (no agent runner / agent dispatch in v2).
  ```
  cd packages/shop_arena && uv run pytest tests/agent/ -v
  cd packages/shop_arena && uv run pyright src/shop_probe/agent/
  ```
  **Check:** all green.

**M3 acceptance:** `run_capture_judge` produces a verdict from a
stubbed client across multi-page, single-page, all-inapplicable, and
malformed-response cases.

**Commit:** `shop_probe(agent): rewrite judge for capture-bundle inputs (M3)`

### M4 · Dispatcher integration

**Goal:** `_run` (axis A) calls `capture_bundle` once per shop, then
dispatches `level: capture_judge` entries through `run_capture_judge`.

- [ ] **T4.1** —
  `packages/shop_arena/src/shop_probe/probes/_runner.py`:
  - Drop `agent_config: AgentRuntimeConfig | None` field from
    `ProbeContext`.
  - Drop `ProbeRunner.run_agent_entry` and the
    `DEFAULT_AGENT_TIMEOUT_S` / `AGENT_BUFFER_S` module constants.
  - Drop the `from shop_probe.agent.config import AgentRuntimeConfig`
    import.
  **Check:** pyright clean; deterministic-probe tests still pass.
- [ ] **T4.2** —
  `packages/shop_arena/src/shop_probe/cli.py`:
  - Add `from shop_probe.capture import capture_bundle` and
    `from shop_probe.agent.judge import JudgeVerdict, run_capture_judge`.
  - In `_run` (axis A path), after `_discover_sample_urls`, call:
    ```python
    bundle_root = evidence_root / "_bundle"
    bundle = await capture_bundle(
        runner,
        base_url=target.base_url,
        sample_collection_url=sample_collection_url,
        sample_product_url=sample_product_url,
        bundle_root=bundle_root,
    )
    ```
  - Replace the `entry.level == "agent_driven"` branch with:
    ```python
    if entry.level == "capture_judge":
        outcome = await _run_capture_judge_entry(
            entry,
            bundle=bundle,
            bundle_root=bundle_root,
            judge_model=judge_model,
        )
    ```
  - New helper `_run_capture_judge_entry(entry, *, bundle, bundle_root,
    judge_model) -> ProbeOutcome`:
    1. `assert entry.capture_judge is not None`.
    2. Slice the bundle: `requested = tuple(bundle.get(p) for p in
       entry.capture_judge.pages)`. Skip any `None` (shouldn't happen —
       bundle always has all 5 captures, even when inapplicable).
    3. If every requested capture has `applicable=False`:
       return `ProbeOutcome(passed=None,
       notes="all requested bundle pages unavailable",
       evidence=tuple(_evidence_refs_for(c, bundle_root) for c in
       requested if c.screenshot_rel))`.
    4. `verdict = await run_capture_judge(requested, bundle_root,
       entry.capture_judge.judge_prompt, model=judge_model)`.
    5. Build `evidence: tuple[EvidenceRef, ...] =
       tuple(_evidence_refs_for(c, bundle_root) for c in requested
       if c.applicable)`. Each capture contributes two
       `EvidenceRef`s — one `kind="screenshot"`, one `kind="a11y"`.
    6. Return `ProbeOutcome(passed=verdict.passed, evidence=evidence,
       notes=None if verdict.passed else verdict.reasoning,
       extra={"judge_cost_usd": verdict.cost_usd, "judge_model":
       verdict.model_id})`.
  - Update `_aggregate_coverage` (`cli.py:759`):
    `level_bucket = "advanced" if entry.level == "capture_judge"
    else entry.level`.
  - Drop `agent_config` parameter from `_run`; drop
    `agent_config=_build_agent_config(args)` at the call site.
  **Check:** pyright clean.
- [ ] **T4.3** — Tests:
  - New `tests/shop_probe/test_dispatch_capture_judge.py`:
    - Build a 1-entry rubric with a `capture_judge` row + minimal
      inline block (`pages: [home]`); stub `capture_bundle` and
      `run_capture_judge`. Assert the dispatcher calls
      `run_capture_judge` with the bundle slice for `home`, and the
      report row carries `judge_cost_usd` from the stub verdict.
    - All-inapplicable bundle path: stub bundle returns `applicable=False`
      for every page; assert dispatcher returns `passed=None`,
      `notes` mentions unavailability, `run_capture_judge` not called.
  ```
  cd packages/shop_arena && uv run pytest \
      tests/shop_probe/test_dispatch_capture_judge.py -v
  cd packages/shop_arena && uv run pyright \
      src/shop_probe/cli.py src/shop_probe/probes/_runner.py
  ```
  **Check:** all green; existing deterministic dispatch tests still green.

**M4 acceptance:** end-to-end capture-judge dispatch path works against
stubs; bundle persisted under `_bundle/`; `_aggregate_coverage` rolls
capture_judge into `coverage_advanced`.

**Commit:** `shop_probe(probes): wire capture_judge dispatch via run_capture_judge (M4)`

### M5 · CLI flag cleanup + report schema

**Goal:** four `--agent-*` flags collapse to one `--judge-model`;
agent cost fields removed from `ProbeResult` / `ProbeReport`;
`_aggregate_cost_totals` returns judge total only.

- [ ] **T5.1** —
  `packages/shop_arena/src/shop_probe/cli.py`:
  - Delete `_DEFAULT_AGENT_CONFIG`, `_AGENT_RUNTIME_CHOICES`,
    `_add_agent_flags`, `_build_agent_config`, and every
    `args.agent_*` reference.
  - Add a single `_add_judge_flag(parser)` adding
    `--judge-model TEXT` (default `"claude-opus-4-7"`). Wire it into
    both `run` and `eval` subparsers. `eval` forwards
    `--judge-model VALUE` into each spawned `run` invocation argv.
  - Default rubric flips: replace `"v1"` literal at the rubric-flag
    declaration with `"v2"` (`cli.py:170`, `cli.py:334`).
  **Check:** pyright clean; `shop-probe run --help` shows
  `--judge-model` only.
- [ ] **T5.2** —
  `packages/shop_arena/src/shop_probe/report.py`:
  - Drop `ProbeResult.agent_cost_usd` and `ProbeResult.agent_model`
    fields; update the docstring to remove the v1.3 surface.
  - Drop `ProbeReport.total_agent_cost_usd`.
  - Update the docstring on `total_judge_cost_usd` to reference v2.
  **Check:** pyright clean.
- [ ] **T5.3** —
  `packages/shop_arena/src/shop_probe/cli.py:_aggregate_cost_totals`:
  return only the judge total (`float | None`); update the call site at
  `_run` (currently `total_judge_cost_usd, total_agent_cost_usd =
  _aggregate_cost_totals(...)` → `total_judge_cost_usd =
  _aggregate_cost_totals(...)`); drop `total_agent_cost_usd=…` from the
  `ProbeReport` constructor invocation.
- [ ] **T5.4** —
  `packages/shop_arena/src/shop_probe/_build_probe_result` (in
  `cli.py`): drop the
  `agent_cost_usd=_extra_float(outcome.extra, "agent_cost_usd")`,
  `agent_model=_extra_str(outcome.extra, "agent_model")` lines.
- [ ] **T5.5** — Tests:
  - Rewrite `tests/shop_probe/test_cli_cost_aggregation.py` for
    judge-only totals: deterministic-only cohort → `None`; one
    capture-judge probe → single non-zero total.
  - Rewrite `tests/shop_probe/test_report.py` to drop assertions over
    `agent_cost_usd` / `agent_model` / `total_agent_cost_usd`.
  - Delete `tests/shop_probe/test_cli_agent_flags.py`. Add
    `tests/shop_probe/test_cli_judge_flag.py`: `--rubric v2
    --judge-model claude-sonnet-4-6` is parsed and forwarded into
    `_run` (assert via stub).
  ```
  cd packages/shop_arena && uv run pytest \
      tests/shop_probe/test_cli_judge_flag.py \
      tests/shop_probe/test_cli_cost_aggregation.py \
      tests/shop_probe/test_report.py -v
  cd packages/shop_arena && uv run pyright \
      src/shop_probe/cli.py src/shop_probe/report.py
  ```
  **Check:** all green.

**M5 acceptance:** `shop-probe run --rubric v2 --judge-model …` parses;
report schema carries judge fields only; cost aggregation returns one
total.

**Commit:** `shop_probe(cli): collapse agent flags to --judge-model; drop agent cost fields (M5)`

### M6 · Removals + spec swap

**Goal:** retire all v1.3 surface from source + docs in one commit.

- [ ] **T6.1** — Delete files:
  - `packages/shop_arena/src/shop_probe/agent/runner.py`
  - `packages/shop_arena/src/shop_probe/agent/config.py`
  - (Spec/impl docs for v1.2/v1.3 already retired in the consolidation
    pass; only source files remain.)
- [ ] **T6.2** — Confirm no source file imports
  `shop_probe.agent.runner`, `shop_probe.agent.config`, or
  `AgentRuntimeConfig`:
  ```
  cd packages/shop_arena && rg -n "agent\.(runner|config)|AgentRuntimeConfig" src/ tests/
  ```
  Expected: zero matches. Fix any stragglers from M1–M5 that leaked
  references.
- [x] **T6.3** — Spec consolidation already done:
  `docs/specs/shop_arena/shop_probe.md` is the single source of truth
  for the rubric structure (§5.3) and the report shape (§5.6). The
  retired v1.x and patch specs are summarized under §3 "Retired surface"
  for educational record only.
- [ ] **T6.4** —
  `packages/shop_arena/src/shop_probe/README.md`: replace the v1.3
  agent-driven tier section with a v2 capture-judge tier section. Cost
  table mirrors spec §Desired Status (~$3 cohort default, ~$0.60 with
  Sonnet via `--judge-model claude-sonnet-4-6`); flag list shows
  `--judge-model` only.
- [ ] **T6.5** — Final test sweep:
  ```
  cd packages/shop_arena && uv run pytest -q
  cd packages/shop_arena && uv run pyright src tests
  ```
  **Check:** clean.

**M6 acceptance:** `git grep -i "agent_driven\|agent_task\|AgentRuntimeConfig"`
in `packages/shop_arena/src` returns zero hits. Repo builds clean.

**Commit:** `shop_probe: retire v1.x rubrics and v1.3 agent surface (M6)`

### M7 · Smoke + cohort

**Goal:** real-world validation. No code changes — operator workflow only.

- [ ] **T7.1** — Single-shop smoke (1 sandbox + 1 real, `--reruns 1`):
  ```
  cd packages/shop_arena && uv run shop-probe run \
      <sandbox-cloud-run-url> \
      --name mock_clothing --label sandbox \
      --rubric v2 --reruns 1 \
      --out /tmp/v2_smoke
  ```
  Verify (per shop):
  - `outputs/.../reports/<label>__<name>__rerun1.json` has 8
    capture-judge probes with non-`None` verdicts.
  - `outputs/.../evidence/<label>__<name>__rerun1/_bundle/<page>/{screenshot.png,
    a11y.json}` exists for `home`, `cart`, `search`, plus `collection`
    + `product` if sample URLs were discovered.
  - Wall time < 90 s for one shop.
  - Per-probe `judge_cost_usd` ≈ $0.05 (Opus); cohort cost ≈
    $0.05 × 8 = $0.40 per shop.
  - Repeat with `--judge-model claude-sonnet-4-6`; verify
    `judge_model` field updates and per-probe cost ≈ $0.01.
  **Check:** both runs produce a complete report; spot-check 2 verdicts
  manually against the captured screenshot + a11y JSON.
- [ ] **T7.2** — Full cohort:
  ```
  cd packages/shop_arena && uv run shop-probe eval \
      --benchmark outputs/shop_probe/benchmark.yaml \
      --out outputs/shop_probe/result_v2 \
      --reruns 1 --rubric v2 --axes A,B --gate 0.01
  ```
  Expectations:
  - 7 shops × 8 probes × 1 rerun = 56 capture-judge calls.
  - Wall time **< 15 min** at default 4-way target parallelism (vs.
    ~3 h on v1.3).
  - Total cost ~$3 (Opus default).
  - `figures/group_comparison.md`, `figures/radar.svg`,
    `figures/surface.svg` render without errors.
  - No `agent_*` fields appear in any `reports/*.json`.
  **Check:** cohort reports written; figures rendered; cost within
  budget; smoke logs free of stack traces.
- [ ] **T7.3** — Quality spot-check: pick 3 capture-judge entries
  whose verdict is `False` and 3 whose verdict is `True` from
  `result_v2/reports/`, eyeball the bundle screenshot + a11y JSON
  against the rubric prompt, record any false-positive / false-negative
  pattern in the M7 commit message. >5% disagreement triggers a
  follow-up issue (chain-of-thought prompt or judge-twice-and-agree —
  out of scope here).

**M7 acceptance:** cohort eval completes < 15 min; `total_judge_cost_usd`
reasonable; figures render; spot-check disagreement < 5%.

**Commit:** `shop_probe: cohort run results for v2 (M7)`

---

## 6. Verification matrix

| Milestone | Type-check | Unit | Smoke | Cohort |
|---|---|---|---|---|
| M1 schema + rubric | ✓ | ✓ schema + rubric hash | — | — |
| M2 capture bundle | ✓ | ✓ stub Page | — | — |
| M3 capture judge | ✓ | ✓ stub Anthropic | — | — |
| M4 dispatch | ✓ | ✓ stub bundle + judge | — | — |
| M5 CLI + report | ✓ | ✓ flag forwarding + cost aggregation | — | — |
| M6 removals | ✓ | ✓ full sweep | — | — |
| M7 smoke + cohort | — | — | ✓ 2 shops | ✓ 7 shops |

End-to-end, post-M6:

1. `cd packages/shop_arena && uv run pytest -q`
2. `cd packages/shop_arena && uv run pyright src tests`
3. M7 smoke + cohort.

## 7. Out of scope

- **No deterministic-vs-capture-judge comparison runs.** The 8 v1.2
  deterministic probes are deleted alongside `v1.2.yaml` in M1; v2
  ships the capture-judge replacement only.
- **No agent layer revival.** `agent/runner.py`, `agent/config.py`, and
  the four `--agent-*` flags are deleted in M1/M5/M6 and not restored.
- **No interaction probes.** Capture-judge inspects static page state.
  Behavioural fidelity for the 8 advanced slots is intentionally
  relaxed (spec §A.4).
- **No backfill of v2 results onto v1.x reports.** Separate measurement
  instruments; v1.x rubric YAMLs are deleted, so v1.x reports become
  non-reproducible by version. Acceptable for pre-paper cleanup.
- **No follow-up flake mitigation** (chain-of-thought judge, judge
  twice-and-agree). Defer until M7 cohort surfaces a real flake rate.
- **No DOM input to the judge.** Accessibility-tree only per spec
  §Alternative.
- **No per-entry capture.** All entries share the 5-page bundle; new
  entry kinds that demand a different page must extend the `PageRef`
  literal + the `capture_bundle` URL table in a follow-up.

---

## Appendix A — Reference judge content layout

`agent/judge.py:_build_capture_judge_content` produces (one screenshot,
one a11y block, one prompt block):

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

## Appendix B — The 8 v2 capture-judge rubric entries

YAML appended to `v2.yaml` after the 66 v1.1 entries. IDs / categories /
weights match v1.2 advanced verbatim — slots stable for cross-version
comparison.

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
      opens one) configured for predictive results — e.g. role=combobox
      / aria-autocomplete / aria-controls referencing a results listbox?
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

Total weight: 14 (collection 7 + product 3 + search 2 + dynamics 2),
identical to v1.2 advanced.

## Appendix C — Cost / latency budget (defaults)

| Unit | Cost | Latency |
|---|---|---|
| One bundle capture (5 pages, headless Chromium) | $0.00 | ~10 s |
| One capture-judge call (Opus, ≤2 images + a11y JSON) | ~$0.05 | ~5 s |
| One probe (1 judge call) | ~$0.05 | ~5 s |
| Single-shop axis-A run (1 bundle + 8 judges) | ~$0.40 | ~50 s |
| Full cohort (7 × 8 probes + 7 bundle passes, 4-way parallel) | ~$3 | ~6 min |

Sonnet 4.6 cuts ~5×: cohort cost ~$0.60 with `--judge-model
claude-sonnet-4-6`. v1.x cohorts no longer exist in v2 (rubric YAMLs
deleted) — the only paid path is the 8 capture-judge entries.

## Appendix D — Risks / open questions

- **Bundle navigation timeouts.** 15 s `goto` timeout per page; 5 pages
  worst-case = 75 s if every page hangs. Mitigation: per-page
  `try / except` already returns `applicable=False` rather than
  blocking the cohort. T7.1 spot-checks this against a deliberately
  slow fixture.
- **a11y tree size on heavy pages.** Hydrogen homepages produce ~5–10
  KB compact JSON; non-trivial real-shop catalogs (~50 product cards
  on a collection page) can hit ~30 KB. Within the Anthropic
  Messages-API content budget by an order of magnitude. If a
  pathological page exceeds 100 KB, truncate to the first 100 KB and
  log a note on the `PageCapture`. Out of scope unless M7 surfaces it.
- **Judge bias toward "passed=true".** Vision Opus over-eagerly
  affirms ambiguous prompts. M7 spot-check (T7.3) measures this; >5%
  false positives triggers a chain-of-thought prompt revision in a
  follow-up.
- **Sample URL discovery flake.** `_discover_sample_urls` is reused
  verbatim. When it fails, every collection / product capture is
  inapplicable and four capture-judge entries report `passed=None`
  (skipped from coverage). This is the same failure mode the
  deterministic v1.2 probes already tolerated — no new mitigation
  needed for v2.
- **Anthropic rate limits.** 7 shops × 8 probes = 56 calls within ~6
  min at 4-way parallelism. Within standard Tier-3 quota; verify
  before scaling parallelism beyond 4-way.
