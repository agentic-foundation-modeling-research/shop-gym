/**
 * `AgentRuntime` backed by the pi coding agent SDK.
 *
 * Every run is isolated: an in-memory session, an in-memory settings
 * manager with compaction off, no extensions, skills, themes, prompt
 * templates, or context files, and only the tools from the request. The
 * system prompt replaces pi's default one verbatim. Raw SDK events are
 * appended to `logDir/events.jsonl`; images returned by tools are saved
 * under `logDir/screenshots/`.
 */

import * as fs from 'node:fs';
import * as fsp from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { AgentToolResult } from '@earendil-works/pi-agent-core';
import type { AssistantMessage, ImageContent, TextContent } from '@earendil-works/pi-ai';
import {
  type AgentSessionEvent,
  DefaultResourceLoader,
  SessionManager,
  SettingsManager,
  type ToolDefinition,
  createAgentSession,
} from '@earendil-works/pi-coding-agent';
import type { Credentials } from '@shop-gym/core';

import { TrajectoryRecorder, sha256 } from '../../trajectory.js';
import {
  type AgentRunRequest,
  type AgentRunResult,
  type AgentRunStatus,
  type AgentRuntime,
  type Tool,
  promptText,
} from '../../types.js';
import { promptImages, toUsage } from './convert.js';
import { createPiModelRuntime, resolveModel } from './model-runtime.js';

/** Options for `PiRuntime`. */
export interface PiRuntimeOptions {
  readonly credentials: Credentials;
}

const MIME_EXTENSIONS: Readonly<Record<string, string>> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/webp': 'webp',
  'image/gif': 'gif',
};

/** Runs episodes through the pi SDK with ShopGym's routing and isolation. */
export class PiRuntime implements AgentRuntime {
  readonly name = 'pi';

  constructor(private readonly options: PiRuntimeOptions) {}

  async run(request: AgentRunRequest): Promise<AgentRunResult> {
    const logDir = request.logDir ?? (await fsp.mkdtemp(path.join(os.tmpdir(), 'shopgym-pi-')));
    await fsp.mkdir(logDir, { recursive: true });
    const agentDir = path.join(logDir, 'pi');
    const modelRuntime = await createPiModelRuntime(agentDir, this.options.credentials);
    const model = resolveModel(modelRuntime, request.model);

    const resourceLoader = new DefaultResourceLoader({
      cwd: request.cwd,
      agentDir,
      noExtensions: true,
      noSkills: true,
      noPromptTemplates: true,
      noThemes: true,
      noContextFiles: true,
      systemPrompt: request.systemPrompt,
    });
    await resourceLoader.reload();

    const { session } = await createAgentSession({
      cwd: request.cwd,
      agentDir,
      modelRuntime,
      model,
      ...(request.model.thinking !== undefined ? { thinkingLevel: request.model.thinking } : {}),
      // An explicit allowlist: only the request's tools, none of pi's built-ins.
      tools: request.tools.map((tool) => tool.name),
      customTools: request.tools.map((tool) => toPiTool(tool, request.cwd)),
      resourceLoader,
      sessionManager: SessionManager.inMemory(request.cwd),
      settingsManager: SettingsManager.inMemory({ compaction: { enabled: false } }),
    });

    const text = promptText(request.prompt);
    const recorder = new TrajectoryRecorder(
      this.name,
      request.model,
      sha256(text),
      request.onEvent,
    );
    const sink = new EventSink(logDir, recorder);
    recorder.record({ kind: 'message', role: 'user', text });

    const unsubscribe = session.subscribe((event) => sink.handle(event));
    const onAbort = () => {
      void session.abort();
    };
    request.signal.addEventListener('abort', onAbort, { once: true });

    let status: AgentRunStatus;
    let error: string | undefined;
    try {
      if (!request.signal.aborted) {
        await session.prompt(text, { images: promptImages(request.prompt) });
      }
      status = request.signal.aborted
        ? 'aborted'
        : sink.modelError === undefined
          ? 'completed'
          : 'error';
      error = status === 'error' ? sink.modelError : undefined;
    } catch (caught) {
      status = request.signal.aborted ? 'aborted' : 'error';
      error = caught instanceof Error ? caught.message : String(caught);
      recorder.record({ kind: 'error', message: error });
    } finally {
      request.signal.removeEventListener('abort', onAbort);
      unsubscribe();
      session.dispose();
      await sink.close();
    }
    return { trajectory: recorder.finish(), status, ...(error !== undefined ? { error } : {}) };
  }
}

