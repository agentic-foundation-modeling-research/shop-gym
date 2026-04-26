# harness

Plan + Exec harness: a self-contained, runtime-agnostic engine for
orchestrating LLM agents through a plan-then-loop flow.

The harness is a **control plane**. It owns process lifecycle, a
workspace state machine, and normalized telemetry. It owns no prompts,
no tools, and no domain knowledge — those are the **data plane**,
provisioned by the `AgentRuntime` adapter and resident inside the
iteration subprocess (Claude Code, `pi`). Tools, MCP servers, sandbox,
permissions, and skills come from whichever runtime the caller picks;
swapping runtimes swaps the data plane.

See
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

A runtime is the plug-in seam between the control plane (this package)
and the data plane (the agent CLI's tools, MCP, sandbox, permissions).
The harness blocks while the subprocess runs and consumes only the
normalized `Trajectory` it returns.

Runtimes are selected by name via `get_runtime(name, **kwargs)`:

- `claude_code` — runs each iteration as a `claude --print` subprocess.
  Brings Claude Code's tool stack (Read/Write/Bash, MCP, sandbox,
  permissions, skills).
- `pi` — runs each iteration as a `pi` CLI subprocess. Brings `pi`'s
  tool stack.
- `replay` — deterministic cassette replay used by tests; takes
  `scenario_dir=` and an optional `fallback=` runtime. Brings no live
  data plane — overlays a recorded `workspace_after/` and emits a
  recorded trajectory.

To swap runtimes, change the name only — the rest of the contract is
identical.

## Recording replay cassettes

`tests/cassettes/toy_homepage_<runtime>/` holds one cassette per real
runtime, captured against the toy scenario in
`tests/smoke/_toy_scenario.py`. Re-record either with the bundled
driver:

```bash
uv run python -m scripts.record_toy_cassette --runtime claude_code
uv run python -m scripts.record_toy_cassette --runtime pi
```

(executed from `packages/harness/`).

The script delegates each iteration to `ReplayRuntime`'s `fallback`
runtime under `HARNESS_RECORD=1` and writes a fresh cassette directory
matching the layout in spec §5.6. Re-record whenever prompts,
`AGENTS.md`, or a runtime's native log contract changes.
