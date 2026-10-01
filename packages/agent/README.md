# @shop-gym/agent

The agent seam: the interfaces the rest of ShopGym uses to run LLM agents,
plus the adapters that bind them to concrete SDKs.

- `types.ts` - `AgentRuntime.run(request)` runs one agentic episode with a
  system prompt, a prompt (text plus optional images), a `ToolSet`, a
  `ModelRef`, and an `AbortSignal`. `Tool` is a TypeBox-typed function the
  model may call.
- `trajectory.ts` - the uniform record of an episode: timestamped steps
  (`message`, `thought`, `tool_call`, `tool_result`, `screenshot`, `error`),
  per-assistant-message `usage`, `model`, and `stopReason`, plus totals.
- `llm.ts` - `LlmClient.complete(request)` for single completions, and
  `completeJson(client, request, zodSchema)` for schema-validated JSON.
- `adapters/pi/` - `PiRuntime` and `PiLlmClient` on the pi coding agent SDK.
  Each run uses an in-memory session and settings, no extensions, skills,
  themes, prompt templates, or context files, and exactly the request's
  tools. Routing comes from `Credentials`: `*_BASE_URL` values go into a
  per-run `models.json`; API keys (gateway key first when a base URL is set)
  are injected at runtime and never written to disk. Raw SDK events land in
  `logDir/events.jsonl`; tool images are saved under `logDir/screenshots/`.
- `testing/` (exported as `@shop-gym/agent/testing`) - `FakeRuntime`, a
  scripted runtime that writes files, calls tools, and replies; and
  `conformanceCases`, the behaviour suite every adapter must pass.

```bash
pnpm --filter @shop-gym/agent test                     # unit + fake conformance
SHOPGYM_LIVE=1 pnpm --filter @shop-gym/agent test      # also run pi against real models
SHOPGYM_LIVE_MODEL=anthropic/claude-sonnet-4-5 ...     # pick the live model
```

Live tests read credentials from the repo root `.env`.
