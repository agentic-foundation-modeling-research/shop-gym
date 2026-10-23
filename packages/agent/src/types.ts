/**
 * The agent seam: what the rest of ShopGym needs from an LLM agent.
 *
 * An `AgentRuntime` runs one agentic episode. It sends a prompt and a set of
 * tools to a model, executes the tool calls the model makes, and returns a
 * `Trajectory` of everything that happened. Harness, arena, and guru depend
 * only on these interfaces; `adapters/` bind them to concrete SDKs.
 */

import type { Static, TSchema } from '@sinclair/typebox';

import type { Trajectory, TrajectoryStep } from './trajectory.js';

/** Reasoning effort requested from the model. `off` disables extended thinking. */
export type ThinkingLevel = 'off' | 'low' | 'medium' | 'high';

/** A model in the grammar of the adapter's SDK, e.g. `{provider: 'openai', id: 'gpt-5.5'}`. */
export interface ModelRef {
  readonly provider: string;
  readonly id: string;
  readonly thinking?: ThinkingLevel;
}

/** A base64-encoded image attached to a prompt or returned by a tool. */
export interface ImageAttachment {
  readonly data: string;
  readonly mimeType: string;
}

/** A prompt with optional image attachments. */
export interface PromptContent {
  readonly text: string;
  readonly images?: readonly ImageAttachment[];
}

/** One content block of a tool result, as shown to the model. */
export type ToolContent =
  | { readonly type: 'text'; readonly text: string }
  | { readonly type: 'image'; readonly data: string; readonly mimeType: string };

/** What a tool returns. `isError` tells the model the call failed. */
export interface ToolResult {
  readonly content: readonly ToolContent[];
  readonly isError?: boolean;
}

/** Per-call context handed to a tool. */
export interface ToolContext {
  readonly cwd: string;
  readonly callId: string;
  readonly signal: AbortSignal;
}

/**
 * A tool the model may call. `parameters` is a TypeBox schema; the adapter
 * validates arguments against it before `execute` runs.
 */
export interface Tool<P extends TSchema = TSchema> {
  readonly name: string;
  readonly description: string;
  readonly parameters: P;
  execute(params: Static<P>, ctx: ToolContext): Promise<ToolResult>;
}

/** The tools offered to one run. */
export type ToolSet = readonly Tool[];

/** Live notification of a step as it is recorded. */
export type AgentEvent = TrajectoryStep;

/** Everything an `AgentRuntime` needs for one episode. */
export interface AgentRunRequest {
  /** Working directory the agent's tools operate in. */
  readonly cwd: string;
  readonly systemPrompt: string;
  readonly prompt: string | PromptContent;
  readonly tools: ToolSet;
  readonly model: ModelRef;
  /** Aborting ends the run with status `aborted`. */
  readonly signal: AbortSignal;
  /** Where the adapter writes raw SDK logs. Omitted means a temp dir. */
  readonly logDir?: string;
  readonly onEvent?: (event: AgentEvent) => void;
}

/** How a run ended. `error` covers both SDK failures and model-reported errors. */
export type AgentRunStatus = 'completed' | 'aborted' | 'error';

/** Result of one episode. The trajectory is complete for every status. */
export interface AgentRunResult {
  readonly trajectory: Trajectory;
  readonly status: AgentRunStatus;
  readonly error?: string;
}

/** Runs agentic episodes against one SDK. */
export interface AgentRuntime {
  readonly name: string;
  run(request: AgentRunRequest): Promise<AgentRunResult>;
}

/** The text of a prompt, with image attachments dropped. */
export function promptText(prompt: string | PromptContent): string {
  return typeof prompt === 'string' ? prompt : prompt.text;
}