/** Translates pi session events into trajectory steps and a raw JSONL log. */
class EventSink {
  /** Message of the last assistant turn that ended with a provider error. */
  modelError: string | undefined;
  private readonly stream: fs.WriteStream;
  private screenshots = 0;

  constructor(
    private readonly logDir: string,
    private readonly recorder: TrajectoryRecorder,
  ) {
    this.stream = fs.createWriteStream(path.join(logDir, 'events.jsonl'), { flags: 'a' });
  }

  handle(event: AgentSessionEvent): void {
    this.stream.write(`${JSON.stringify({ at: new Date().toISOString(), ...event })}\n`);
    switch (event.type) {
      case 'message_end':
        if (event.message.role === 'assistant') {
          this.assistant(event.message);
        }
        break;
      case 'tool_execution_end':
        this.toolResult(event.toolCallId, event.result, event.isError);
        break;
      default:
        break;
    }
  }

  close(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.stream.end((err?: Error | null) => (err ? reject(err) : resolve()));
    });
  }

  private assistant(message: AssistantMessage): void {
    const texts: string[] = [];
    for (const part of message.content) {
      if (part.type === 'thinking' && part.thinking !== '') {
        this.recorder.record({ kind: 'thought', text: part.thinking });
      } else if (part.type === 'text') {
        texts.push(part.text);
      }
    }
    this.recorder.record({
      kind: 'message',
      role: 'assistant',
      text: texts.join(''),
      model: message.model,
      stopReason: message.stopReason,
      usage: toUsage(message.usage),
    });
    for (const part of message.content) {
      if (part.type === 'toolCall') {
        this.recorder.record({
          kind: 'tool_call',
          callId: part.id,
          tool: part.name,
          arguments: part.arguments,
        });
      }
    }
    this.modelError =
      message.stopReason === 'error'
        ? (message.errorMessage ?? 'model returned an error')
        : undefined;
  }

  private toolResult(callId: string, result: unknown, isError: boolean): void {
    const parts: string[] = [];
    for (const block of resultContent(result)) {
      if (block.type === 'text') {
        parts.push(block.text);
      } else {
        const relative = this.saveImage(callId, block);
        this.recorder.record({ kind: 'screenshot', callId, path: relative });
        parts.push(`[image: ${relative}]`);
      }
    }
    this.recorder.record({ kind: 'tool_result', callId, output: parts.join('\n'), isError });
  }

  private saveImage(callId: string, image: ImageContent): string {
    const ext = MIME_EXTENSIONS[image.mimeType] ?? 'bin';
    const relative = path.join(
      'screenshots',
      `${String(++this.screenshots).padStart(3, '0')}-${callId}.${ext}`,
    );
    const absolute = path.join(this.logDir, relative);
    fs.mkdirSync(path.dirname(absolute), { recursive: true });
    fs.writeFileSync(absolute, Buffer.from(image.data, 'base64'));
    return relative;
  }
}

/** Content blocks of a pi tool result; strings and unknown shapes become text. */
function resultContent(result: unknown): (TextContent | ImageContent)[] {
  if (typeof result === 'string') {
    return [{ type: 'text', text: result }];
  }
  if (
    typeof result === 'object' &&
    result !== null &&
    Array.isArray((result as AgentToolResult).content)
  ) {
    return (result as AgentToolResult).content;
  }
  return [{ type: 'text', text: JSON.stringify(result) }];
}

/** Wrap a ShopGym tool as a pi tool definition bound to `cwd`. */
function toPiTool(tool: Tool, cwd: string): ToolDefinition {
  return {
    name: tool.name,
    label: tool.name,
    description: tool.description,
    parameters: tool.parameters,
    async execute(toolCallId, params, signal) {
      const result = await tool.execute(params, {
        cwd,
        callId: toolCallId,
        signal: signal ?? new AbortController().signal,
      });
      const content = result.content.map((block) =>
        block.type === 'text'
          ? ({ type: 'text', text: block.text } satisfies TextContent)
          : ({ type: 'image', data: block.data, mimeType: block.mimeType } satisfies ImageContent),
      );
      if (result.isError) {
        throw new Error(
          content.map((block) => (block.type === 'text' ? block.text : '[image]')).join('\n'),
        );
      }
      return { content, details: undefined };
    },
  };
}
