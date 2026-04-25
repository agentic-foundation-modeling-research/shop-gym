# harness

Plan + Exec harness: a self-contained, runtime-agnostic engine for
orchestrating LLM agents through a plan-then-loop flow.

The harness owns process lifecycle, a workspace state machine, and
normalized telemetry. It owns no prompts, no tools, and no domain
knowledge. See
[`docs/specs/harness/plan_exec_loop.md`](../../docs/specs/harness/plan_exec_loop.md)
for the full design.

## Install

The package is part of the repo `uv` workspace:

```bash
uv sync
```

Verify the public surface imports cleanly:

```bash
uv run python -c "from harness import PlanExecLoopConfig, Prompts, get_runtime, run_plan_exec_loop; print('ok')"
```

## Usage

A run takes a planner prompt, an executor prompt, an `AGENTS.md` body,
and an `AgentRuntime`. The harness creates `run_dir`, runs one planner
iteration, then loops executor iterations until all PENDING tasks are
drained or `max_iters` is reached.

```python
from pathlib import Path

from harness import (
    PlanExecLoopConfig,
    Prompts,
    get_runtime,
    run_plan_exec_loop,
)

config = PlanExecLoopConfig(
    run_dir=Path("/tmp/my-run"),
    prompts=Prompts(
        planner="Write a plan.md with one PENDING task per page to cover.",
        execute="Work on the selected task. Self-check before marking it [x].",
    ),
    agents_md="# Project rules\n...\n",
    max_iters=10,
    timeout=300.0,
)
runtime = get_runtime("claude_code")  # or "pi", or "replay"
result = run_plan_exec_loop(config, runtime)

print(result.final_status, result.exec_iter_count)
```

After the run, `result` is also persisted as `run_dir/run.json`. Per-iteration
telemetry lives under `run_dir/iters/<iter_id>/` (see spec §5.3).

## Runtimes

Runtimes are selected by name via `get_runtime(name, **kwargs)`:

- `claude_code` — runs each iteration as a `claude --print` subprocess.
- `pi` — runs each iteration as a `pi` CLI subprocess.
- `replay` — deterministic cassette replay used by tests; takes
  `scenario_dir=` and an optional `fallback=` runtime.

To swap runtimes, change the name only — the rest of the contract is
identical.

## Recording replay cassettes

`tests/cassettes/<scenario>/` holds the cassettes consumed by the e2e
suite. To re-record one against a real CLI runtime:

```bash
HARNESS_RECORD=1 pytest packages/harness/tests/e2e/test_loop_replay.py
```

Record mode delegates each iteration to `ReplayRuntime`'s `fallback`
runtime and writes a fresh cassette directory matching the layout in
spec §5.6. Re-record whenever prompts or `AGENTS.md` change.
