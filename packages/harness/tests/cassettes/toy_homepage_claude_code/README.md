# `toy_homepage_claude_code` cassette

Per-runtime recording of the toy scenario captured by running the real
`claude` CLI through `ReplayRuntime` in record mode (impl plan T3.3).
Re-record with:

```bash
uv run python -m scripts.record_toy_cassette --runtime claude_code
```

(executed from `packages/harness/`).

## Shape

```
toy_homepage_claude_code/
├── plan/                 # planner iteration
├── exec-0001/            # executor iteration 1 (selects `homepage`, priority 2)
└── exec-0002/            # executor iteration 2 (selects `product_detail`, priority 1)
```

Each iteration directory matches the spec §5.6 minimal cassette layout:
`trajectory.json`, `native.log`, and `workspace_after/` (the evolving
workspace surface the iteration leaves behind).

## Behaviour

`plan/` writes a two-task `plan.md`:

```
- [ ] homepage          [priority: 2]
- [ ] product_detail    [priority: 1]
```

`exec-0001/` runs against the harness-selected `homepage` task and flips
it to `[x]`. `exec-0002/` runs against `product_detail` and flips it to
`[x]`. The run terminates `completed`.

Re-record whenever the toy prompts in `tests/smoke/_toy_scenario.py`,
`AGENTS.md`, or the Claude Code `stream-json` event contract changes.
