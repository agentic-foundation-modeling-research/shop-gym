/**
 * LLM-driven task discovery: one agent run over a hosted SandboxShop that
 * proposes tasks through `propose_task`, followed by independent
 * verification of every proposal.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  type AgentRuntime,
  type ModelRef,
  type Trajectory,
  writeTrajectory,
} from '@shop-gym/agent';
import { BrowserSession, browserTools } from '@shop-gym/browser';
import type { Task } from '@shop-gym/core';
import type { Customer } from '@shop-gym/shop-backend';

import { fillPlaceholders } from '../placeholders.js';
import { type Proposal, proposalTools } from './propose.js';
import { verifyProposal, withEvidence } from './verify.js';

/** Prompts live outside `src` so the same relative path works from `dist`. */
const PROMPT_PATH = fileURLToPath(new URL('../../prompts/explore.md', import.meta.url));

export interface ExploreOptions {
  readonly runtime: AgentRuntime;
  readonly model: ModelRef;
  readonly shop: string;
  readonly baseUrl: string;
  readonly skills: readonly string[];
  readonly customers: readonly Customer[];
  readonly maxTasks: number;
  /** Receives `trajectory.json`, `rejected.json`, and `evidence/<id>.png`. */
  readonly outDir: string;
  readonly headless?: boolean;
  readonly signal?: AbortSignal;
}

export interface RejectedProposal {
  readonly task: Task;
  readonly reasons: string[];
}

export interface ExploreResult {
  readonly tasks: Task[];
  readonly rejected: RejectedProposal[];
  readonly trajectory: Trajectory;
}

/** Explore the shop once and return the proposals that survived verification. */
export async function explore(options: ExploreOptions): Promise<ExploreResult> {
  await fs.mkdir(path.join(options.outDir, 'evidence'), { recursive: true });
  const episodeId = `explore-${Date.now().toString(36)}`;
  const proposals: Proposal[] = [];
  const session = await BrowserSession.launch({
    episodeId,
    baseUrl: options.baseUrl,
    headless: options.headless ?? true,
  });
  let trajectory: Trajectory;
  try {
    await session.page.goto(options.baseUrl, { waitUntil: 'domcontentloaded' });
    const prompt = fillPlaceholders(await fs.readFile(PROMPT_PATH, 'utf-8'), {
      base_url: options.baseUrl,
      shop: options.shop,
      max_tasks: String(options.maxTasks),
      skills: options.skills.join(', '),
      personas:
        options.customers.length === 0
          ? '(none)'
          : options.customers.map((c) => `${c.id} (${c.first_name} ${c.last_name})`).join(', '),
    });
    const result = await options.runtime.run({
      cwd: options.outDir,
      systemPrompt: prompt,
      prompt: 'Start exploring now.',
      tools: [
        ...browserTools(session).filter((t) => t.name !== 'finish'),
        ...proposalTools(session, options.shop, proposals),
      ],
      model: options.model,
      signal: options.signal ?? new AbortController().signal,
      logDir: path.join(options.outDir, 'agent'),
    });
    trajectory = result.trajectory;
    if (result.status === 'error') {
      throw new Error(`explorer run failed: ${result.error ?? 'unknown error'}`);
    }
  } finally {
    await session.close();
  }
  await writeTrajectory(path.join(options.outDir, 'trajectory.json'), trajectory);

  const tasks: Task[] = [];
  const rejected: RejectedProposal[] = [];
  for (const proposal of proposals.slice(0, options.maxTasks)) {
    const verification = await verifyProposal(proposal, {
      baseUrl: options.baseUrl,
      episodeId: `${episodeId}-verify`,
      screenshotPath: path.join(options.outDir, 'evidence', `${proposal.task.id}.png`),
      ...(options.headless === undefined ? {} : { headless: options.headless }),
    });
    if (verification.ok) {
      tasks.push(withEvidence(proposal.task, verification.evidence));
    } else {
      rejected.push({ task: proposal.task, reasons: verification.reasons });
    }
  }
  await fs.writeFile(
    path.join(options.outDir, 'rejected.json'),
    `${JSON.stringify(rejected, null, 2)}\n`,
  );
  return { tasks, rejected, trajectory };
}
