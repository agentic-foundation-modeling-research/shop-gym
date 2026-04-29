# ShopProbe v1.3 / agent-driven advanced tier — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/shop_arena/web_probe_v1_3_agent_driven.md`](../specs/shop_arena/web_probe_v1_3_agent_driven.md) (drafted under T1.0 below)
Target module: `packages/shop_arena/src/shop_probe`

> Pure task list. Seven milestones land as seven git commits on
> `mz/dev-visual-judge`. No PRs in this batch.

---

## 1. Overview

Replace the v1.2 `advanced` tier (8 deterministic Playwright probes whose
selector unions are biased toward Hydrogen DOMs and produce a spurious
sandbox-vs-real gap of `coverage_advanced` 0.238 vs 0.028) with 8
**agent-driven** probes. Each probe runs `harness.run_plan_exec_loop` with
the existing `playwright-browser` skill (`claude_code` runtime by default,
`pi` available as alternate); a vision Anthropic Messages API call inspects
before/after screenshots + the trajectory and decides pass/fail.

Make task-set extension a YAML-only edit: each `level: agent_driven`
rubric entry carries an inline `agent_task:` block (`goal`, `judge_prompt`,
`precondition_url_attr`, optional `step_budget`/`timeout_s`). One generic
runner serves every agent-driven entry — no per-task wrapper coroutines, no
`probes/agent_tasks.py`, no `AGENT_TASKS` dict. Adding a 9th task is one
YAML edit.

## 2. Terminology

Uses the v1.3 spec's vocabulary verbatim. Key terms reintroduced for
convenience:

- **Agent-driven probe** — rubric entry with `level: agent_driven` whose
  inline `agent_task` block drives an agent + judge instead of a Python
  probe coroutine.
- **Inline `agent_task` block** — Pydantic `AgentTaskInline` model attached
  to each agent-driven entry; carries `goal`, `judge_prompt`,
  `precondition_url_attr`, optional per-task `step_budget` / `timeout_s`.
- **Generic runner** — `agent/runner.py:run_agent_task(page, ctx, task)`.
  One coroutine for all agent-driven entries.
- **Completion judge** — `agent/judge.py:run_completion_judge(...)`.
  Anthropic vision call returning `JudgeVerdict` (`passed`, `reasoning`,
  `cost_usd`, `model_id`).

## 3. Current Status

`packages/shop_arena/src/shop_probe/rubric/`:
- `v1.yaml` (61 entries), `v1.1.yaml` (66), `v1.2.yaml` (74; 8 advanced
  behavioral via deterministic selectors).
- `RubricLevel = Literal["core", "modern", "advanced"]`.
- `RubricEntry.probe: str` is required.

`packages/shop_arena/src/shop_probe/probes/`: 8 v1.2 advanced probe
coroutines in `collection.py` / `product.py` / `search.py` / `dynamics.py`.

`packages/shop_arena/src/shop_probe/judge/agent.py:103-202` is the working
template for "give the agent a task, run harness, project trajectory,
persist artifact" — used today for the Turing-test classifier and reused
verbatim (with a different post-condition) by v1.3.

`harness.run_plan_exec_loop` and `harness.runtimes.{claude_code,pi}` are
production-ready and already configured for `claude-opus-4-7`.

The 7-shop cohort run on 2026-04-29 produced
`outputs/shop_probe/result_v1_2/figures/` showing the rubric-shape bias:
sandbox group beats real group 0.238 vs 0.028 on the advanced tier.

## 4. Desired Status

After M7: `--rubric v1.3` resolves a 74-entry rubric (66 v1.1 verbatim + 8
agent-driven). Each agent-driven probe captures a before-screenshot,
spawns a harness loop with the inline `goal`, persists the trajectory under
`<evidence_dir>/<probe_id>/harness/`, calls the judge with the inline
`judge_prompt`, and emits a `ProbeOutcome` whose `passed` is the judge
verdict and whose `notes` is the judge's reasoning when failing. Per-probe
agent + judge cost is recorded in the report. Cost defaults to ~$72/cohort
(Opus); ~$15 with Sonnet via `--agent-model`. Adding a 9th task is one
YAML edit.

