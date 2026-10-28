# All agent work goes through one in-process runtime seam

v1.0 ran each agent as a `pi` or `claude` CLI subprocess and rebuilt the trajectory by parsing its log. Now every agent call (build loop, explore, solve, judges, data synthesis) goes through the `AgentRuntime` and `LlmClient` interfaces in `@shop-gym/agent`, and the only adapter today drives the pi SDK in-process. Callers never see pi types, so a new SDK is one adapter directory plus the shared conformance suite, and in-process calls give typed tool execution and per-message usage and cost.

## Considered Options

- Use pi's `AgentSession` type directly in callers: rejected, because it locks every caller to pi.
- Keep CLI subprocess runtimes as the default: rejected, because they add a second config surface (`~/.pi`, CLI flags) and turn trajectories into log parsing. A subprocess adapter is still possible later for agents that have no SDK.

## Consequences

The pi adapter reads nothing from `~/.pi`. It writes a `models.json` per run, turns off extensions, skills, context files and compaction, uses the caller's system prompt as-is, and exposes only the tools in the request.
