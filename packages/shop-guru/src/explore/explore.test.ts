import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { FakeRuntime } from '@shop-gym/agent/testing';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import {
  type Backend,
  type FakeStorefront,
  SHOP_PAGES,
  startBackend,
  startFakeStorefront,
} from '../testing/fixtures.js';
import { explore } from './explore.js';

let backend: Backend;
let shop: FakeStorefront;

beforeAll(async () => {
  backend = await startBackend();
  shop = await startFakeStorefront(SHOP_PAGES);
}, 60_000);

afterAll(async () => {
  await shop.close();
  await backend.server.close();
});

describe('explore', () => {
  it('keeps verified proposals, drops failing ones, and records evidence', async () => {
    const outDir = await fs.mkdtemp(path.join(os.tmpdir(), 'shopgym-guru-explore-'));
    const runtime = new FakeRuntime([
      {
        toolCalls: [
          { tool: 'navigate', arguments: { url: '/collections/dog-essentials' } },
          { tool: 'probe', arguments: { locator: '.product .title' } },
          {
            tool: 'propose_task',
            arguments: {
              skill: 'browse',
              goal: 'Find the tick collar in the dog range and stop on the collection page.',
              eval: [
                { type: 'url_match', url: '/collections/dog-essentials', rule: 'prefix' },
                {
                  type: 'locator_probe',
                  url: 'last',
                  locator: '.product .title',
                  required: { mustInclude: ['Anti Tick Collar'] },
                },
              ],
              verifyUrl: '/collections/dog-essentials',
            },
          },
          {
            tool: 'propose_task',
            arguments: {
              skill: 'exact',
              goal: 'Open the cat range.',
              eval: [{ type: 'url_match', url: '/collections/cat-care', rule: 'exact' }],
              verifyUrl: '/collections/cat-care',
            },
          },
          {
            tool: 'propose_task',
            arguments: {
              skill: 'exact',
              goal: 'Check the cart total.',
              eval: [
                {
                  type: 'locator_probe',
                  url: '/cart',
                  locator: '.nope',
                  required: { mustInclude: ['x'] },
                },
              ],
              verifyUrl: '/cart',
            },
          },
          {
            tool: 'propose_task',
            arguments: { skill: 'Bad Skill', goal: 'x', eval: [], verifyUrl: '/' },
          },
        ],
        reply: 'DONE',
      },
    ]);

    const result = await explore({
      runtime,
      model: { provider: 'fake', id: 'explorer' },
      shop: 'fixture',
      baseUrl: shop.url,
      skills: ['exact', 'browse'],
      customers: backend.data.customers,
      maxTasks: 5,
      outDir,
    });

    expect(result.tasks.map((t) => t.id)).toEqual(['fixture-explore-1']);
    expect(result.tasks[0]).toMatchObject({ source: 'explore', skill: 'browse' });
    expect(result.tasks[0]?.evidence).toMatchObject({
      url: '/collections/dog-essentials',
      probes: [{ locator: '.product .title', count: 2 }],
    });
    expect(result.rejected.map((r) => r.task.id)).toEqual([
      'fixture-explore-2',
      'fixture-explore-3',
    ]);
    expect(result.rejected[0]?.reasons[0]).toContain('not reachable');
    expect(result.rejected[1]?.reasons[0]).toContain('matched nothing');

    const screenshot = String(result.tasks[0]?.evidence?.screenshotPath);
    expect((await fs.stat(screenshot)).size).toBeGreaterThan(0);
    await fs.stat(path.join(outDir, 'trajectory.json'));
    await fs.stat(path.join(outDir, 'rejected.json'));

    const request = runtime.requests[0];
    expect(request?.tools.map((t) => t.name)).not.toContain('finish');
    expect(request?.tools.map((t) => t.name)).toContain('propose_task');
    expect(request?.systemPrompt).toContain(shop.url);
    expect(request?.systemPrompt).toContain('1 (Jane Doe)');
    const rejectedCall = result.trajectory.steps.find(
      (s) => s.kind === 'tool_result' && s.output.startsWith('Rejected: skill'),
    );
    expect(rejectedCall).toBeDefined();
  });
});