---

## 5. Proposal — Task list

### M1 · Schema + scaffolding

**Goal:** spec + impl docs land; schema accepts a new `level: agent_driven`
entry with an inline `agent_task:` block; v1.1 / v1.2 rubrics still load.

- [x] **T1.0** — Write spec at
  `docs/specs/shop_arena/web_probe_v1_3_agent_driven.md` following the
  CLAUDE.md spec template (Overview / Terminology / Current Status /
  Desired Status / Proposal / Alternative / Milestones / Appendix). Add a
  one-row index entry to `docs/specs/README.md` under "ShopArena":
  ```
  | [shop_arena/web_probe_v1_3_agent_driven.md](shop_arena/web_probe_v1_3_agent_driven.md) | `packages/shop_arena/src/shop_probe` | Agent-driven advanced tier: replaces v1.2 deterministic behavioural probes with LLM-agent + LLM-judge runs over inline `agent_task` rubric blocks. **Status:** Draft (proposed). | [impl](../impl/web_probe_v1_3_agent_driven_implementation.md) |
  ```
  **Check:** spec renders cleanly; impl doc + spec link to each other.
- [x] **T1.1** — `packages/shop_arena/src/shop_probe/rubric/schema.py`:
  extend `RubricLevel` literal with `"agent_driven"`; add new
  `AgentTaskInline` Pydantic model (`goal: str`, `judge_prompt: str`,
  `precondition_url_attr: Literal["base_url", "sample_collection_url",
  "sample_product_url"]`, optional `step_budget: int | None` ∈ [1, 50],
  optional `timeout_s: int | None` ∈ [10, 600]); make `RubricEntry.probe`
  optional (`str | None = None`); add
  `RubricEntry.agent_task: AgentTaskInline | None = None`; add a
  `model_validator(mode="after")` enforcing **exactly one of**
  `{probe, agent_task}` per entry, and `agent_task` is required iff
  `level == "agent_driven"`. **Check:** strict pyright passes; existing
  rubric load tests stay green.
- [x] **T1.2** — Scaffold `packages/shop_arena/src/shop_probe/agent/`:
  - `__init__.py` re-exports `AgentRuntimeConfig`.
  - `config.py` defines a frozen dataclass `AgentRuntimeConfig` with
    `runtime: Literal["claude_code", "pi"] = "claude_code"`,
    `model: str = "claude-opus-4-7"`, `step_budget: int = 15`,
    `timeout_s: int = 180`, `judge_model: str = "claude-opus-4-7"`.
  Also create `packages/shop_arena/tests/agent/__init__.py` (empty).
  **Check:** module imports without I/O; pyright strict-clean.
- [x] **T1.3** — Add `packages/shop_arena/tests/test_rubric_schema_agent.py`
  with cases:
  - agent_driven entry with inline block parses
  - agent_driven entry missing `agent_task` raises ValidationError
  - core entry with `agent_task` raises ValidationError
  - core entry without `probe` raises ValidationError (regression)
  Confirm v1, v1.1, v1.2 rubric tests stay green:
  ```
  cd packages/shop_arena && uv run pytest \
      tests/test_rubric_schema_agent.py \
      tests/shop_probe/test_rubric_v1.py \
      tests/shop_probe/test_rubric_v1_1.py \
      tests/shop_probe/test_rubric_v1_2.py -v
  ```
  **Check:** all green; pyright + ruff clean.

**M1 acceptance:** schema PR-equivalent commit lands cleanly; tests above
all green; no source code under `agent/` beyond the dataclass + exports.

**Commit:** `shop_probe(rubric): scaffold v1.3 agent_driven schema (M1)`

### M2 · Runner skeleton (no judge yet)

**Goal:** `run_agent_task(page, ctx, task)` runs the harness loop, persists
trajectory, returns a fixed-true `ProbeOutcome`. End-to-end wired so M3
only swaps the post-condition.

