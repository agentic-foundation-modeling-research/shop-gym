/**
 * Behaviour every `AgentRuntime` adapter must share.
 *
 * Each case drives a runtime through one scenario and asserts on the
 * result with `node:assert`, so the suite runs under any test framework:
 *
 *     for (const c of conformanceCases) it(c.name, () => c.run(context));
 */

import assert from 'node:assert/strict';

import { type TObject, type TString, Type } from '@sinclair/typebox';

import { sha256, trajectorySchema } from '../trajectory.js';
import type { AgentRunRequest, AgentRuntime, ModelRef, Tool } from '../types.js';

/** The situations a conformance case puts a runtime in. */
export type ConformanceScenario = 'reply' | 'tool' | 'abort';

/** What a test file supplies to run the suite. */
export interface ConformanceContext {
  /** Build a runtime for one scenario. Scripted runtimes use it to pick a script. */
  readonly runtime: (scenario: ConformanceScenario) => AgentRuntime | Promise<AgentRuntime>;
  readonly cwd: string;
  readonly model: ModelRef;
}

/** One conformance case. */
export interface ConformanceCase {
  readonly name: string;
  run(context: ConformanceContext): Promise<void>;
}

const SYSTEM_PROMPT = 'You are a test agent. Follow the instruction exactly.';

/** Prompt the suite sends for each scenario. */
export const CONFORMANCE_PROMPTS: Readonly<Record<ConformanceScenario, string>> = {
  reply: 'Reply with exactly the word PONG and nothing else.',
  tool: 'Call the echo tool once with text "ping". After it returns, reply with exactly DONE.',
  abort: 'Reply with exactly the word PONG and nothing else.',
};

/** Tool the `tool` scenario expects the runtime to execute. */
export function makeEchoTool(): { tool: Tool<TObject<{ text: TString }>>; calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    tool: {
      name: 'echo',
      description: 'Echo the given text back.',
      parameters: Type.Object({ text: Type.String() }),
      async execute({ text }) {
        calls.push(text);
        return { content: [{ type: 'text', text }] };
      },
    },
  };
}

function baseRequest(
  context: ConformanceContext,
  scenario: ConformanceScenario,
  signal: AbortSignal,
): AgentRunRequest {
  return {
    cwd: context.cwd,
    systemPrompt: SYSTEM_PROMPT,
    prompt: CONFORMANCE_PROMPTS[scenario],
    tools: [],
    model: context.model,
    signal,
  };
}

/** The cases, in the order they are meant to be reported. */
export const conformanceCases: readonly ConformanceCase[] = [
  {
    name: 'records the prompt, an assistant reply with usage, and a valid trajectory',
    async run(context) {
      const runtime = await context.runtime('reply');
      const result = await runtime.run(baseRequest(context, 'reply', new AbortController().signal));
      assert.equal(result.status, 'completed', result.error);
      const trajectory = trajectorySchema.parse(result.trajectory);
      assert.equal(trajectory.runtime, runtime.name);
      assert.equal(trajectory.promptSha256, sha256(CONFORMANCE_PROMPTS.reply));
      assert.ok(trajectory.startedAt <= trajectory.endedAt);
      const first = trajectory.steps[0];
      assert.deepEqual(
        first && { kind: first.kind, role: 'role' in first ? first.role : undefined },
        { kind: 'message', role: 'user' },
      );
      const assistant = trajectory.steps.filter(
        (s) => s.kind === 'message' && s.role === 'assistant',
      );
      assert.ok(assistant.length > 0, 'no assistant message recorded');
      assert.ok(
        assistant.some((s) => s.kind === 'message' && s.usage !== undefined),
        'no assistant message carries usage',
      );
      assert.ok(trajectory.usage.input + trajectory.usage.output > 0, 'usage totals are zero');
    },
  },
  {
    name: 'round-trips a tool call through execute',
    async run(context) {
      const runtime = await context.runtime('tool');
      const echo = makeEchoTool();
      const result = await runtime.run({
        ...baseRequest(context, 'tool', new AbortController().signal),
        tools: [echo.tool],
      });
      assert.equal(result.status, 'completed', result.error);
      assert.deepEqual(echo.calls, ['ping']);
      const call = result.trajectory.steps.find((s) => s.kind === 'tool_call' && s.tool === 'echo');
      assert.ok(call?.kind === 'tool_call', 'no tool_call step for echo');
      assert.equal(call.arguments.text, 'ping');
      const reply = result.trajectory.steps.find(
        (s) => s.kind === 'tool_result' && s.callId === call.callId,
      );
      assert.ok(reply?.kind === 'tool_result', 'no tool_result step matching the call');
      assert.equal(reply.isError, false);
      assert.match(reply.output, /ping/);
    },
  },
  {
    name: 'reports aborted when the signal is already aborted',
    async run(context) {
      const runtime = await context.runtime('abort');
      const controller = new AbortController();
      controller.abort();
      const result = await runtime.run(baseRequest(context, 'abort', controller.signal));
      assert.equal(result.status, 'aborted');
      trajectorySchema.parse(result.trajectory);
    },
  },
];
