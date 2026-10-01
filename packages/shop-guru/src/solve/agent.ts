/**
 * The seam between the benchmark and whatever is being measured.
 *
 * An `AgentUnderTest` receives one episode at a time: the task, a browser
 * session already pointed at the storefront with any `setup` applied, the
 * UI-only browser tools bound to that session, and a signal that fires on
 * timeout, on abort, or once the agent calls `finish`.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { AgentRunStatus, AgentRuntime, ModelRef, Tool, Trajectory } from '@shop-gym/agent';
import type { BrowserSession } from '@shop-gym/browser';
import type { Task } from '@shop-gym/core';

import { fillPlaceholders } from '../placeholders.js';

export interface SolveEpisode {
  readonly task: Task;
  /** Storefront origin. */
  readonly baseUrl: string;
  readonly session: BrowserSession;
  /** Browser tools bound to `session`; `finish` ends the episode. */
  readonly tools: readonly Tool[];
  /** Directory for the agent's own logs. */
  readonly logDir: string;
  readonly signal: AbortSignal;
}

export interface SolveOutcome {
  readonly trajectory: Trajectory;
  readonly status: AgentRunStatus;
  readonly error?: string;
}

export interface AgentUnderTest {
  readonly name: string;
  readonly model: ModelRef;
  run(episode: SolveEpisode): Promise<SolveOutcome>;
}

/** Prompts live outside `src` so the same relative path works from `dist`. */
const PROMPT_PATH = fileURLToPath(new URL('../../prompts/solve.md', import.meta.url));

export interface RuntimeBrowserAgentOptions {
  readonly runtime: AgentRuntime;
  readonly model: ModelRef;
  /** Defaults to `<runtime name>-browser`. */
  readonly name?: string;
}

/**
 * Drives any `AgentRuntime` with the built-in solver prompt and the
 * episode's browser tools. `PiRuntime` plugged in here is the reference
 * `PiBrowserAgent`.
 */
export class RuntimeBrowserAgent implements AgentUnderTest {
  readonly name: string;
  readonly model: ModelRef;
  private readonly runtime: AgentRuntime;

  constructor(options: RuntimeBrowserAgentOptions) {
    this.runtime = options.runtime;
    this.model = options.model;
    this.name = options.name ?? `${options.runtime.name}-browser`;
  }

  async run(episode: SolveEpisode): Promise<SolveOutcome> {
    const systemPrompt = fillPlaceholders(await fs.readFile(PROMPT_PATH, 'utf-8'), {
      base_url: episode.baseUrl,
    });
    const result = await this.runtime.run({
      cwd: episode.logDir,
      systemPrompt,
      prompt: episode.task.goal,
      tools: [...episode.tools],
      model: this.model,
      signal: episode.signal,
      logDir: episode.logDir,
    });
    return {
      trajectory: result.trajectory,
      status: result.status,
      ...(result.error === undefined ? {} : { error: result.error }),
    };
  }
}