- [ ] **T2.1** — `packages/shop_arena/src/shop_probe/agent/runner.py`:
  define `run_agent_task(page, ctx, task) -> ProbeOutcome`. Pattern source:
  `shop_probe/judge/agent.py:103-202`. Steps:
  1. Resolve `cfg = ctx.agent_config or AgentRuntimeConfig()`.
  2. Resolve `start_url` from `task.precondition_url_attr` against
     `ctx`. If missing → return `passed=None` with a clear note.
  3. `await page.goto(start_url, wait_until="domcontentloaded")`; capture
     `before_shot = await ctx.screenshot("before-agent")`.
  4. Build harness `PlanExecConfig` with `run_dir=ctx.evidence_dir/
     "<probe_id>"/"harness"`, `max_iters=task.step_budget or
     cfg.step_budget`, `timeout_s=task.timeout_s or cfg.timeout_s`, prompts
     produced from `task.goal` (planner + executor templates inlined; see
     Appendix A).
  5. Build runtime via `_build_runtime(cfg)` (claude_code or pi). Call
     `await harness.run_plan_exec_loop(config, runtime)`.
  6. Read `after_shot` from the last `ScreenshotStep` in the trajectory;
     fall back to `before_shot` if no screenshots emitted.
  7. Return `ProbeOutcome(passed=True, evidence=(before_shot, after_shot,
     <harness run_dir>))`. M3 replaces the `True`.
  **Check:** strict pyright passes; module imports without side effects.
- [ ] **T2.2** — `packages/shop_arena/src/shop_probe/probes/_runner.py`:
  add `agent_config: AgentRuntimeConfig | None = None` to `ProbeContext`.
  No dispatch routing yet (lands in M4). **Check:** pyright clean;
  existing probe tests still green.
- [ ] **T2.3** — `packages/shop_arena/tests/agent/test_runner.py`:
  hermetic test cases (mirror `tests/judge/test_agent.py` pattern):
  - Stub harness loop writes a fake trajectory with two ScreenshotSteps;
    `run_agent_task` picks the second as `after_shot`.
  - `precondition_url_attr="sample_product_url"` with
    `ctx.sample_product_url=None` → `passed=None` with informative note.
  - Stub runtime records the executor prompt body it received; assert it
    contains `task.goal` verbatim.
  ```
  cd packages/shop_arena && uv run pytest tests/agent/test_runner.py -v
  cd packages/shop_arena && uv run pyright src/shop_probe/agent/runner.py
  ```
  **Check:** all green; ruff clean.

**M2 acceptance:** stub-driven test green; runner produces correct
ProbeOutcome shape; trajectory persisted under `evidence_dir/`.

**Commit:** `shop_probe(agent): runner skeleton wires harness loop (M2)`

### M3 · Completion judge

**Goal:** `run_completion_judge` issues the vision Anthropic Messages API
call and returns a structured `JudgeVerdict`.

- [ ] **T3.1** — `packages/shop_arena/src/shop_probe/agent/judge.py`:
  - Frozen dataclass `JudgeVerdict(passed: bool, reasoning: str,
    cost_usd: float, model_id: str)`.
  - `async def run_completion_judge(before_shot: Path, after_shot: Path,
    trajectory_text: str, judge_prompt: str, *, model: str =
    "claude-opus-4-7", client: AsyncAnthropic | None = None) ->
    JudgeVerdict`.
  - Build a single Messages API request with two `image` content blocks
    (base64 PNG) labelled BEFORE / AFTER, the `trajectory_text`, the
    inline `judge_prompt`, and a closing instruction asking for JSON
    `{"passed": bool, "reasoning": str}`.
  - Cost computation mirrors `shop_probe/judge/run.py:35-99`
    (`usage.input_tokens`, `usage.output_tokens` → per-model rate table).
  - Tolerate malformed JSON: fall back to a string-match heuristic on
    `"passed:\s*(true|false)"` and surface a `notes`-friendly reasoning.
  **Check:** strict pyright; module import-safe (no client construction
  at import time).
