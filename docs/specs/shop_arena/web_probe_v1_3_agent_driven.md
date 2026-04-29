# `web_probe` v1.3 — agent-driven `advanced` tier

Status: **Draft (proposed)** · Applies to: `docs/specs/shop_arena/web_probe.md` v0.1
Owners: ShopGym
Last updated: **2026-04-29**
Implementation plan: [`docs/impl/web_probe_v1_3_agent_driven_implementation.md`](../../impl/web_probe_v1_3_agent_driven_implementation.md)

## Overview

The v1.2 `advanced` tier (8 deterministic Playwright probes; spec
[`web_probe_v1_2_advanced.md`](web_probe_v1_2_advanced.md)) was designed to
verify that primitives advertised by `core` / `modern` actually fire — sort
re-orders, filters narrow, variants update price, etc. In practice the
probes' selector unions ended up biased toward Hydrogen DOMs: the 7-shop
cohort run on 2026-04-29 (`outputs/shop_probe/result_v1_2/figures/`) shows
sandbox group beating real group **0.238 vs 0.028** on `coverage_advanced`,
while presence-only `coverage_core` / `coverage_modern` track within
~0.05 across the same shops. The signal is not "sandboxes behave better";
it is "sandboxes happen to match the assertion shape."

This spec defines `rubric/v1.3.yaml`, an **agent-driven** replacement for
those 8 advanced entries. v1.3 keeps the 66 v1.1 presence probes verbatim
and swaps the 8 advanced entries for `level: agent_driven` rows whose
`agent_task` block drives an LLM agent through the existing
`playwright-browser` skill and an LLM judge over before/after screenshots.
The agent picks the surface (sort `<select>` vs custom popover, ?, ?), so
the rubric stops asserting DOM shape on behalf of behavior — and the
sandbox-vs-real gap stops being a function of theme provenance.

## Terminology

- **Presence probe** — DOM-presence assertion. v1 + v1.1 are presence-only
  with two exceptions (cart line-item flow, `/cart.js` HTTP fetch). See
  [`web_probe_v1_2_advanced.md`](web_probe_v1_2_advanced.md) §Terminology.
- **Behavioral probe (deterministic)** — Playwright coroutine that drives
  one interaction and asserts on a known selector union. v1.2's 8 advanced
  entries are this shape.
- **Agent-driven probe** — rubric entry with `level: agent_driven` whose
  inline `agent_task` block drives an autonomous agent + a vision judge
  instead of a Python probe coroutine. The agent decides which surface to
  click; the judge decides whether the page changed in the way the entry
  asks about.
- **Inline `agent_task` block** — Pydantic `AgentTaskInline` model attached
  to each agent-driven entry. Carries `goal: str`, `judge_prompt: str`,
  `precondition_url_attr: Literal["base_url", "sample_collection_url",
  "sample_product_url"]`, plus optional per-task `step_budget: int |
  None` ∈ [1, 50] and `timeout_s: int | None` ∈ [10, 600] overrides.
- **Generic runner** — `agent/runner.py:run_agent_task(page, ctx, task)`.
  One coroutine handles every `level: agent_driven` entry. There is no
  per-task wrapper coroutine and no `AGENT_TASKS` registry: adding a 9th
  agent-driven probe is a single YAML edit.
- **Completion judge** — `agent/judge.py:run_completion_judge(...)`.
  Anthropic Messages-API call with two image content blocks (BEFORE and
  AFTER) plus a compact text projection of the harness trajectory and
  the inline `judge_prompt`. Returns a frozen `JudgeVerdict(passed: bool,
  reasoning: str, cost_usd: float, model_id: str)`.
- **`level: advanced`** — retired tier name in v1.3. v1.2.yaml stays on
  disk for archival; v1.3 routes its 8 behavioral slots through the new
  `agent_driven` level instead. v1.3 has no entries with `level:
  advanced`.
- **`passed=None` / not-applicable** — `ProbeOutcome.passed` continues to
  carry `True | False | None`. For agent-driven probes, the runner emits
  `None` when the precondition URL is missing (e.g.
  `precondition_url_attr=sample_product_url` with `ctx.sample_product_url
  is None`); the judge itself returns only `True` / `False`.

