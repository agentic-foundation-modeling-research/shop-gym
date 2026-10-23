/**
 * Scripted `AgentRuntime` for tests.
 *
 * Each call consumes the next `FakeScript`: it writes files under `cwd`,
 * executes the scripted tool calls against the request's tools, and ends
 * with a fixed reply. The trajectory it produces has the same shape as a
 * real adapter's, so harness tests exercise real telemetry code.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { TrajectoryRecorder, sha256 } from '../trajectory.js';
import {
  type AgentRunRequest,
  type AgentRunResult,
  type AgentRunStatus,
  type AgentRuntime,
  promptText,
} from '../types.js';

/** What one `FakeRuntime.run` call does. */
export interface FakeScript {
  /** Files to write under `cwd` before replying, keyed by relative path. */
  readonly writeFiles?: Readonly<Record<string, string>>;
  /** Tool calls to make, in order, against the request's tools. */
  readonly toolCalls?: readonly {
    readonly tool: string;
    readonly arguments: Record<string, unknown>;
  }[];
  /** Final assistant text. */
  readonly reply?: string;
  /** Status to report; defaults to `completed`, or `aborted` when the signal fires. */
  readonly status?: AgentRunStatus;
  readonly error?: string;
}

const FAKE_USAGE = { input: 10, output: 5, cacheRead: 0, cacheWrite: 0, costUsd: 0 };

/** Replays scripts in order; an exhausted queue replies with an empty message. */
export class FakeRuntime implements AgentRuntime {
  readonly name = 'fake';
  /** Every request received, oldest first. */
  readonly requests: AgentRunRequest[] = [];
  private readonly queue: FakeScript[];

  constructor(scripts: readonly FakeScript[] = []) {
    this.queue = [...scripts];
  }

  async run(request: AgentRunRequest): Promise<AgentRunResult> {
    this.requests.push(request);
    const script = this.queue.shift() ?? {};
    const text = promptText(request.prompt);
    const recorder = new TrajectoryRecorder(
      this.name,
      request.model,
      sha256(text),
      request.onEvent,
    );
    recorder.record({ kind: 'message', role: 'user', text });

    for (const [relative, content] of Object.entries(script.writeFiles ?? {})) {
      const target = path.join(request.cwd, relative);
      await fs.mkdir(path.dirname(target), { recursive: true });
      await fs.writeFile(target, content);
    }

    let error = script.error;
    let callNo = 0;
    for (const call of script.toolCalls ?? []) {
      if (request.signal.aborted) {
        break;
      }
      const callId = `call-${++callNo}`;
      recorder.record({ kind: 'tool_call', callId, tool: call.tool, arguments: call.arguments });
      const tool = request.tools.find((candidate) => candidate.name === call.tool);
      if (tool === undefined) {
        error = `unknown tool: ${call.tool}`;
        recorder.record({ kind: 'tool_result', callId, output: error, isError: true });
        break;
      }
      const result = await tool.execute(call.arguments, {
        cwd: request.cwd,
        callId,
        signal: request.signal,
      });
      const output = result.content
        .map((block) => (block.type === 'text' ? block.text : `[image ${block.mimeType}]`))
        .join('\n');
      recorder.record({ kind: 'tool_result', callId, output, isError: result.isError ?? false });
    }

    recorder.record({
      kind: 'message',
      role: 'assistant',
      text: script.reply ?? '',
      model: request.model.id,
      stopReason: 'stop',
      usage: FAKE_USAGE,
    });
    const status =
      script.status ??
      (request.signal.aborted ? 'aborted' : error === undefined ? 'completed' : 'error');
    return { trajectory: recorder.finish(), status, ...(error !== undefined ? { error } : {}) };
  }
}