- [ ] **T3.2** — `packages/shop_arena/src/shop_probe/agent/runner.py`:
  replace the M2 stub `passed=True` with:
  ```python
  verdict = await run_completion_judge(
      before_shot, after_shot, _project_trajectory(trajectory),
      judge_prompt=task.judge_prompt, model=cfg.judge_model,
  )
  return ProbeOutcome(
      passed=verdict.passed,
      evidence=(before_shot, after_shot, run_dir),
      notes=None if verdict.passed else verdict.reasoning,
      extra={"judge_cost_usd": verdict.cost_usd,
             "judge_model": verdict.model_id},
  )
  ```
  Add `_project_trajectory(trajectory) -> str`: render the harness
  trajectory as a compact text block (per-iteration: `goal`, `tool calls`,
  final URL) suitable for the judge prompt context.
  **Check:** runner test from T2.3 needs an updated stub-judge expectation;
  add a test that asserts the `extra` dict carries `judge_cost_usd`.
- [ ] **T3.3** — `packages/shop_arena/tests/agent/test_judge.py`: stub
  `AsyncAnthropic` client + cases:
  - Request includes both image blobs (base64 length > 0) + the
    `judge_prompt` verbatim.
  - Stub returns `{"passed": true, "reasoning": "..."}` → verdict parses
    cleanly with `cost_usd > 0`.
  - Stub returns malformed string `"yes the order changed"` → verdict
    falls back to string-match, `notes` flags the fallback.
  ```
  cd packages/shop_arena && uv run pytest tests/agent/ -v
  cd packages/shop_arena && uv run pyright src/shop_probe/agent/
  ```
  **Check:** all green.

**M3 acceptance:** judge produces a verdict from a stubbed client; runner
emits a real ProbeOutcome shape end-to-end against fakes.

**Commit:** `shop_probe(agent): completion judge with vision (M3)`

### M4 · Wire dispatcher

**Goal:** A `level: agent_driven` rubric entry routes through
`run_agent_task` end-to-end inside `ProbeRunner`.

- [ ] **T4.1** — `packages/shop_arena/src/shop_probe/probes/_runner.py`:
  in `_run_one(entry, ctx)`, add the agent-driven branch before the
  existing deterministic dispatch:
  ```python
  if entry.level == "agent_driven":
      assert entry.agent_task is not None
      agent_timeout = (entry.agent_task.timeout_s
                       or DEFAULT_AGENT_TIMEOUT_S) + AGENT_BUFFER_S
      return await asyncio.wait_for(
          run_agent_task(self.page, ctx, task=entry.agent_task),
          timeout=agent_timeout,
      )
  ```
  Define module-level `DEFAULT_AGENT_TIMEOUT_S = 180`,
  `AGENT_BUFFER_S = 30`. Keep deterministic entries on the existing
  `DEFAULT_PROBE_TIMEOUT_S = 10` outer wait.
  **Check:** pyright clean; existing deterministic probe tests untouched.
- [ ] **T4.2** — `packages/shop_arena/tests/agent/test_dispatch.py`:
  build a 1-entry rubric with an `agent_driven` row + minimal inline
  block, run `ProbeRunner` against a stub Page + a stub
  `run_agent_task` (monkey-patched on the module). Assert stub was called
  with `task=entry.agent_task` and the report carries the stub's verdict.
  ```
  cd packages/shop_arena && uv run pytest tests/agent/ -v
  cd packages/shop_arena && uv run pyright src/shop_probe/probes/_runner.py
  ```
  **Check:** dispatch test green; deterministic dispatch tests still green.

**M4 acceptance:** end-to-end agent-driven dispatch path works against
stubs; outer timeout doesn't cut the inner harness loop.

**Commit:** `shop_probe(probes): dispatch agent_driven via run_agent_task (M4)`

### M5 · Rubric `v1.3.yaml`

