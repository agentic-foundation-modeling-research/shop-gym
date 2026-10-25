# Agent Runtime Seam

## Overview

`@shop-gym/agent` is the single boundary between ShopGym and LLM agent SDKs.
Harness, arena, and guru program against `AgentRuntime`, `LlmClient`, `Tool`,
and `Trajectory`; adapters under `adapters/` implement them for one SDK each.
This spec fixes those contracts and the conformance every adapter must meet.

## Terminology

- **AgentRuntime** - runs one agentic episode: prompt in, tool calls executed,
  trajectory out.
- **LlmClient** - one completion without tools, optionally JSON constrained.
- **Tool** - a named, TypeBox-typed function the model may call.
- **Trajectory** - the SDK-independent record of an episode.
- **Adapter** - an `AgentRuntime` or `LlmClient` bound to a concrete SDK.
- **Conformance suite** - behaviour cases run against every adapter.

## Current Status

Implemented in `packages/agent` (milestone M1 of the v1.1 redesign):

- `AgentRuntime`, `AgentRunRequest`, `AgentRunResult`, `Tool`, `ToolSet`,
  `ModelRef`, `PromptContent`, `LlmClient`, `completeJson`.
- `Trajectory` zod schema with timestamped steps and per-message usage.
- `adapters/pi`: `PiRuntime` and `PiLlmClient` on
  `@earendil-works/pi-coding-agent` 0.87.1.
- `testing/`: `FakeRuntime` and `conformanceCases`.

## Desired Status

Unchanged from the current status. Future adapters (for example an OpenAI
Agents or Claude Agent SDK adapter) add a directory under `adapters/` and a
test file that runs `conformanceCases`; nothing outside the package changes.

## Proposal

### Interfaces

```ts
interface AgentRuntime {
  readonly name: string;
  run(request: AgentRunRequest): Promise<AgentRunResult>;
}
interface AgentRunRequest {
  cwd: string; systemPrompt: string; prompt: string | PromptContent;
  tools: ToolSet; model: ModelRef; signal: AbortSignal;
  logDir?: string; onEvent?(step: TrajectoryStep): void;
}
interface AgentRunResult { trajectory: Trajectory; status: 'completed' | 'aborted' | 'error'; error?: string }
interface Tool<P extends TSchema> { name; description; parameters: P; execute(params: Static<P>, ctx: ToolContext): Promise<ToolResult> }
interface LlmClient { complete(request: CompleteRequest): Promise<Completion> }
```

Rules:

- `run` never throws for model or tool failures. They surface as
  `status: 'error'` with a trajectory that still records what happened.
- Aborting `signal` ends the run with `status: 'aborted'`; a signal that is
  already aborted produces an aborted result without contacting the model.
- The system prompt is used verbatim. Adapters add no prompt of their own.
- Only the request's tools are exposed. No SDK built-in tools.
- `logDir` holds raw SDK output (`events.jsonl`) and tool images
  (`screenshots/`). Callers own the directory layout above it.

### Trajectory

```ts
{
  runtime, model: {provider, id}, startedAt, endedAt, promptSha256,
  steps: ({timestamp} & (
    | {kind:'message', role:'user'|'assistant', text, model?, stopReason?, usage?}
    | {kind:'thought', text}
    | {kind:'tool_call', callId, tool, arguments}
    | {kind:'tool_result', callId, output, isError}
    | {kind:'screenshot', callId, path}
    | {kind:'error', message}))[],
  usage: {input, output, cacheRead, cacheWrite, costUsd}
}
```

`usage` on an assistant message is that one model call; the top-level
`usage` is the sum. `promptSha256` hashes the prompt text only.

### pi adapter

- Per run: `logDir/pi/models.json` with `baseUrl` overrides from
  `Credentials.anthropicBaseUrl` / `openaiBaseUrl`. API keys are set with
  `ModelRuntime.setRuntimeApiKey`; the gateway key (`PI_PROXY_API_KEY`) wins
  for a provider that has a base URL, otherwise the provider key.
- `createAgentSession` with `SessionManager.inMemory`,
  `SettingsManager.inMemory({compaction: {enabled: false}})`,
  `DefaultResourceLoader` with every discovery flag off and
  `systemPrompt` set, and `tools` as an explicit allowlist of the request's
  tool names (`noTools: 'all'` would also drop custom tools).
- Session events map to steps: `message_end` (assistant) to `thought`,
  `message`, and `tool_call`; `tool_execution_end` to `tool_result` and
  `screenshot`.
- `PiLlmClient` uses `ModelRuntime.completeSimple` with the same routing.

### Conformance suite

Three cases, run by every adapter's test file and by `FakeRuntime`:

1. **reply** - status completed, trajectory validates, first step is the
   user message, an assistant message carries usage, totals are non-zero.
2. **tool** - the `echo` tool's `execute` runs with the model's arguments
   and the trajectory holds a matching `tool_call` / `tool_result` pair.
3. **abort** - an already-aborted signal yields status aborted.

Live adapter runs are gated behind `SHOPGYM_LIVE=1`.

## Alternative

Wrapping the `pi` CLI as a subprocess (the v1 approach) was rejected: it
forces a second config surface (`~/.pi`, CLI flags), loses typed tool
execution, and makes trajectories a log-parsing exercise.

## Execution Table

| # | Item | Status |
| - | ---- | ------ |
| 1 | Interfaces, trajectory schema, `completeJson` | done |
| 2 | pi adapter with per-run routing and isolation | done |
| 3 | `FakeRuntime` and conformance cases | done |
| 4 | Live conformance gated by `SHOPGYM_LIVE` | done |

## Appendix

pi SDK surface used: `createAgentSession`, `DefaultResourceLoader`,
`SessionManager.inMemory`, `SettingsManager.inMemory`, `ModelRuntime.create`
/ `getModel` / `setRuntimeApiKey` / `completeSimple`, `ToolDefinition`,
`AgentSession.subscribe` / `prompt` / `abort` / `dispose`.