## Current Status

Implemented surface as of v1.2 (`outputs/shop_probe/result_v1_2/`):

```
v1   (61 probes) — core + modern, presence-only
v1.1 (66 probes) — v1 + 5 auth/checkout entries (account.*, checkout.*)
v1.2 (74 probes) — v1.1 + 8 deterministic advanced probes
                   ↳ rubric-shape bias: sandbox 0.238 vs real 0.028 on
                     coverage_advanced; coverage_core / coverage_modern
                     track within ~0.05 across the same 7 shops
```

Underlying machinery already in place — v1.3 reuses all of it:

- **`harness.run_plan_exec_loop`** + `harness.runtimes.{claude_code, pi}`
  are production-ready and configured for `claude-opus-4-7`. ShopProbe's
  Turing-test classifier (`shop_probe/judge/agent.py:103-202`) is the
  reference template for "give the agent a task, run harness, project
  trajectory, persist artifact" and is reused verbatim by v1.3 with a
  different post-condition (the completion judge instead of a real-vs-
  sandbox classifier).
- **`playwright-browser` skill** is auto-loaded by both `claude_code` and
  `pi` runtimes per project CLAUDE.md.
- **Rubric loader / schema / report** (`rubric/{loader.py, schema.py}`,
  `report.py`, `probes/_runner.py`) already supports adding a new rubric
  file alongside existing ones; the loader picks rubrics by filename.

Schema gaps that block v1.3:

- `RubricLevel = Literal["core", "modern", "advanced"]` does not yet admit
  `"agent_driven"`.
- `RubricEntry.probe: str` is required, leaving no slot for inline
  agent-task config.
- `ProbeContext` carries no agent-runtime config (model, runtime,
  step/timeout budget, judge model).
- `ProbeResult` / `ProbeReport` carry no per-probe agent / judge cost.

## Desired Status

After v1.3:

```
v1   (61 probes)  ─── unchanged
v1.1 (66 probes)  ─── unchanged
v1.2 (74 probes)  ─── archival; reports remain reproducible
v1.3 (74 probes)  ─── 66 v1.1 verbatim + 8 agent_driven entries
                      ↳ same probe IDs / categories / weights as v1.2
                        advanced; total agent_driven weight = 14
```

Per-probe behavior:

- The runner resolves the entry's `precondition_url_attr` against
  `ProbeContext`, navigates the page, captures a `before-agent`
  screenshot, then runs `harness.run_plan_exec_loop` with the inline
  `goal` as planner / executor prompt input. The harness loop persists
  its trajectory under `<evidence_dir>/<probe_id>/harness/`.
- After the harness loop, the runner pulls the last `ScreenshotStep`
  from the trajectory as the `after-agent` shot (falling back to
  `before` if the agent emitted none) and calls
  `run_completion_judge(before, after, projected_trajectory,
  judge_prompt)`.
- `ProbeOutcome.passed` is the judge verdict;
  `ProbeOutcome.notes` is the judge's reasoning when failing;
  `ProbeOutcome.evidence` is `(before_shot, after_shot, run_dir)`;
  `ProbeOutcome.extra` carries `judge_cost_usd` + `judge_model` (the
  agent run's own cost is recorded by the runner from
  `harness.PlanExecResult`).

Reporting:

- `ProbeResult` gains optional `judge_cost_usd`, `judge_model`,
  `agent_cost_usd`, `agent_model`. `ProbeReport` aggregates totals
  (`total_judge_cost_usd`, `total_agent_cost_usd`).
- `coverage_agent_driven` replaces `coverage_advanced` as the new axis;
  v1.1 reports remain reproducible against their own rubric.

CLI / runtime:

- `--rubric v1.3` runs the new tier end-to-end. Five new flags expose
  agent + judge knobs (defaults match `AgentRuntimeConfig`):
  `--agent-runtime`, `--agent-model`, `--agent-step-budget`,
  `--agent-timeout-s`, `--agent-judge-model`.