**Goal:** Real rubric on disk, hash-pinned, all 8 inline blocks valid.

- [ ] **T5.1** — `packages/shop_arena/src/shop_probe/rubric/v1.3.yaml`:
  copy the 66 v1.1 entries verbatim from `v1.1.yaml` (preserving order),
  bump `version: v1.3`, then append the 8 agent-driven entries from
  Appendix B below. Each entry has `level: agent_driven`, no `probe:`,
  with a fully populated `agent_task:` block. Categories + weights match
  v1.2 advanced (collection ×4, product ×2, search ×1, dynamics ×1; total
  weight 14). **Check:** YAML round-trips through the loader; total entry
  count = 74.
- [ ] **T5.2** — `packages/shop_arena/src/shop_probe/rubric/loader.py`:
  register `"v1.3"` → `v1.3.yaml`. **Check:** `load_rubric("v1.3")`
  returns a `Rubric` instance.
- [ ] **T5.3** — `packages/shop_arena/src/shop_probe/probes/__init__.py`:
  module docstring lists the 8 agent-driven task IDs (linking to YAML,
  not Python). **Check:** docstring renders.
- [ ] **T5.4** — `packages/shop_arena/tests/shop_probe/test_rubric_v1_3.py`
  mirroring `test_rubric_v1_2.py` style:
  - `EXPECTED_V1_3_HASH = "<paste once tests run>"` — pin SHA-256 over
    raw YAML bytes after T5.1.
  - `EXPECTED_V1_3_VERSION = "v1.3"`.
  - `EXPECTED_V1_3_PROBE_COUNT = 74`.
  - `EXPECTED_V1_3_AGENT_DRIVEN_COUNT = 8`.
  - Test cases: hash pin, version, probe count, agent-driven count, every
    agent-driven entry has `authenticated=false` + `transactional=false`,
    every agent-driven entry has a non-None `agent_task` block, the 8 IDs
    match the canonical set, total `agent_driven` weight equals
    v1.2 `advanced` weight (14).
  ```
  cd packages/shop_arena && uv run pytest tests/shop_probe/test_rubric_v1_3.py -v
  ```
  **Check:** green.

**M5 acceptance:** v1.3 rubric loads, hash-pinned; v1.1/v1.2 unchanged.

**Commit:** `shop_probe(rubric): ship v1.3 with 8 agent-driven entries (M5)`

### M6 · CLI flags + report schema

**Goal:** `shop-probe run --rubric v1.3 --agent-runtime …` works end-to-end;
report records per-probe agent + judge cost.

- [ ] **T6.1** — `packages/shop_arena/src/shop_probe/cli.py`: add five
  flags to both the `run` and `eval` subcommands (defaults match
  `AgentRuntimeConfig`):
  ```
  --agent-runtime [claude_code|pi]   default claude_code
  --agent-model TEXT                 default claude-opus-4-7
  --agent-step-budget INTEGER        default 15
  --agent-timeout-s INTEGER          default 180
  --agent-judge-model TEXT           default claude-opus-4-7
  ```
  Build `AgentRuntimeConfig` from flags; pass into `ProbeContext`. `eval`
  forwards all five into each spawned `run` invocation. **Check:**
  `--rubric v1.1` ignores all flags, makes zero Anthropic calls.
- [ ] **T6.2** — `packages/shop_arena/src/shop_probe/report.py`:
  `ProbeResult` gains optional `judge_cost_usd: float | None`,
  `judge_model: str | None`, `agent_cost_usd: float | None`,
  `agent_model: str | None`. `ProbeReport` aggregates totals
  (`total_judge_cost_usd`, `total_agent_cost_usd`). **Check:** existing
  report tests still green; new test asserts cost fields populate from
  `ProbeOutcome.extra`.
- [ ] **T6.3** — `packages/shop_arena/src/shop_probe/README.md`: new
  "v1.3 agent-driven tier" section under "Run probes against one
  storefront". Rubric description, flags table, cost expectation
  (~$72/cohort default Opus, ~$15 with Sonnet via `--agent-model
  claude-sonnet-4-6`). **Check:** README renders; flags table matches
  T6.1 verbatim.
