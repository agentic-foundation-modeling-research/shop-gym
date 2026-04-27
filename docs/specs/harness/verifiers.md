# Verifier Extension (`packages/harness`)

Status: **Spec (draft)** · Version: **0.1**
Owners: ShopGym

> An additive, opt-in extension to `run_plan_exec_loop` that lets
> callers gate executor `[x]` marks on a list of caller-owned
> **verifiers** (rule-based or LLM-based) and surface verifier
> feedback to the next iteration.

---

## 1. Overview

`packages/harness` v0.1 has no independent verifier phase. The
executor is responsible for self-checking before it marks a task
`[x]` ([plan_exec_loop §5.8](plan_exec_loop.md#58-executor-self-check-and-protocol-checks)).
That works for shallow tasks but fails for any pipeline where:

- the agent cannot easily verify its own work
  (e.g. "did the page render correctly?", "did the build pass?"),
- the verification logic is reusable across iterations
  (so each iteration shouldn't re-implement it), or
- the verification is most reliably a fresh, isolated check
  (a separate process invoking `tsc`, an LLM judge with a clean
  context, etc.).

This spec adds one harness-owned hook — the **verifier dispatch** —
that runs caller-supplied checks after each executor iteration,
records their verdicts, and (on failure) rewrites the task's marker
back to `[~]` while injecting the verifier's feedback into the next
iteration's prompt.

Two design choices define the extension:

- **Caller owns implementations; harness owns dispatch.** Verifier
  classes live in caller code (e.g. `shop_gen.build.verifiers.tsc`).
  The harness defines a protocol, a registry, a per-iteration
  dispatch lifecycle, telemetry, and a prompt-feedback slot. It
  contains zero domain logic.
- **Additive and opt-in.** The default verifier list is empty;
  existing v0.1 callers (`shop_explore`) see no behavior change.
  Verifiers are passed via `PlanExecLoopConfig.verifiers`.

---

## 2. Terminology

- **Verifier** — a caller-provided check, a rule-based deterministic
  function or an LLM-as-judge call. Implements the `Verifier`
  protocol (§5.2). Pure-ish: reads the workspace and emits a verdict
  + optional feedback markdown.
- **Verdict** — one of `PASS`, `FAIL`, `ADVISORY`. `FAIL` blocks the
  selected task's `[x]` mark; `ADVISORY` reports without blocking.
- **Verifier feedback** — markdown the verifier returns alongside
  `FAIL` and (optionally) `ADVISORY`. Rendered into the next
  iteration's prompt under a `{{verifier_feedback}}` slot.
- **Dispatch** — the harness step, run between exec iterations, that
  selects applicable verifiers, runs them, persists verdicts, and
  decides whether to advance.
- **Applicability** — a verifier can scope itself to specific task
  ids, task name patterns, or "all tasks" via `applies_to`.

---

## 3. Current Status

- `packages/harness` v0.1.0 ships `run_plan_exec_loop` with executor
  self-check + harness-owned protocol checks (state-machine /
  seed-immutability). No independent verifier API.
- `plan_exec_loop §8.2` lists "Independent evaluator phases" as a
  future direction; this spec is the v0.1 of that direction, but
  scoped narrowly to **gating** rather than parallel evaluation.
- `shop_gen` (this spec's primary caller) is in design and *requires*
  per-iteration verifiers to gate the build loop. See
  [`shop_gen.md`](../shop_arena/shop_gen.md) §5.5.

---

## 4. Desired Status

A small additive hook on the harness public surface so that callers
can pass a list of verifiers and have them dispatched after every
executor iteration without forking the loop.

### 4.1 I/O contract

**Inputs** (additive on `PlanExecLoopConfig`):

| Input        | Notes                                                                                  |
| ------------ | -------------------------------------------------------------------------------------- |
| `verifiers`  | `list[Verifier]`. Default `[]`. Empty list ⇒ current v0.1 behavior, no dispatch.       |
| `verifier_feedback_max_chars` | Truncation budget for feedback injected into the next prompt. Default 4000.   |

**Outputs** (additive on `PlanExecLoopResult`):

- `verifier_runs: list[VerifierRun]` — flat sequence of every
  verifier invocation across the run, with `iter_id`, `name`,
  `verdict`, `duration_ms`, `path` (telemetry path).

**On disk** (additive under existing `iters/<id>/checks/`):

```
iters/<exec_id>/checks/
├── protocol.json              # existing; harness state-machine checks
└── verifiers/                 # NEW
    ├── <name>.json            # one file per verifier invocation
    └── feedback.md            # NEW; concatenated feedback shown to NEXT iteration
```

`feedback.md` is rewritten only when at least one verifier returned
`FAIL` or `ADVISORY` with feedback content. Otherwise absent.

**Out of scope (v0.1):**

- **Independent evaluator phases** that run on a separate workspace
  copy (still in `plan_exec_loop §8.2` future). Verifiers in this
  spec read the live `run_dir` synchronously between iterations.
- **Parallel verifier execution.** Verifiers run sequentially in
  the order the caller registered them. v0.2 may parallelize.
- **Pre-iteration / pre-plan verifiers.** Verifiers run only after
  executor iterations in v0.1. Planner-iteration verifiers are a
  natural follow-up but not needed by `shop_gen` v0.1.
- **Cross-iteration retry budget.** A verifier failing the same task
  N times does not auto-block the run. The caller's `max_iters`
  budget is the only termination signal in v0.1.

### 4.2 Success criteria

| ID  | Criterion                                                                                                              |
| --- | ---------------------------------------------------------------------------------------------------------------------- |
| SC1 | An empty `verifiers` list produces byte-identical telemetry to v0.1 (backward compatible).                             |
| SC2 | A passing verifier set leaves the executor's `[x]` mark intact and writes per-verifier `iters/<id>/checks/verifiers/<name>.json`. |
| SC3 | A `FAIL` verifier rewrites the selected task `[x]` → `[~]`, writes `feedback.md`, and the next iteration's prompt receives the feedback under `{{verifier_feedback}}`. |
| SC4 | An `ADVISORY` verifier never rewrites the marker but its feedback (if present) appears in `feedback.md` and the next prompt. |
| SC5 | A verifier raising an exception is recorded with verdict `ERROR` and is treated as `ADVISORY` (does not block).        |
| SC6 | The replay runtime cassette format is unchanged; verifier fixtures plug in via a separate `VerifierFixture` mechanism. |

---

## 5. Proposal

### 5.1 Architecture (delta vs. v0.1)

```
        ┌──────────────────────────────────────────────────┐
        │                      Caller                      │
        │   prompts · AGENTS.md · runtime · config         │
        │   verifiers ── NEW (caller-owned classes) ───┐   │
        └──────────────────────────────────────────────┼───┘
                                                       │
                                                       ▼
                          ┌──────────────────────────────────────┐
                          │              Harness                 │
                          │                                      │
                          │   plan() → execute()*                │
                          │              │                       │
                          │              ▼                       │
                          │   ┌───────────────────────────────┐  │
                          │   │ verifier dispatch  (NEW)      │  │
                          │   │  • run applicable verifiers   │  │
                          │   │  • persist verdicts           │  │
                          │   │  • on FAIL: [x]→[~]           │  │
                          │   │  • write feedback.md          │  │
                          │   └───────────────────────────────┘  │
                          └────────┬─────────────────────────────┘
                                   │ (next iteration's prompt
                                   │  gets {{verifier_feedback}})
                                   ▼
                          ┌──────────────────────┐
                          │  Agent subprocess    │
                          └──────────────────────┘
```

The verifier list is owned by the caller; the harness only knows the
`Verifier` protocol and the order of registration.

### 5.2 Verifier protocol

Lives in `harness.verifiers`:

```python
class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ADVISORY = "advisory"
    ERROR = "error"      # set by harness when run() raises

class VerifierResult(BaseModel, frozen=True, extra="forbid"):
    verdict: Verdict
    feedback: str = ""        # markdown; surfaced to next prompt on FAIL/ADVISORY
    details: dict[str, Any] = {}   # caller-defined; persisted verbatim

class VerifierContext(BaseModel, frozen=True, extra="forbid"):
    run_dir: Path             # absolute
    iter_id: str              # e.g. "exec-0003"
    selected_task_id: str
    plan: TaskList            # parsed plan.md after the iteration
    artifact_dir: Path        # run_dir / "artifact"
    runtime: AgentRuntime     # opt-in: callers may invoke the runtime's LLM

class Verifier(Protocol):
    name: str                 # filesystem-safe; unique per registration
    def applies_to(self, task_id: str) -> bool: ...
    def run(self, ctx: VerifierContext) -> VerifierResult: ...
```

`VerifierContext.runtime` is exposed deliberately so LLM-based
verifiers reuse the same model + auth path the harness already drives
its iterations with (mirrors the `LLMCompleter` adapter
`shop_explore` uses for the synthesis call).

### 5.3 Dispatch lifecycle

After each executor iteration's protocol checks complete:

1. Filter verifiers by `applies_to(selected_task_id)`.
2. Run each filtered verifier sequentially. Each gets a fresh
   `VerifierContext`. The harness times the call and catches
   exceptions; an exception → `Verdict.ERROR` with
   `feedback=str(exc)`.
3. Persist `iters/<id>/checks/verifiers/<name>.json` per call.
4. Compute aggregate state:
   - any `FAIL` ⇒ **block**: rewrite the executor's `[x]` or `[!]`
     for `selected_task_id` back to `[~]`.
   - all `PASS`/`ADVISORY`/`ERROR` ⇒ **advance**: leave the marker.
5. If any verifier produced non-empty feedback (`FAIL` or
   `ADVISORY`), concatenate them under per-verifier headers and write
   `iters/<id>/checks/verifiers/feedback.md`.
6. The next iteration's prompt template renders
   `{{verifier_feedback}}` from the **previous iteration's**
   `feedback.md`. If absent, the slot expands to empty.

`ERROR` is intentionally non-blocking: a verifier crash should never
deadlock the loop. The caller sees the error in telemetry and can
decide whether to fix the verifier or escalate it to `FAIL`.

### 5.4 Plan-file interaction

The harness already parses `plan.md` between iterations. Verifier
dispatch reuses that snapshot:

- `[x]` → `[~]`: replace the marker character. Preserve task brief,
  priority, and any other metadata on the line.
- `[!]` → `[~]`: same. The harness treats both terminal states
  identically for the purpose of verifier blocking.
- New tasks added by the executor: untouched. Only the
  `selected_task_id` line is mutated.

`plan.after.md` (the snapshot the harness writes after the iteration)
is captured **before** verifier dispatch, so it reflects the
executor's intent. The post-dispatch state is reflected in `plan.md`
itself and in the next iteration's `plan.before.md`.

### 5.5 Prompt feedback slot

Caller's `execute.md` may include a `{{verifier_feedback}}`
placeholder. The harness renders the slot from the **previous**
iteration's `feedback.md` (or empty string if none). Slot rendering
is the only templating the harness performs; everything else is
passed verbatim per current v0.1 behavior.

```
# in execute.md (caller-authored)

## Previous-iteration feedback
{{verifier_feedback}}
```

Truncation: if the feedback exceeds
`verifier_feedback_max_chars`, it's truncated with a `[...truncated]`
suffix; full content stays on disk.

If the caller's `execute.md` does not include the placeholder, the
feedback is *not* injected — verifier dispatch still gates `[x]`
marks, but the next iteration won't see the feedback prose. This is
intentional: the caller decides whether the agent should see it.

### 5.6 Telemetry shape

Per verifier invocation:

```json
{
  "iter_id": "exec-0003",
  "name": "tsc",
  "task_id": "gen_homepage",
  "verdict": "fail",
  "started_at": "2026-04-26T10:14:00Z",
  "duration_ms": 4220,
  "feedback": "...markdown...",
  "details": {"errors": 3, "first_error": "..."}
}
```

The aggregated `run.json` adds a `verifier_runs` array with summary
rows (no `feedback`/`details` to keep `run.json` small; full bodies
live in the per-verifier files).

### 5.7 Replay-runtime interaction

The replay runtime (used by tests) does not need to know about
verifiers. Verifiers run **after** the runtime exits, against the
real workspace the cassette overlay produced. Tests compose a real
verifier instance with the replay runtime in the same `run_plan_exec_loop`
call.

For a verifier that itself calls an LLM, tests pass a stub `Verifier`
with deterministic outputs — the harness has no opinion about how
the verifier produces its verdict.

### 5.8 Backward compatibility

All additions are non-breaking:

- New `verifiers` field on `PlanExecLoopConfig` defaults to `[]`.
- New `verifier_runs` field on `PlanExecLoopResult` defaults to `[]`.
- New `iters/<id>/checks/verifiers/` directory only exists when
  verifiers ran.
- Existing callers (`shop_explore`) need zero changes.

---

## 6. Alternative

**In-caller wrapper.** Run verifiers from outside the harness by
calling `run_plan_exec_loop` once per iteration in a caller-owned
loop. Tempting because no harness change is needed.

Rejected: this duplicates plan-parsing, task-selection, and
state-machine logic in every caller. The harness already owns those;
verifier dispatch is a tiny addition compared to re-implementing the
loop at the caller level. The user's design instruction is also
explicit: "harness should be able to apply them."

---

## 7. Open Questions

1. **Verifier *parallelism*.** v0.1 ships sequential. Dependency
   among verifiers (e.g. `tsc` must pass before `routes_200`) is
   captured by registration order in v0.1; v0.2 may add explicit
   `depends_on`. Default: defer.
2. **Rerun limits.** Should the harness track "task X has failed
   verifier Y, N times" and force-block the run? v0.1 says no —
   `max_iters` is the budget. If a verifier always fails on a given
   task the loop will exhaust naturally.
3. **Verifier-injected tasks.** Should a verifier be able to
   *append* tasks to `plan.md` (e.g. a "fix the build" follow-up)?
   v0.1 says no; only the executor adds tasks. v0.2 may relax.

---

## 8. Milestones (informative)

- **M1 — Protocol + dispatch.** `Verifier` protocol, `VerifierContext`,
  per-iteration dispatch, telemetry. Unit tests with stub verifiers.
- **M2 — Prompt feedback.** `{{verifier_feedback}}` slot + truncation.
  Integration test: a `FAIL` injects feedback; the next iteration
  receives it; on retry verdict is `PASS`; loop completes.
- **M3 — `shop_gen` consumer.** Verify the API satisfies
  `shop_gen`'s build-loop verifier set (rule + LLM mix). Tag harness
  v0.3.0.

---

## 9. Appendix

### 9.1 Public surface (informative)

```python
# harness/__init__.py adds:
from harness.verifiers import (
    Verifier,
    VerifierContext,
    VerifierResult,
    Verdict,
    VerifierRun,        # telemetry record
)

# harness/config.py adds to PlanExecLoopConfig:
verifiers: list[Verifier] = []
verifier_feedback_max_chars: int = 4000
```

### 9.2 Reference verifier shapes (informative; not shipped by harness)

A rule-based verifier — runs in-process, no LLM:

```python
class TSCVerifier:
    name = "tsc"
    def applies_to(self, task_id: str) -> bool: return task_id.startswith("gen_")
    def run(self, ctx: VerifierContext) -> VerifierResult:
        proc = subprocess.run(["tsc", "--noEmit"], cwd=ctx.artifact_dir / "hydrogen",
                              capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return VerifierResult(verdict=Verdict.PASS)
        return VerifierResult(
            verdict=Verdict.FAIL,
            feedback=f"`tsc --noEmit` failed:\n```\n{proc.stdout}\n```",
            details={"returncode": proc.returncode},
        )
```

An LLM-based verifier — reuses `ctx.runtime.complete`:

```python
class CapabilitiesMatchVerifier:
    name = "capabilities_match"
    def __init__(self, area: str): self.area = area
    def applies_to(self, task_id: str) -> bool: return task_id == f"gen_{self.area}"
    def run(self, ctx: VerifierContext) -> VerifierResult:
        rendered = render_page(ctx.artifact_dir, self.area)            # caller-defined
        prompt = build_judge_prompt(self.area, rendered, ctx.artifact_dir / "manual")
        completion = ctx.runtime.complete(prompt)                      # via LLMCompleter
        verdict, feedback = parse_judge_completion(completion)         # caller-defined
        return VerifierResult(verdict=verdict, feedback=feedback)
```