- v1.1 cohorts incur **zero** Anthropic calls — the agent path is
  reachable only via `agent_driven` entries.

Cost / latency budget (defaults, per Appendix C of the impl plan):

| Unit | Cost | Latency |
|---|---|---|
| One agent task run (~10 turns, Opus) | $0.25 | 60–120 s |
| One judge call (Opus, 2 images) | $0.01 | ~3 s |
| One probe (1 task + 1 judge) | $0.26 | ~120 s |
| Full cohort (7 × 8 × 4 = 224 probes) | ~$72 | 30–60 min @ 4-way parallel |

Sonnet 4.6 cuts the cohort to ~$15 via `--agent-model
claude-sonnet-4-6`. v1.1 cohorts pay $0.

Success criterion for the M7 cohort: the sandbox-vs-real gap on
`coverage_agent_driven` is **< 0.10** (vs the 0.21 gap v1.2 advanced
showed on the same 7 shops).

## Proposal

### 1. Rubric file

New file `packages/shop_arena/src/shop_probe/rubric/v1.3.yaml`:

- Verbatim copy of v1.1's 66 entries (preserving order and hashes per
  entry).
- 8 new entries appended, all `level: agent_driven`, all
  `authenticated: false`, all `transactional: false`, no `probe:` field;
  each carries a fully populated `agent_task:` block.
- `version: v1.3` in the header.
- Content-addressable: SHA-256 of raw bytes pinned in
  `tests/shop_probe/test_rubric_v1_3.py`.
- IDs / categories / weights identical to v1.2 advanced — slots stable
  for cross-version comparison: `collection.*` ×4 (weight 7),
  `product.*` ×2 (weight 3), `search.*` ×1 (weight 2),
  `dynamics.*` ×1 (weight 2). Total agent-driven weight: **14**.

The 8 entries (full YAML in
[`docs/impl/web_probe_v1_3_agent_driven_implementation.md`](../../impl/web_probe_v1_3_agent_driven_implementation.md)
Appendix B):

| id | category | weight | precondition_url_attr |
|---|---|---|---|
| `collection.sort.changes_order` | collection | 2 | `sample_collection_url` |
| `collection.filters.applies_to_results` | collection | 2 | `sample_collection_url` |
| `collection.pagination.advances` | collection | 1 | `sample_collection_url` |
| `collection.filters.url_state_advances` | collection | 2 | `sample_collection_url` |
| `product.variant.swap_updates_state` | product | 2 | `sample_product_url` |
| `product.qty.spinner_increments` | product | 1 | `sample_product_url` |
| `search.predictive.populates_listbox` | search | 2 | `base_url` |
| `dynamics.cart_count_badge_updates` | dynamics | 2 | `sample_product_url` |

### 2. Schema additions

`packages/shop_arena/src/shop_probe/rubric/schema.py`:

- Extend `RubricLevel` literal with `"agent_driven"`.
- New Pydantic model `AgentTaskInline` (frozen) with the four fields
  defined under *Inline `agent_task` block* in §Terminology.
- Make `RubricEntry.probe: str | None = None` (was required).
- Add `RubricEntry.agent_task: AgentTaskInline | None = None`.
- `model_validator(mode="after")` enforces:
  - exactly one of `{probe, agent_task}` is set per entry, and
  - `agent_task` is set iff `level == "agent_driven"`.

### 3. Generic runner + completion judge

New `packages/shop_arena/src/shop_probe/agent/` module:

- `config.py` — frozen `AgentRuntimeConfig` (runtime / model /
  step_budget / timeout_s / judge_model) carried on `ProbeContext`.
- `runner.py:run_agent_task(page, ctx, task) -> ProbeOutcome` — the
  generic runner. Resolves `start_url` from `task.precondition_url_attr`,
  captures BEFORE, builds harness `PlanExecConfig` (`run_dir =
  ctx.evidence_dir / probe_id / "harness"`, prompts inlined from
  `task.goal`), runs the harness loop, picks AFTER from the last
  `ScreenshotStep`, calls the completion judge, returns a `ProbeOutcome`
  with verdict + cost extras.