- [ ] **T6.4** — `packages/shop_arena/tests/shop_probe/test_cli_agent_flags.py`:
  - v1.1 rubric + default flags → no Anthropic calls (assert via stub).
  - v1.3 rubric + stub runner/judge → flags forwarded into
    `ProbeContext.agent_config`.
  - `eval` forwards flags into spawned `run` invocations (subprocess
    argv inspection via mock).
  ```
  cd packages/shop_arena && uv run pytest \
      tests/shop_probe/test_cli_agent_flags.py \
      tests/shop_probe/test_rubric_v1_3.py \
      tests/agent/ -v
  cd packages/shop_arena && uv run pyright \
      src/shop_probe/cli.py src/shop_probe/report.py
  ```
  **Check:** all green.

**M6 acceptance:** CLI invocations work end-to-end with flags; cost is
recorded; v1.1 cohorts incur zero API cost.

**Commit:** `shop_probe(cli): plumb --agent-* flags + record judge cost (M6)`

### M7 · Smoke + cohort

**Goal:** Real-world validation. No code changes — operator workflow only.

- [ ] **T7.1** — Single-shop smoke (1 sandbox + 1 real, `--reruns 1`):
  ```
  cd packages/shop_arena && uv run shop-probe run \
      <sandbox-cloud-run-url> \
      --name mock_clothing --label sandbox \
      --rubric v1.3 --reruns 1 \
      --out /tmp/v1_3_smoke
  ```
  Verify (per shop):
  - `outputs/.../reports/<label>__<name>__rerun1.json` has 8 agent-driven
    probes with non-`None` verdicts.
  - `outputs/.../evidence/<label>__<name>__rerun1/<probe_id>/harness/`
    contains `plan.md`, iteration screenshots, and `trajectory.json`.
  - Wall time < 25 min for one shop.
  - Per-probe `judge_cost_usd` ≈ $0.01; `agent_cost_usd` ≈ $0.25; total
    ≈ $2 per shop.
  - Repeat against one real shop URL; same expectations.
  **Check:** both shops produce a complete report; spot-check 2 judge
  verdicts manually against the screenshots.
- [ ] **T7.2** — Full cohort:
  ```
  cd packages/shop_arena && uv run shop-probe eval \
      --benchmark outputs/shop_probe/benchmark.yaml \
      --out outputs/shop_probe/result_v1_3 \
      --reruns 4 --rubric v1.3 --axes A,B
  ```
  Expectations:
  - 7 shops × 8 probes × 4 reruns = 224 agent runs + 224 judge calls.
  - Wall time 30–60 min @ 4-way target parallelism.
  - Total cost ~$72 (Opus default).
  - `figures/group_comparison.md` shows `coverage_advanced` much closer
    between sandbox and real groups than the v1.2 cohort
    (success criterion: gap < 0.10).
  **Check:** cohort reports written; figures rendered; cost within
  budget.

**M7 acceptance:** cohort signal validates the v1.3 thesis (rubric-shape
bias removed); reports + figures committed under
`outputs/shop_probe/result_v1_3/`.

**Commit:** `shop_probe: cohort run results for v1.3 (M7)`

---

## 6. Verification matrix

| Milestone | Type-check | Unit | Smoke | Cohort |
|---|---|---|---|---|
| M1 schema | ✓ | ✓ schema cases | — | — |
| M2 runner | ✓ | ✓ stub harness | — | — |
| M3 judge | ✓ | ✓ stub Anthropic | — | — |
| M4 dispatch | ✓ | ✓ stub runner | — | — |
| M5 rubric | — | ✓ hash + count + ID set | — | — |
| M6 CLI | ✓ | ✓ flag forwarding | — | — |
| M7 smoke + cohort | — | — | ✓ 1 shop | ✓ 7 shops |

End-to-end:

