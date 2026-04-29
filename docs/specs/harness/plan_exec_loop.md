# Plan + Exec Harness (`packages/harness`)

Status: **Implemented** · Version: **0.1**
Owners: ShopGym

> A self-contained, runtime-agnostic engine for orchestrating LLM agents
> through a plan-then-loop flow. Owns process lifecycle, a workspace
> state machine, and normalized telemetry. Owns no prompts, no tools,
> no domain knowledge.

---

## 1. Overview

Many agentic pipelines have the same shape: a planner writes a task
list, a loop spawns a fresh agent per task. `packages/harness` ships
this pattern once.

Two design choices define the harness:

- **Fresh subprocess per iteration.** No long-lived orchestrator LLM.
  The Python loop selects the next task and enforces the workspace state
  machine; each agent performs one bounded planner or executor job.
- **Filesystem-as-memory.** Every iteration starts with zero context
  and reads its memory from a small, fixed set of files under `run_dir/`.

The harness is initially used by `shop_arena.explore` and `shop_arena.gen` but is
coupled to neither. Its tests run against arbitrary toy tasks.

---

## 2. Terminology

- **Run** — one invocation of `run_plan_exec_loop`, scoped to one `run_dir`.
- **Iteration** — one subprocess invocation of an agent within a run.
  Each iteration gets a fresh LLM context. *Not* to be confused with an
  "LLM turn" (one user/assistant exchange); a single iteration may
  contain many LLM turns internally, all hidden inside the subprocess.
- **AgentRuntime** — the adapter that runs one iteration under a concrete
  agent system (Claude Code CLI, `pi` CLI, plus a `replay` runtime for
  tests — see §5.6) and emits a normalized
  trajectory.
- **Anchor files** — the two files every agent reads at the start of
  every iteration: `AGENTS.md` (rules) and `plan.md` (state). The
  artifact directory is *available* — agents read it on demand — but
  it is not an anchor.
- **Executor self-check** — prompt-guided quality check performed by the
  executor before it marks its selected task `[x]` or `[!]`. This is not
  an independent grading phase.
- **Protocol check** — deterministic harness-side validation run after an
  executor iteration. It checks state-machine invariants and task
  attribution, not domain quality.

---

## 3. Current Status

- `packages/harness` is implemented and published in the repo workspace.
  The package exposes `run_plan_exec_loop`, `PlanExecLoopConfig`,
  `Prompts`, `PlanExecLoopResult`, `get_runtime`, runtime adapters for
  `pi`, Claude Code, and replay, and normalized trajectory / run-summary
  telemetry.
- The base v0.1 loop is now extended by sibling specs:
  - [`seed_immutability.md`](seed_immutability.md) adds the persisted
    seed manifest and post-iteration seed checks.
  - [`resume.md`](resume.md) adds `Workspace.open`, planner-skip resume,
    partial-iteration quarantine, and `resume_history`.
  - [`verifiers.md`](verifiers.md) adds caller-owned verifier dispatch
    and `{{verifier_feedback}}`.
  - [`protocol_violation_recovery.md`](protocol_violation_recovery.md)
    adds executor-phase BLOCKED-and-continue recovery.
- The current Python implementation remains the shipping harness. The
  proposed TypeScript vNext contract is tracked separately in
  [`plan_exec_loop_vnext.md`](plan_exec_loop_vnext.md).

---

## 4. Desired Status

A single self-contained package, `packages/harness`, that runs a
plan-then-loop flow from a config + prompt bundle, supports swappable
runtimes, and emits a normalized trajectory per iteration.

### 4.1 I/O contract

**Inputs** (from caller):

| Input               | Notes                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| `run_dir`           | Empty or non-existent path; harness owns it once the run starts.      |
| `prompts`           | `planner` (required), `execute` (required). Strings; no templating.   |
| `AGENTS.md`         | Caller's project constitution. Stable for the run.                    |
| `runtime`           | An `AgentRuntime` instance, obtained via `get_runtime(name)`.         |
| `config`            | Loop budget: `max_iters`, `timeout`.                                  |
| `artifact_seed_dir` | Optional external directory copied into `run_dir/artifact/` at start. |

**Outputs**:

- A populated `run_dir` matching the layout in §5.3.
- A `PlanExecLoopResult` return value (final status, iter counts, trajectory paths).
- `run.json` on disk: the reproducibility record.

**Out of scope:** prompt quality, tool configuration, artifact validation.