- `judge.py:run_completion_judge(before, after, trajectory_text,
  judge_prompt, *, model, client) -> JudgeVerdict` — single Messages-API
  request with two base64 image blocks (labelled BEFORE / AFTER), the
  trajectory text, the entry's `judge_prompt`, and a closing instruction
  asking for `{"passed": bool, "reasoning": str}`. Cost computation
  mirrors `shop_probe/judge/run.py:35-99` (`usage.input_tokens`,
  `usage.output_tokens` → per-model rate table). Tolerates malformed
  JSON via a `passed:\s*(true|false)` string-match fallback.

### 4. Dispatcher

`packages/shop_arena/src/shop_probe/probes/_runner.py:_run_one`:

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

Module-level `DEFAULT_AGENT_TIMEOUT_S = 180`, `AGENT_BUFFER_S = 30`.
Deterministic entries keep the existing `DEFAULT_PROBE_TIMEOUT_S = 10`
outer wait — agent-driven probes need their own scale.

### 5. CLI flags + report schema

Five new flags on both `run` and `eval`, defaults matching
`AgentRuntimeConfig`:

```
--agent-runtime [claude_code|pi]   default claude_code
--agent-model TEXT                 default claude-opus-4-7
--agent-step-budget INTEGER        default 15
--agent-timeout-s INTEGER          default 180
--agent-judge-model TEXT           default claude-opus-4-7
```

`eval` forwards all five into spawned `run` invocations.
`ProbeResult` gains the four optional cost / model fields named under
*Reporting* in §Desired Status; `ProbeReport` aggregates totals.

### 6. Failure modes the design defends against

- **Selector-shape bias** (the v1.2 motivator). The agent picks the
  surface; the rubric never asserts on DOM selectors for agent-driven
  entries. Real-shop themes with quirky sort UIs (anchor lists, custom
  popovers) are now first-class.
- **Insufficient sample data** (e.g. `sample_product_url` missing). The
  runner returns `passed=None` with a structured note before invoking
  the harness or the judge — same convention as deterministic v1.2.
- **Judge flake on borderline cases**. Vision Opus may flip on close
  decisions (a qty spinner that visually changes by 1 px). The M7
  cohort uses `--reruns 4` to surface the rate; >5% flake is a
  follow-up trigger (chain-of-thought judge prompt or
  judge-twice-and-agree). Out of scope for v1.3.
- **Outer-timeout starvation**. The dispatcher uses a wider
  `DEFAULT_AGENT_TIMEOUT_S = 180` + 30s buffer so the outer
  `asyncio.wait_for` never preempts the harness loop's own timeout.
- **Unbounded cost**. Per-probe cost is recorded in `ProbeOutcome.extra`
  and aggregated in `ProbeReport`; no enforcement, but cost is
  observable in every report and v1.1 cohorts pay $0.

## Alternative

**Per-task wrapper coroutines** — a `probes/agent_tasks.py` module with
one coroutine per agent-driven entry (`async def
sort_changes_order_agent(page, ctx) -> ProbeOutcome:` …) and an
`AGENT_TASKS` dict. Rejected: every entry would duplicate the same
boilerplate (resolve precondition, capture BEFORE, configure harness,
project trajectory, call judge, build outcome). Adding a 9th task would
require a YAML edit *and* a Python edit. The inline `agent_task` block +
generic runner achieves the same surface area in YAML alone, and keeps
`probes/` reserved for deterministic Playwright assertions.

**Tighten the v1.2 selector unions in place** — rejected for the same
reasons v1.2 rejected upgrading v1 presence probes: it conflates two
fidelity dimensions on one rubric entry, and breaks comparability with
the 28 v1 + 7 v1.2 reports already on disk.

**Run agent + judge inline (no harness)** — bypass `harness` and drive
Playwright directly from a single `Anthropic` chat. Rejected: loses the
verifier hook, the iteration trajectory, and resume support that
`harness.run_plan_exec_loop` already ships; would also re-implement the
plan / exec contract that ShopGuru and ShopExplore both depend on.

