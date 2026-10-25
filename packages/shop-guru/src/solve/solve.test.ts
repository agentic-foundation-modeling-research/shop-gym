import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { TrajectoryRecorder, readTrajectory, sha256 } from '@shop-gym/agent';
import { FakeRuntime, type FakeScript } from '@shop-gym/agent/testing';
import type { Task } from '@shop-gym/core';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import {
  type Backend,
  type FakeStorefront,
  SHOP_PAGES,
  startBackend,
  startFakeStorefront,
} from '../testing/fixtures.js';
import { type AgentUnderTest, RuntimeBrowserAgent, type SolveEpisode } from './agent.js';
import { type EpisodeOptions, runEpisode, runEpisodes } from './solve.js';

const MODEL = { provider: 'fake', id: 'solver' };

let backend: Backend;
let shop: FakeStorefront;
let runDir: string;

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 'fixture-exact-1',
    shop: 'fixture',
    skill: 'exact',
    goal: 'Report the cart total.',
    eval: [
      { type: 'string_match', mustInclude: ['29.98'] },
      { type: 'url_match', url: '/cart', rule: 'exact' },
      {
        type: 'locator_probe',
        url: 'last',
        locator: '.total',
        required: { mustInclude: ['29.98'] },
      },
      { type: 'state_check', path: '/carts', match: 'equals', value: [] },
    ],
    source: 'seed',
    ...overrides,
  };
}

function scriptedAgent(...scripts: FakeScript[]): RuntimeBrowserAgent {
  return new RuntimeBrowserAgent({
    runtime: new FakeRuntime(scripts),
    model: MODEL,
    name: 'scripted',
  });
}

function options(agent: AgentUnderTest, overrides: Partial<EpisodeOptions> = {}): EpisodeOptions {
  return {
    agent,
    baseUrl: shop.url,
    backendUrl: backend.url,
    customers: backend.data.customers,
    runDir,
    grade: true,
    episodeTimeoutMs: 20_000,
    ...overrides,
  };
}

beforeAll(async () => {
  backend = await startBackend();
  shop = await startFakeStorefront(SHOP_PAGES);
}, 60_000);

beforeEach(async () => {
  runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'shopgym-guru-solve-'));
  shop.seen.length = 0;
});

afterAll(async () => {
  await shop.close();
  await backend.server.close();
});