### 4.2 Success criteria

- **SC1 — Self-contained.** Test suite runs with no dependency on other packages in this repo.
- **SC2 — Runtime-swappable.** The same toy task runs under `ClaudeCodeRuntime` and `PiRuntime` with only the runtime name changing. Tests use the deterministic `replay` runtime.
- **SC3 — Workspace-replayable.** A validator reconstructs `PlanExecLoopResult` from `run_dir` alone.

---

## 5. Proposal

### 5.1 Architecture

```
        ┌───────────────────────────────────────────────────┐
        │                     Caller                        │
        │   prompts · AGENTS.md · runtime name · config     │
        └───────────────────────┬───────────────────────────┘
                                │
                                ▼
        ┌───────────────────────────────────────────────────┐
        │                Harness  (Python)                  │
        │                                                   │
        │   plan() → execute()*                             │
        │                                                   │
        │   • parses plan.md, enforces state machine        │
        │   • normalizes telemetry                          │
        │   • atomically rewrites run.json                  │
        └────────┬─────────────────────────────┬────────────┘
                 │ invokes per iteration       │ owns
                 ▼                             ▼
        ┌──────────────────────┐   ┌────────────────────────┐
        │    AgentRuntime      │   │ Workspace  (run_dir/)  │
        │  claude_code · pi    │   │                        │
        │  · replay (tests)    │   │ AGENTS.md     stable   │
        │                      │   │ prompts/      stable   │
        │  spawns subprocess;  │   │ plan.md       evolving │
        │  converts native     │   │ artifact/     evolving │
        │  log → Trajectory    │   │ iters/<id>/   append   │
        └──────────┬───────────┘   │ run.json      rewrite  │
                   │ spawns        └──────────┬─────────────┘
                   ▼                          │ reads/writes
        ┌──────────────────────┐              │
        │  Agent subprocess    │ ◄────────────┘
        │  (one iteration =    │
        │   N internal LLM     │   anchors:   AGENTS.md, plan.md
        │   turns, then exit)  │   workspace: artifact/
        └──────────────────────┘
```

The harness writes stable files before the run, append-only telemetry
under `iters/`, and the derived `run.json` summary. Planner and executor
agents may write `plan.md` and `artifact/` during their subprocess
invocation. Between invocations, the harness may normalize `plan.md` to
enforce the state machine. The runtime is a thin adapter: spawn, collect
output, normalize.

### 5.2 Execution model

A run has one required planner iteration followed by zero or more
executor iterations. Between iterations, Python runs; during an
iteration, Python is blocked and the agent subprocess has exclusive
control of the mutable workspace.

```
plan()  # records telemetry under iters/plan/
while exec_iter < max_iters and PENDING tasks remain:
    select highest-priority PENDING task
    execute(selected_task_id)  # records telemetry under iters/exec-000n/
    run deterministic protocol checks
```

`max_iters` counts executor iterations only. The planner is outside that
budget and must produce a parseable `plan.md` with at least one task
unless the caller's prompt intentionally defines an empty run. v0.1 has no
independent verifier phase; executors are expected to self-check before
marking tasks terminal.

### 5.3 Workspace layout

The harness owns this layout. Callers pass `run_dir`; the harness creates
and populates the workspace.

```
<run_dir>/
├── AGENTS.md                 # stable; caller constitution
├── prompts/                  # stable; harness writes caller-provided prompts
├── artifact/                 # evolving; caller-defined deliverables
├── plan.md                   # evolving; the task list (§5.4)
├── iters/                    # append-only telemetry per iteration
│   ├── plan/
│   │   ├── metadata.json
│   │   ├── plan.before.md
│   │   ├── plan.after.md
│   │   ├── trajectory.json
│   │   ├── native.log
│   │   └── screenshots/
│   └── exec-0001/
│       ├── metadata.json
│       ├── plan.before.md
│       ├── plan.after.md
│       ├── trajectory.json
│       ├── native.log
│       ├── screenshots/
│       └── checks/
│           └── protocol.json
└── run.json                  # atomically rewritten run summary
```

`AGENTS.md` is uppercase by community convention. The Claude Code
runtime adapter symlinks `CLAUDE.md → AGENTS.md` inside `run_dir` at
spawn time so its auto-load works.

### 5.4 Memory model

