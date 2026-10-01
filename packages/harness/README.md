# @shop-gym/harness

The plan-then-loop engine: a runtime-agnostic control plane that drives an
`AgentRuntime` from `@shop-gym/agent` through one planner iteration and a
sequence of executor iterations, with protocol checks, verifier dispatch,
resume, and normalized telemetry.

The harness owns no prompts, tools, or domain knowledge. The caller passes
the planner and executor prompts, the `AGENTS.md` body, the `ToolSet`, and
the model; the runtime executes each iteration in-process.

- `plan/` - the `plan.md` grammar (`parse`, `selectNext`, `diff`), the
  executor protocol checks, and the pure `reopenTask` / `blockTask`
  rewrites.
- `seed.ts` - the seed manifest for `artifact/` and the post-iteration
  immutability check (`seed_mutated` / `seed_deleted` / `seed_extended`).
- `workspace.ts` - run-dir layout (`AGENTS.md`, `prompts/`, `artifact/`,
  `plan.md`, `iters/`, `run.json`), creation, and identity-checked reopen
  for resume.
- `verifiers/` - caller-owned `Verifier` dispatch after each executor
  iteration: FAIL reopens the task to `[~]`, ERROR never blocks, feedback is
  written to `checks/verifiers/feedback.md` and rendered into the next
  prompt's `{{verifier_feedback}}` placeholder.
- `loop.ts` - `runPlanExecLoop(config, runtime, { force? })`. Fresh or
  resume mode is inferred from `runDir`; executor-phase timeouts quarantine
  the iteration dir and skip the task; protocol violations and unparseable
  plan edits restore `plan.md`, force-block the task, and continue.
- `telemetry/` - iteration ids, `metadata.json` schema, secret scrubbing,
  atomic `run.json` writes, and `reconstruct(runDir)` for crashed runs.
- `trace.ts` - `renderIterDir(iterDir)` renders an iteration's
  `trajectory.json` (plus `metadata.json`) as plain text.

```ts
import { PiRuntime } from '@shop-gym/agent';
import { runPlanExecLoop } from '@shop-gym/harness';

const result = await runPlanExecLoop(
  {
    runDir: '/tmp/my-run',
    prompts: { planner: '...', execute: '...\n{{verifier_feedback}}' },
    agentsMd: '# Project rules\n',
    maxIters: 10,
    timeoutMs: 300_000,
    model: { provider: 'anthropic', id: 'claude-sonnet-4-5' },
    tools: [],
  },
  new PiRuntime({ credentials }),
);
console.log(result.finalStatus, result.execIterCount);
```

Every iteration leaves `iters/<id>/{plan.before.md,plan.after.md,trajectory.json,metadata.json,checks/}`
and `run.json` is rewritten after each one. All JSON written by this package
uses camelCase keys.

```bash
pnpm --filter @shop-gym/harness test
pnpm --filter @shop-gym/harness typecheck
```
