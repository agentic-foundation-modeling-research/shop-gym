# Changelog

All notable changes to `harness` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-04-25

Initial release. Implements the
[plan + exec loop spec](../../docs/specs/harness/plan_exec_loop.md) v0.1.

### Added

- **Core primitives** (M1): `TaskStatus`, `Task`, `TaskList`, `Trajectory`,
  `TrajectoryStep`, `IterationMetadata`, `ProtocolCheckResult`, `Prompts`,
  `PlanExecLoopConfig`, `PlanExecLoopResult`.
- **Plan parser** (`plan_parser`): GFM checkbox parser enforcing the §5.5
  invariants, priority-aware `select_next`, `diff`, and `InvalidPlanError`.
- **Workspace** (`workspace`): owns the §5.3 `run_dir` layout, atomic JSON
  rewrites via temp + `os.replace`, and plan snapshotting.
- **Protocol checks** (`protocol_check`): deterministic post-execution
  invariants (parseable plan, unique ids, no resurrected `[x]`, single
  terminal flip, new tasks PENDING).
- **Telemetry** (`telemetry`): per-iter dir helper, `RunSummaryWriter` with
  secret-scrubbing and atomic rewrite, `reconstruct(run_dir)` validator
  that rebuilds `PlanExecLoopResult` from append-only files alone.
- **Loop** (M2): `run_plan_exec_loop(config, runtime)` runs one planner
  iteration plus bounded executor iterations with the
  `<<<harness-control>>>` header carrying `selected_task_id`. Maps
  `TimeoutExpired` → `timeout`, exceptions → `runtime_error`, and rewrites
  `run.json` after every iteration.
- **Runtimes** (M2 / M3):
  - `AgentRuntime` Protocol (`runtimes.base`).
  - `get_runtime(name, **kwargs)` registry with lazy imports.
  - `ReplayRuntime`: deterministic cassette playback; `HARNESS_RECORD=1`
    delegates to a fallback runtime to record a fresh cassette.
  - `ClaudeCodeRuntime`: spawns `claude --print --output-format=stream-json`,
    streams `native.log`, converts stream-json events to `TrajectoryStep`s,
    symlinks `CLAUDE.md → AGENTS.md` for auto-load.
  - `PiRuntime`: spawns `pi --print --output-format=jsonl`, streams
    `native.log`, ships its own native-log → `Trajectory` converter.
- **Tests**: unit suite for every module, e2e replay suite covering
  `completed`, `invalid_plan`, `protocol_violation`, `budget_exhausted`,
  `timeout`, and `runtime_error` terminal statuses, plus
  `HARNESS_SMOKE_CLAUDE` / `HARNESS_SMOKE_PI`-gated live smoke tests.
- **Docs**: `README.md` with usage example, runtime selection notes, and
  cassette recording workflow.

[0.1.0]: https://github.com/Shopify/shop-gym/releases/tag/harness-v0.1.0
