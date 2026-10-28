# The harness starts a fresh agent for each iteration and keeps memory in files

Long build and explore runs use a plan-then-loop. One planner iteration writes `plan.md`; then each executor iteration gets a new agent session, works one task that the harness selects, and ends. Between iterations the only memory is the run directory (`AGENTS.md`, `plan.md`, `artifact/`). We chose this over one long session with context compaction because fresh contexts stay reliable over multi-hour runs and give clean iteration boundaries for telemetry and resume.

## Considered Options

- One long-lived session with compaction: rejected for the reason above.
- Replace `plan.md` with `plan.json`: rejected. Agents edit markdown reliably, prompts and tests assume it, and no caller needs structured edits.

## Consequences

The harness has no domain knowledge. Callers supply prompts, tools and verifiers; the harness only dispatches verifiers after each iteration and reopens the task (`[~]`) when one returns `fail`.
