# Plan + Exec Harness — Implementation Plan

Status: **Plan (proposed)** · Version: **0.1**
Spec: [`docs/specs/harness/plan_exec_loop.md`](../specs/harness/plan_exec_loop.md)
Target package: `packages/harness`

> Task list for landing the spec. Each task is one PR-sized unit of
> work with a deliverable and a check. Behavior comes from the spec;
> this doc only says what to do and in what order.

---

## 1. Overview

Four milestones, each independently landable: M1 pure data layer, M2
orchestration loop + replay runtime, M3 real CLI runtimes, M4 v0.1.0
release. Tasks below are ordered; later tasks assume earlier ones.

## 2. Terminology

Uses the spec's vocabulary verbatim. No new terms.

## 3. Current Status

`packages/harness` does not exist. Not registered in any workspace
config. No callers consume it.

## 4. Desired Status

After M4: `from harness import run_plan_exec_loop, get_runtime` works;
`pytest packages/harness/tests` is green without API keys; smoke tests
behind `HARNESS_SMOKE_*` env vars verify real-CLI parity.

---

## 5. Proposal — Task list

### M1 · Core primitives

- [x] **T1.1** — Create `packages/harness/` skeleton: `pyproject.toml` (hatchling, mirror `shop_arena`), `src/harness/__init__.py`, `src/harness/py.typed`, empty `tests/`. **Check:** `uv sync` installs it.
- [x] **T1.2** — Register the package in root `pyproject.toml` under `[tool.uv.workspace]`, `[tool.ruff].src`, `[tool.pyright].include`, `[tool.pytest.ini_options].testpaths`. **Check:** `pyright --strict` and `ruff check` run clean on the empty package.
- [x] **T1.3** — `src/harness/types.py`: `TaskStatus` enum, frozen dataclasses `Task` / `TaskList`, pydantic v2 `Trajectory` + tagged-union `TrajectoryStep`, `IterationMetadata`, `ProtocolCheckResult`. **Check:** unit tests round-trip every pydantic model through JSON.
- [x] **T1.4** — `src/harness/config.py`: `Prompts`, `PlanExecLoopConfig`, `PlanExecLoopResult` (incl. `final_status` enum). **Check:** invalid configs (`max_iters <= 0`, missing prompt) raise `ValidationError`.
- [x] **T1.5** — `src/harness/plan_parser.py`: `parse(text) -> TaskList`, `select_next(tasks)`, `diff(before, after)`, `InvalidPlanError`. Enforces all §5.5 invariants. **Check:** `tests/unit/test_plan_parser.py` covers happy path, each invariant violation, priority ordering, optional `— note`.
- [x] **T1.6** — `src/harness/workspace.py`: `Workspace.create(config)`, `snapshot_plan`, `atomic_write_json` (temp + `os.replace`). Rejects non-empty `run_dir`. **Check:** `tests/unit/test_workspace.py` asserts the §5.3 layout exists post-create and that snapshots are byte-identical copies.
- [x] **T1.7** — `src/harness/protocol_check.py`: pure `run_protocol_checks(before, after, selected_id)` covering the §5.8 list. **Check:** one test per violation, plus a clean-pass case.
- [x] **T1.8** — `src/harness/telemetry.py`: per-iter dir helper, `RunSummaryWriter.rewrite(run_dir, ...)` with secret-scrubbing regex, `reconstruct(run_dir) -> PlanExecLoopResult` validator. **Check:** unit test rebuilds `run.json` from a hand-crafted `iters/` tree; secrets in config snapshot are redacted.

**M1 acceptance:** all unit tests green, `pyright --strict` clean, `ruff` clean. No subprocess code yet.

### M2 · Loop + replay runtime