1. `cd packages/shop_arena && uv run pytest tests/agent/ tests/shop_probe/test_rubric_v1_3.py tests/shop_probe/test_cli_agent_flags.py -v`
2. `cd packages/shop_arena && uv run pyright src/shop_probe/agent/ src/shop_probe/probes/_runner.py src/shop_probe/cli.py src/shop_probe/rubric/schema.py`
3. M7 smoke + cohort.

## 7. Out of scope

- **No deterministic-vs-agent comparison runs.** v1.2.yaml stays on disk
  for archival; v1.3 does not invoke it.
- **No agent-driven core/modern tier.** Presence probes work; the agent
  layer is reserved for behavioural tasks.
- **No new browser tool stack.** The agent uses the existing
  `playwright-browser` skill auto-loaded by `claude_code` and `pi`.
- **No cost gating.** Per-probe cost recorded, never enforced.
- **No backfill of v1.3 results onto v1.2 reports.** Separate measurement
  instruments; comparison is at the report level only.
- **No follow-up flake mitigation** (e.g., judge-twice-and-agree). Defer
  until M7 cohort surfaces a real flake rate.

---

## Appendix A — Harness prompt templates

`agent/runner.py` constructs harness prompts inline. Sketch (final wording
in T2.1):

```
PLANNER_TEMPLATE = """\
You are an autonomous shopping agent on the storefront at {url}.
Your task: {goal}

Use the playwright-browser skill to navigate and interact. Plan up to {step_budget}
steps. Persist screenshots and trajectory under the harness run_dir
(relative paths only — do NOT use ARTIFACT_DIR or /var/folders).
Stop when the task is complete.
"""

EXECUTOR_TEMPLATE = """\
Continue working toward: {goal}

Use the playwright-browser skill. Take a screenshot before exiting so the
judge can verify the after-state.
"""
```

Project-level skill conventions (per CLAUDE.md):
- **Always save artifacts to relative paths under the harness `run_dir`.**
- **Never use `ARTIFACT_DIR` or `/var/folders/`** — wrapper denies these.
- **Use built-in skill commands**, not `run-code` against internal
  Playwright objects.

## Appendix B — The 8 v1.3 agent-driven rubric entries

YAML appended to `v1.3.yaml` after the 66 v1.1 entries. IDs / categories /
weights match v1.2 advanced verbatim — slots stable for cross-version
comparison.