| Tier            | Writer                                      | Mutability                          |
| --------------- | ------------------------------------------- | ----------------------------------- |
| **Stable**      | Harness, from caller inputs                 | Immutable during a run              |
| **Evolving**    | Agents during iterations; harness between   | Edited under state machine          |
| **Append-only** | Harness                                     | Per-iteration files never rewritten |

Every iteration reads two anchors in order: `AGENTS.md`, then
`plan.md`. The `artifact/` directory is the working area: agents
have full access and decide what to read or write. Memory is
per-run; `plan.md` starts empty each run.
Callers do not write inside `run_dir` after the run starts. If initial
artifacts are needed, the caller passes `artifact_seed_dir`; the harness
copies it into `run_dir/artifact/` before `plan()`. The seeded subtree is
treated as stable for the duration of the run and is enforced by a
deterministic post-iteration check — see
[seed_immutability.md](seed_immutability.md).

### 5.5 Plan file protocol (`plan.md`)

`plan.md` is GFM markdown. The harness parses one section, **Tasks**.
Other sections (e.g. a "Last action" handoff note) are prompt-guided,
not parser-enforced; they live in the `AGENTS.md` template, not here.

```md
# Plan

## Tasks
- [x] homepage — covered hero, nav, footer
- [~] product_detail   [priority: 3]
- [ ] collection       [priority: 2]
- [!] checkout — auth wall, cannot complete
```

**Parser invariants for Tasks** (enforced):

1. Each task is a top-level GFM checkbox item.
2. First token after the checkbox is the task `id`, matching `[a-z0-9_]+`, unique.
3. Status is the marker: `[ ]` PENDING, `[~]` IN_PROGRESS, `[x]` DONE, `[!]` BLOCKED.
4. `[x]` is terminal; an id cannot be re-opened.
5. Priority is optional (`[priority: N]`), default 0, higher wins.

**Planner contract:**

- Write a parseable `plan.md` with a `## Tasks` section.
- Create PENDING tasks; do not mark initial work DONE unless the caller's
  planner prompt explicitly defines that behavior.

**Executor contract per iteration:**

- Work only on the `selected_task_id` chosen by the harness. The harness
  selects the highest-priority PENDING task and passes it in a small
  control header before the caller-provided execute prompt.
- Flip the selected task to `[~]` before working.
- Self-check the result before exiting.
- Flip the selected task to `[x]` or `[!]` before exiting.
- May add new PENDING items. May not complete or block unrelated tasks.
- May not resurrect `[x]` ids.

**Harness contract between iterations:**

1. Parse the raw `plan.md` snapshot.
2. Select the highest-priority PENDING task for the next executor iteration.
3. Save `plan.before.md` before spawning the executor and `plan.after.md` after it exits.
4. Derive task attribution metadata: `selected_task_id`, `completed_task_ids`, `blocked_task_ids`, and `added_task_ids`.
5. Abort `invalid_plan` on duplicate ids or resurrected `[x]` ids.
6. Abort `protocol_violation` if an executor marks any task other than the selected task terminal.
7. Write per-iteration telemetry and rewrite `run.json` atomically.

### 5.6 Agent runtime abstraction

Every runtime implements one contract:

- given a rendered prompt, the `run_dir` as working directory, and a timeout,
- run one iteration synchronously,
- and produce: a native log, a normalized `Trajectory`, and any screenshots.

The runtime owns: which LLM, API keys, tool selection, in-iteration
context management (including any internal LLM-turn loop). The
harness owns: iteration lifecycle, timeout, telemetry normalization,
plan parsing, workspace layout.

v1 ships two production runtimes: `claude_code` and `pi`. Selected
by name via a small registry.

**Replay runtime (tests).** A third runtime, `replay`, implements the
same protocol but does not call any LLM. Given an iteration id (`plan`,
`exec-0001`, ...), it reads a cassette under
`tests/cassettes/<scenario>/<iter_id>/`, copies the recorded
`workspace_after/` overlay into `run_dir`, and emits the recorded
trajectory. v0.1 uses full overlays only — no patch or diff cassette
format.

Minimal cassette shape:

```
tests/cassettes/<scenario>/<iter_id>/
├── trajectory.json
├── native.log
└── workspace_after/
    ├── plan.md
    └── artifact/
```

Cassettes are produced by running a real CLI runtime once with
`HARNESS_RECORD=1` and committed to the repo. e2e tests use `replay` by
default — deterministic, no API keys, no flake. Re-record when prompts
or `AGENTS.md` change.

### 5.7 Telemetry

