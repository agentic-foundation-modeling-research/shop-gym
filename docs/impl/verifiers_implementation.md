# Harness Verifiers — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/harness/verifiers.md`](../specs/harness/verifiers.md)
Target package: `packages/harness`

> Pure task checklist. Behavior comes from the spec; this doc only
> says what to do and in what order.

---

## Tasks

### M1 · Protocol + dispatch

- [ ] **T1.1** — `src/harness/verifiers/__init__.py`: `Verdict` (StrEnum), `VerifierResult`, `VerifierContext`, `Verifier` (Protocol), `VerifierRun` (telemetry record). Public re-exports from `harness/__init__.py`. Spec §5.2 + §9.1. **Check:** `from harness import Verifier, VerifierContext, VerifierResult, Verdict, VerifierRun` works; types frozen; `extra="forbid"`.
- [ ] **T1.2** — Extend `PlanExecLoopConfig` with `verifiers: list[Verifier] = []` and `verifier_feedback_max_chars: int = 4000`. Spec §4.1 + §9.1. **Check:** existing callers compile unchanged; `verifiers=[]` default.
- [ ] **T1.3** — `src/harness/loop.py`: per-iteration verifier dispatch after protocol checks. Filter by `applies_to(selected_task_id)`, run sequentially, time + catch exceptions (→ `Verdict.ERROR`), persist `iters/<id>/checks/verifiers/<name>.json`. Spec §5.3 steps 1–3 + §5.6. **Check:** unit test with stub verifiers asserts files written, ordering preserved, ERROR captured with `feedback=str(exc)`.
- [ ] **T1.4** — On any `FAIL`: rewrite `[x]` or `[!]` → `[~]` for `selected_task_id` in `plan.md`, preserving task brief, priority, and other line metadata. Spec §5.3 step 4 + §5.4. **Check:** unit test asserts marker rewrite, brief preserved, other tasks untouched, `plan.after.md` snapshot taken **before** dispatch.
- [ ] **T1.5** — `PlanExecLoopResult.verifier_runs: list[VerifierRun]` populated; `run.json` aggregates summary rows (no `feedback`/`details`). Spec §5.6. **Check:** validator round-trip; `run.json` size sanity-checked.
- [ ] **T1.6** — Tests: (a) empty `verifiers=[]` produces byte-identical telemetry to v0.1; (b) all-PASS leaves `[x]` intact; (c) one FAIL rewrites to `[~]`; (d) ERROR does not block; (e) ADVISORY does not block. SC1 + SC2 + SC4 + SC5. **Check:** all five pass under the `replay` runtime.

**M1 acceptance:** dispatch works end-to-end without prompt feedback wired; SC1/SC2/SC4/SC5 satisfied.

### M2 · Prompt feedback

- [ ] **T2.1** — `iters/<id>/checks/verifiers/feedback.md` writer: concatenate non-empty `feedback` under per-verifier headers (`## <name>`). Skip writing when nothing to report. Spec §5.3 step 5. **Check:** unit test on mixed PASS/FAIL/ADVISORY/ERROR verdict sets.
- [ ] **T2.2** — Truncate `feedback.md` content per `verifier_feedback_max_chars` with `[...truncated]` suffix when injected; full body remains on disk. Spec §5.5. **Check:** unit test with feedback exceeding the budget.
- [ ] **T2.3** — `{{verifier_feedback}}` slot rendering in the executor prompt: read **previous** iteration's `feedback.md`, render once before subprocess spawn. Missing placeholder ⇒ no injection. Missing file ⇒ empty string. Spec §5.5. **Check:** integration test — first iteration sees empty slot, post-FAIL iteration sees previous feedback verbatim (modulo truncation).
- [ ] **T2.4** — End-to-end integration test under `replay`: iter-1 FAIL → feedback written → iter-2 prompt receives feedback → iter-2 PASS → loop completes with no remaining FAIL verdicts. SC3. **Check:** test green, telemetry has expected `verifier_runs` sequence.

**M2 acceptance:** SC3 satisfied; verifier-driven retry loop is closed.

### M3 · `shop_gen` consumer + release

- [ ] **T3.1** — Reference verifier fixtures under `tests/integration/verifiers/`: a rule-based stub (`AlwaysPass`, `AlwaysFail`, `RaisesException`) and an `LLMCompleter`-driven stub that asserts `ctx.runtime.complete` is callable. Spec §9.2. **Check:** fixtures usable from `shop_gen`'s own tests once landed.
- [ ] **T3.2** — Update `harness/__init__.py` `__all__` and bump `_version.py` to `0.3.0`. **Check:** `from harness import __version__` returns `"0.3.0"`.
- [ ] **T3.3** — Update spec status badge in [`docs/specs/harness/verifiers.md`](../specs/harness/verifiers.md) from "Spec (draft)" to "Implemented in `harness` 0.3.0". Update `docs/specs/README.md` row accordingly. **Check:** links resolve; status accurate.
- [ ] **T3.4** — Tag `harness-v0.3.0`. **Check:** tag pushed.

**M3 acceptance:** harness 0.3.0 tagged; `shop_gen` M5 unblocked.

---

## Milestones (summary)

| Milestone | Tasks     | Gate                                                                |
| --------- | --------- | ------------------------------------------------------------------- |
| M1        | T1.1–T1.6 | dispatch + telemetry; SC1/SC2/SC4/SC5 under `replay`                |
| M2        | T2.1–T2.4 | prompt feedback wired; SC3                                          |
| M3        | T3.1–T3.4 | consumer fixtures + 0.3.0 tag; `shop_gen` M5 unblocked              |