## Milestones

| Milestone | Deliverables |
|---|---|
| **M1** | Spec + impl docs land. Schema accepts `level: agent_driven` + inline `agent_task` block; v1.1 / v1.2 rubrics still load. New `agent/` package scaffold (config dataclass + tests dir). Schema validation tests green. |
| **M2** | Generic `run_agent_task(page, ctx, task)` skeleton runs the harness loop and persists trajectory; returns a fixed-true `ProbeOutcome` against stub fixtures. `ProbeContext` carries `agent_config: AgentRuntimeConfig | None`. |
| **M3** | `run_completion_judge` issues the vision Anthropic Messages call against a stubbed `AsyncAnthropic` client and returns a structured `JudgeVerdict`. Runner replaces M2's `passed=True` with the real verdict; trajectory projection helper lands. |
| **M4** | `_run_one` dispatcher routes `level: agent_driven` entries through `run_agent_task` end-to-end inside `ProbeRunner`. Outer timeout uses the wider agent budget. Stub-driven dispatch test green. |
| **M5** | `rubric/v1.3.yaml` written (66 v1.1 entries verbatim + 8 inline `agent_task` blocks). Loader registers `"v1.3"`. `tests/shop_probe/test_rubric_v1_3.py` pins SHA-256, version, total count (74), agent-driven count (8), the 8 canonical IDs, and total agent-driven weight (14). |
| **M6** | CLI flags + report schema. Five `--agent-*` flags on `run` and `eval`; `eval` forwards into spawned `run` invocations. `ProbeResult` / `ProbeReport` gain the cost / model fields. v1.1 cohorts incur zero Anthropic calls. |
| **M7** | Real-world validation. Single-shop smoke (1 sandbox + 1 real, `--reruns 1`) confirms harness artifacts + judge verdicts. Full 7-shop × 4-rerun cohort verifies the success criterion: `coverage_agent_driven` sandbox-vs-real gap < 0.10. Reports + figures committed under `outputs/shop_probe/result_v1_3/`. |

M1–M6 land as six commits on `mz/dev-visual-judge`; M7 is operator-only,
with the cohort outputs committed as the seventh. Detailed task
breakdown lives in
[`docs/impl/web_probe_v1_3_agent_driven_implementation.md`](../../impl/web_probe_v1_3_agent_driven_implementation.md).

## Appendix

### A.1 Reference inline `agent_task` block

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
```

### A.2 Reference dispatch path

```python
# probes/_runner.py:_run_one
if entry.level == "agent_driven":
    assert entry.agent_task is not None
    agent_timeout = (entry.agent_task.timeout_s
                     or DEFAULT_AGENT_TIMEOUT_S) + AGENT_BUFFER_S
    return await asyncio.wait_for(
        run_agent_task(self.page, ctx, task=entry.agent_task),
        timeout=agent_timeout,
    )
# ... existing deterministic dispatch unchanged
```

### A.3 Reference judge response contract

```json
{"passed": true, "reasoning": "First three product cards in AFTER show a different order from BEFORE — top card changed from 'Atlas Tee' to 'Zenith Tee'."}
```

Malformed responses fall back to `passed:\s*(true|false)` string-match;
fallback path stamps a note onto `verdict.reasoning` so the report
reader can audit the failure mode.

### A.4 Out of scope

- **No deterministic-vs-agent comparison runs.** `v1.2.yaml` stays on
  disk for archival; v1.3 does not invoke it. v1.3 vs v1.3 is the new
  comparison axis.
- **No agent-driven core / modern tier.** Presence probes work; the
  agent layer is reserved for behavioural tasks.
- **No new browser tool stack.** The agent uses the existing
  `playwright-browser` skill auto-loaded by `claude_code` and `pi`.
- **No cost gating.** Per-probe cost is recorded, never enforced.
- **No backfill of v1.3 results onto v1.2 reports.** Separate
  measurement instruments; comparison is at the report level only.
- **No follow-up flake mitigation** (e.g. judge-twice-and-agree). Defer
  until M7 cohort surfaces a real flake rate.