```yaml
- id: collection.sort.changes_order
  category: collection
  level: agent_driven
  weight: 2
  description: Agent-driven — completes a sort task; judge verifies order changed.
  authenticated: false
  transactional: false
  agent_task:
    goal: |
      On the collection page, change the product list ordering by selecting
      a different sort option than the current default.
    judge_prompt: |
      Compare the BEFORE and AFTER screenshots. Did the product ordering
      visibly change? Look at the first ~3 product cards.
    precondition_url_attr: sample_collection_url

- id: collection.filters.applies_to_results
  category: collection
  level: agent_driven
  weight: 2
  description: Agent-driven — applies a filter; judge verifies result set narrowed.
  authenticated: false
  transactional: false
  agent_task:
    goal: |
      Apply any one filter on the collection page that narrows the visible
      product list.
    judge_prompt: |
      Compare BEFORE and AFTER. Did the visible product set narrow? Look
      at product card count or membership.
    precondition_url_attr: sample_collection_url

- id: collection.pagination.advances
  category: collection
  level: agent_driven
  weight: 1
  description: Agent-driven — advances past page 1; judge verifies new products visible.
  authenticated: false
  transactional: false
  agent_task:
    goal: |
      Advance the product list past the first page (next page, load-more,
      or scroll-pagination — whichever the storefront provides).
    judge_prompt: |
      Are different products visible in AFTER than in BEFORE?
    precondition_url_attr: sample_collection_url

- id: collection.filters.url_state_advances
  category: collection
  level: agent_driven
  weight: 2
  description: Agent-driven — applies a filter; judge verifies URL records the filter state.
  authenticated: false
  transactional: false
  agent_task:
    goal: |
      Apply any one filter on the collection page and confirm the page URL
      updates to record the filter state.
    judge_prompt: |
      Compare BEFORE and AFTER URLs visible in the screenshots / trajectory.
      Did the URL gain query parameters or path segments encoding the
      filter?
    precondition_url_attr: sample_collection_url

- id: product.variant.swap_updates_state
  category: product
  level: agent_driven
  weight: 2
  description: Agent-driven — swaps variant; judge verifies price or gallery updated.
  authenticated: false
  transactional: false
  agent_task:
    goal: |
      On the product page, select a different product variant (color, size,
      style — whichever the page exposes).
    judge_prompt: |
      Did the price text or main gallery image change between BEFORE and
      AFTER?
    precondition_url_attr: sample_product_url

- id: product.qty.spinner_increments
  category: product
  level: agent_driven
  weight: 1
  description: Agent-driven — increments quantity to ≥2; judge verifies value increased.
  authenticated: false
  transactional: false
  agent_task:
    goal: |
      Increase the purchase quantity for this product to at least 2.
    judge_prompt: |
      Did the quantity input value visibly increase between BEFORE and
      AFTER?
    precondition_url_attr: sample_product_url

- id: search.predictive.populates_listbox
  category: search
  level: agent_driven
  weight: 2
  description: Agent-driven — types into header search; judge verifies predictive results visible.
  authenticated: false
  transactional: false
  agent_task:
    goal: |
      Type a 3-character query into the header search field and observe the
      predictive results UI.
    judge_prompt: |
      Does the AFTER screenshot show predictive search results visible
      below or near the search input?
    precondition_url_attr: base_url

- id: dynamics.cart_count_badge_updates
  category: dynamics
  level: agent_driven
  weight: 2
  description: Agent-driven — adds to cart, returns home; judge verifies cart badge incremented.
  authenticated: false
  transactional: false
  agent_task:
    goal: |
      Add this product to the cart and then return to the homepage.
    judge_prompt: |
      Does the header cart count or cart badge in AFTER show a higher
      count than BEFORE?
    precondition_url_attr: sample_product_url
```

Total weight: 14 (collection 7 + product 3 + search 2 + dynamics 2),
identical to v1.2 advanced.

## Appendix C — Cost / latency budget (defaults)

| Unit | Cost | Latency |
|---|---|---|
| One agent task run (~10 turns × $0.025/turn, Opus) | $0.25 | 60–120 s |
| One judge call (Opus, 2 images) | $0.01 | ~3 s |
| One probe (1 task + 1 judge) | $0.26 | ~120 s |
| Full cohort (7 × 8 × 4 = 224 probes) | ~$72 | 30–60 min @ 4-way parallel |

Sonnet 4.6 cuts ~5×. v1.1 cohort is unaffected (zero Anthropic calls).

## Appendix D — Risks / open questions

- **Harness pricing field**: confirm the cost-aggregation field name on
  `harness.PlanExecResult` (or equivalent) when wiring T2.1 / T6.2.
  `shop_probe/judge/agent.py` already consumes it — copy the field name
  verbatim.
- **`pi` runtime smoke**: project-level `playwright-browser` skill is on
  disk for both runtimes per CLAUDE.md, but the `pi` subprocess inherits
  the skill via the shell environment. T7.1 should run one task with
  `--agent-runtime pi` to confirm before defaulting cohort to
  `claude_code`.
- **Judge flake on borderline cases**: vision Opus may flip on close
  decisions (e.g., qty spinner that visually changes by 1 px). M7 cohort
  with `--reruns 4` surfaces the rate. If >5%, follow-up: chain-of-thought
  judge prompt or judge-twice-and-agree. Out of scope for this batch.
- **Anthropic rate limits**: 224 probes × (1 agent + 1 judge) =
  448 API calls within ~30 min at 4-way parallelism. Within standard
  Tier-3 quota; verify before scaling parallelism beyond 4-way.