One normalized `Trajectory` per planner or executor iteration at
`iters/<iter_id>/trajectory.json`: `iter_id`, `runtime`, timestamps,
exit code, `prompt_sha256`, and an ordered list of typed steps
(`thought`, `message`, `tool_call`, `tool_result`, `screenshot`,
`error`). Each runtime ships a converter from its native log to this
shape. Trajectory files are immutable once written.

Every iteration directory also contains `metadata.json`,
`plan.before.md`, and `plan.after.md`. Executor metadata includes task
attribution: `selected_task_id`, `completed_task_ids`,
`blocked_task_ids`, and `added_task_ids`. Protocol-check results are
written to `iters/<exec_id>/checks/protocol.json`.

`run.json` aggregates trajectory paths, task-list snapshots, final
result, and the secret-free config snapshot. Rewritten atomically
(temp + rename) after each iteration. If a process crashes mid-run, a
validator reconstructs state from append-only files under `iters/` plus
the current `plan.md`.

### 5.8 Executor self-check, verifiers, and protocol checks

The base v0.1 contract relied on executor self-checking: the executor
was responsible for checking its selected task before marking that task
`[x]` or `[!]`. The shipping package now also includes the additive
verifier extension described in
[`verifiers.md`](verifiers.md): callers may pass `Verifier`
implementations that run after each executor iteration, persist
per-verifier telemetry, rewrite failed tasks to `[~]`, and feed bounded
feedback into the next executor prompt.

The harness may still run deterministic protocol checks after each
executor iteration. These checks enforce the harness contract, for
example:

- `plan.md` remains parseable.
- task ids remain unique.
- `[x]` tasks are not resurrected.
- the selected task is the only task newly marked `[x]` or `[!]`.
- new tasks are PENDING.
- the seeded subtree under `run_dir/artifact/` is unchanged
  ([seed_immutability.md](seed_immutability.md)).

Protocol checks are not domain-quality grading and do not produce
advisory verdicts. They are harness-owned guardrails and write their
result to `iters/<exec_id>/checks/protocol.json`. Domain-specific
quality checks either stay in executor self-check instructions or live
behind caller-owned verifiers.

---

## 6. Alternative

**In-process orchestrator (no subprocess per iteration).** Keep one
long-lived LLM session and rely on context compaction. Rejected:
fresh sub-agents beat compaction for multi-hour runs (Anthropic
harness paper, Ralph practice), and the subprocess model gives clean
trajectory boundaries for free.

---

## 7. Milestones

**M1 — Core primitives.** Types, plan parser, workspace helpers,
telemetry writer. Unit tests cover invariants.

**M2 — Loop + replay runtime.** `run_plan_exec_loop` plus the
`replay` runtime and cassette format. Toy e2e suite (§8.2) passes
under `replay` deterministically in CI without API keys.

**M3 — Real CLI runtimes.** `ClaudeCodeRuntime` and `PiRuntime`.
Cassettes for the toy suite are recorded by running each real CLI
once. Smoke tests gated behind `HARNESS_SMOKE_CLAUDE=1` /
`HARNESS_SMOKE_PI=1` re-run the suite against live binaries to detect
cassette drift.

**M4 — v0.1.0.** Docs, semver tag, CHANGELOG.

---

## 8. Appendix

### 8.1 Public surface (informative)

- **Types**: `Task`, `TaskList`, `TaskStatus`, `Trajectory`, `TrajectoryStep`, `AgentRuntime`, `IterationMetadata`, `ProtocolCheckResult`.
- **Config & result**: `PlanExecLoopConfig` (contains `run_dir`, `prompts`, `agents_md`, `artifact_seed_dir`, and loop budget), `Prompts`, `PlanExecLoopResult`.
- **Entry points**: `run_plan_exec_loop(config, runtime)`, `get_runtime(name, **kwargs)`.

### 8.2 Future directions (non-blocking)

- **Hooks.** OpenClaw-style `before_iter`/`after_iter`/`on_stuck` callbacks for callers to add observability without forking.
- **Independent evaluator phases.** Add isolated evaluator phases for benchmark-grade evaluation, with read-only access to the main workspace and separate telemetry.
- **Long-lived orchestrator mode.** Alternative entry point reusing the runtime protocol, workspace, and trajectory schema.
- **Parallelism.** Shard `plan.md` Tasks by id with per-iteration locks.
- **Remote execution.** Swap `subprocess` for an RPC runtime; same contract.