describe('runEpisode', () => {
  it('solves, grades, and writes artifacts for a completed episode', async () => {
    const agent = scriptedAgent({
      toolCalls: [
        { tool: 'navigate', arguments: { url: '/cart' } },
        { tool: 'finish', arguments: { answer: 'Total: $29.98' } },
      ],
    });
    const result = await runEpisode(task(), options(agent));

    expect(result).toMatchObject({
      taskId: 'fixture-exact-1',
      status: 'completed',
      answer: 'Total: $29.98',
      finalUrl: `${shop.url}/cart`,
      passed: true,
      agent: { name: 'scripted', model: 'solver' },
      trajectoryPath: path.join('episodes', 'fixture-exact-1', 'trajectory.json'),
    });
    expect(result.checks).toHaveLength(4);
    expect(result.usage.input).toBe(10);
    expect(result.durationMs).toBeGreaterThanOrEqual(0);

    const episodeDir = path.join(runDir, 'episodes', 'fixture-exact-1');
    const trajectory = await readTrajectory(path.join(episodeDir, 'trajectory.json'));
    expect(trajectory.steps.some((s) => s.kind === 'tool_call' && s.tool === 'finish')).toBe(true);
    expect((await fs.stat(path.join(episodeDir, 'final.png'))).size).toBeGreaterThan(0);
    expect(JSON.parse(await fs.readFile(path.join(episodeDir, 'result.json'), 'utf-8'))).toEqual(
      result,
    );

    // Every storefront request carried the episode header.
    expect(shop.seen.length).toBeGreaterThan(0);
    expect(shop.seen.every((r) => r.episode?.startsWith('fixture-exact-1-'))).toBe(true);
  });

  it('ends the episode when finish is called and ignores later tool calls', async () => {
    const agent = scriptedAgent({
      toolCalls: [
        { tool: 'finish', arguments: { answer: 'done' } },
        { tool: 'navigate', arguments: { url: '/cart' } },
      ],
    });
    const result = await runEpisode(task({ eval: [] }), options(agent));
    expect(result.status).toBe('completed');
    expect(result.finalUrl).toBe(`${shop.url}/`);
    expect(result.passed).toBe(true);
  });

  it('does not offer the evaluate tool to the agent', async () => {
    const runtime = new FakeRuntime([{ toolCalls: [{ tool: 'finish', arguments: {} }] }]);
    const agent = new RuntimeBrowserAgent({ runtime, model: MODEL });
    await runEpisode(task({ eval: [] }), options(agent));
    const names = runtime.requests[0]?.tools.map((t) => t.name) ?? [];
    expect(names).toContain('snapshot');
    expect(names).not.toContain('evaluate');
    expect(runtime.requests[0]?.systemPrompt).toContain(shop.url);
    expect(runtime.requests[0]?.prompt).toBe('Report the cart total.');
  });

  it('applies setup through the storefront before the agent starts', async () => {
    const agent = scriptedAgent({ toolCalls: [{ tool: 'finish', arguments: { answer: 'ok' } }] });
    const result = await runEpisode(
      task({ eval: [], setup: { login: '1', cart: [{ variantId: 47642512195758, quantity: 2 }] } }),
      options(agent),
    );
    expect(result.status).toBe('completed');
    const posts = shop.seen.filter((r) => r.method === 'POST');
    expect(posts.map((r) => r.path)).toEqual(['/cart', '/account/login']);
    expect(posts[0]?.body).toContain(
      'merchandiseId=gid%3A%2F%2Fshopify%2FProductVariant%2F47642512195758',
    );
    expect(posts[0]?.body).toContain('quantity=2');
    expect(posts[1]?.body).toContain('email=jane.doe%40example.com');
    const home = shop.seen.find((r) => r.method === 'GET' && r.path === '/');
    expect(home?.cookie).toContain('__shop_gym_session=fake-session');
  });

  it('reports a failed setup as an error without running the agent', async () => {
    const runtime = new FakeRuntime([]);
    const agent = new RuntimeBrowserAgent({ runtime, model: MODEL });
    const result = await runEpisode(task({ eval: [], setup: { login: '404' } }), options(agent));
    expect(result.status).toBe('error');
    expect(result.error).toContain('unknown persona');
    expect(runtime.requests).toHaveLength(0);
    expect(result.trajectoryPath).toBeUndefined();
  });

  it('marks infeasible and error outcomes', async () => {
    const infeasible = await runEpisode(
      task(),
      options(
        scriptedAgent({
          toolCalls: [
            { tool: 'finish', arguments: { infeasible: true, reason: 'no such product' } },
          ],
        }),
      ),
    );
    expect(infeasible).toMatchObject({ status: 'infeasible', answer: null, passed: false });

    const errored = await runEpisode(
      task(),
      options(scriptedAgent({ status: 'error', error: 'provider down' })),
    );
    expect(errored).toMatchObject({
      status: 'error',
      error: 'provider down',
      passed: false,
      checks: [],
    });
  });

  it('aborts an agent that outlives the episode timeout', async () => {
    const waiting: AgentUnderTest = {
      name: 'waiting',
      model: MODEL,
      async run(episode: SolveEpisode) {
        await new Promise<void>((resolve) =>
          episode.signal.addEventListener('abort', () => resolve(), { once: true }),
        );
        const recorder = new TrajectoryRecorder('waiting', MODEL, sha256(episode.task.goal));
        return { trajectory: recorder.finish(), status: 'aborted' as const };
      },
    };
    const result = await runEpisode(
      task({ eval: [] }),
      options(waiting, { episodeTimeoutMs: 200 }),
    );
    expect(result.status).toBe('aborted');
    expect(result.passed).toBe(false);
  });

  it('skips grading when grade is false', async () => {
    const agent = scriptedAgent({ toolCalls: [{ tool: 'finish', arguments: { answer: 'x' } }] });
    const result = await runEpisode(task(), options(agent, { grade: false }));
    expect(result).toMatchObject({ status: 'completed', passed: false, checks: [] });
  });
});

describe('runEpisodes', () => {
  it('keeps task order with a concurrency pool', async () => {
    const tasks = [1, 2, 3].map((n) => task({ id: `fixture-exact-${n}`, eval: [] }));
    const scripts = tasks.map(() => ({
      toolCalls: [{ tool: 'finish', arguments: { answer: 'x' } }],
    }));
    const results = await runEpisodes(tasks, options(scriptedAgent(...scripts)), 2);
    expect(results.map((r) => r.taskId)).toEqual([
      'fixture-exact-1',
      'fixture-exact-2',
      'fixture-exact-3',
    ]);
    expect(results.every((r) => r.status === 'completed')).toBe(true);
  });
});