- [x] **T2.1** — `src/harness/runtimes/base.py`: `AgentRuntime` Protocol with `run_iteration(*, run_dir, iter_dir, prompt, timeout) -> RuntimeIterationResult`. **Check:** import-only smoke test.
- [x] **T2.2** — `src/harness/runtimes/__init__.py`: `get_runtime(name, **kwargs)` registry. **Check:** unknown name raises `ValueError`; `"replay"` resolves once T2.3 lands.
- [x] **T2.3** — `src/harness/runtimes/replay.py`: `ReplayRuntime(scenario_dir, fallback=None)`. Replay mode copies `workspace_after/` overlay union-with-overwrite, copies `trajectory.json` + `native.log` into `iter_dir`. Record mode (`HARNESS_RECORD=1`) delegates to `fallback` and writes a fresh cassette; refuses if `fallback is None`. **Check:** unit test of overlay semantics; record-mode test with a stub fallback writes the expected cassette.
- [x] **T2.4** — `src/harness/loop.py`: `run_plan_exec_loop(config, runtime)` implementing the spec §5.2 loop. Composes the executor prompt with a fixed `<<<harness-control>>>` header carrying `selected_task_id`. Maps `subprocess.TimeoutExpired` → `final_status=timeout`, other exceptions → `runtime_error`. Records `prompt_sha256` per iter. Calls `RunSummaryWriter.rewrite` after every iter. **Check:** signature matches spec §8.1.
- [x] **T2.5** — Author hand-crafted toy cassette `tests/cassettes/toy_homepage/` with `plan/`, `exec-0001/`, `exec-0002/`. Plan creates two PENDING tasks; execs mark them `[x]` in priority order. **Check:** cassette files match the spec §5.6 minimal shape.
- [x] **T2.6** — `tests/e2e/test_loop_replay.py`: full toy run end-to-end against `ReplayRuntime`. Asserts §5.3 layout exists, `final_status=completed`, `telemetry.reconstruct(run_dir)` returns the same `PlanExecLoopResult`. **Check:** SC1 + SC3 satisfied.
- [ ] **T2.7** — `tests/e2e/test_loop_invariants.py`: handcrafted bad cassettes triggering each terminal status (`invalid_plan`, `protocol_violation`, `budget_exhausted`, `timeout`, `runtime_error`). **Check:** each status reachable from at least one test.
- [ ] **T2.8** — `tests/unit/test_runtime_registry.py`: registry coverage. **Check:** SC2 partially satisfied (replay only; full SC2 lands in M3).

**M2 acceptance:** `pytest packages/harness/tests` green in CI without API keys.

### M3 · Real CLI runtimes

- [ ] **T3.1** — `src/harness/runtimes/claude_code.py`: `ClaudeCodeRuntime`. Symlinks `run_dir/CLAUDE.md → AGENTS.md`. Spawns `claude --print --output-format=stream-json`, streams stdout to `iter_dir/native.log`, converts JSON-stream events to `TrajectoryStep`s. Honors timeout via `subprocess.run(timeout=...)` + process-group kill on expiry. **Check:** unit test of the converter against a recorded `native.log` fixture.
- [ ] **T3.2** — `src/harness/runtimes/pi.py`: `PiRuntime`. Same shape as T3.1 minus the CLAUDE.md symlink; ships its own native-log → `Trajectory` converter. **Check:** converter unit test against a recorded fixture.
- [ ] **T3.3** — Re-record toy cassettes by running each real runtime with `HARNESS_RECORD=1` against the M2 scenario. Commit refreshed cassettes. **Check:** `test_loop_replay.py` still green; diff vs. M2 hand-authored cassette is review-readable.
- [ ] **T3.4** — `tests/smoke/test_claude_code.py` + `tests/smoke/test_pi.py`, marked `@pytest.mark.smoke`, skipped unless `HARNESS_SMOKE_CLAUDE=1` / `HARNESS_SMOKE_PI=1`. Run the toy scenario live; assert `tasks_final` matches cassette and step-kind counts match within tolerance. **Check:** smoke run passes locally for at least one runtime; CI skips by default.

**M3 acceptance:** SC2 fully satisfied — same toy scenario passes under both real runtimes.

### M4 · v0.1.0

- [ ] **T4.1** — Lock public surface: `harness/__init__.py` re-exports only the names in spec §8.1. **Check:** `from harness import …` works for each listed symbol; nothing else is importable from the top level.
- [ ] **T4.2** — `packages/harness/README.md`: 60-line usage example, runtime-selection note, record-cassette workflow. **Check:** `python -c` snippet from the README runs.
- [ ] **T4.3** — `packages/harness/CHANGELOG.md`: `0.1.0` entry. Bump `pyproject.toml` version to `0.1.0`. Tag `harness-v0.1.0`. **Check:** tag pushed.
- [ ] **T4.4** — Already done in this PR: `docs/specs/README.md` cross-cutting row "Impl Plan" cell points here. Verify it still does. **Check:** link resolves.

---

## 6. Milestones (summary)

| Milestone | Tasks       | Gate                                       |
| --------- | ----------- | ------------------------------------------ |
| M1        | T1.1–T1.8   | unit tests + pyright strict + ruff         |
| M2        | T2.1–T2.8   | M1 + e2e replay + invariant suite          |
| M3        | T3.1–T3.4   | M2 + smoke tests gated by env vars         |
| M4        | T4.1–T4.4   | All prior + README + CHANGELOG + tag       |

## 7. Appendix

### 7.1 Out-of-scope (deferred)

Tracked here so we don't drift into them: `Verifier` / `verdicts.md`,
hooks, long-lived orchestrator mode, parallelism, RPC runtime. See spec
§5.8 + §8.2.

### 7.2 Open questions

- Claude Code `--output-format=stream-json` stability — confirm before T3.1.
- `pi` CLI non-interactive mode — verify before T3.2; may need a wrapper script.
- Caller migration (`shop_explore`, `shop_gen`) is out of scope; tracked separately after M4.
