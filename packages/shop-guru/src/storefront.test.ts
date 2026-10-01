/**
 * Episodes against the real storefront template over the sandbox backend.
 *
 * Gated by `SHOPGYM_SLOW_TESTS=1` because it installs and builds the
 * storefront template in a temp dir. The live block additionally needs
 * `SHOPGYM_LIVE=1` and model credentials in `.env`; it drives one seed task
 * with the pi browser agent.
 */

import { type ChildProcess, execFileSync, spawn } from 'node:child_process';
import { cpSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { TrajectoryRecorder, sha256 } from '@shop-gym/agent';
import { loadCredentials } from '@shop-gym/core';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { readBenchmarks } from './benchmarks.js';
import { type GuruConfig, parseGuruConfig } from './config.js';
import { createPiBrowserAgent, createPiJudge } from './pi.js';
import { build } from './pipeline.js';
import type { AgentUnderTest, SolveEpisode, SolveOutcome } from './solve/agent.js';
import { runEpisode } from './solve/solve.js';
import { type Backend, FIXTURE_DIR, startBackend } from './testing/fixtures.js';

/** Storefront template location; override to test another copy. */
const STOREFRONT_TEMPLATE_DIR =
  process.env.SHOPGYM_STOREFRONT_TEMPLATE_DIR ??
  fileURLToPath(new URL('../../shop-arena/templates/storefront', import.meta.url));
const REPO_ROOT = fileURLToPath(new URL('../../..', import.meta.url));
const BOOT_TIMEOUT_MS = 30_000;
const MODEL = { provider: 'fake', id: 'scripted' };
/** Live model as `<provider>/<id>`, matching the agent package's live tests. */
const [LIVE_PROVIDER = 'openai', LIVE_MODEL_ID = 'gpt-5.5'] = (
  process.env.SHOPGYM_LIVE_MODEL ?? 'openai/gpt-5.5'
).split('/', 2);

let workDir: string;
let backend: Backend;
let storefront: ChildProcess | undefined;
let config: GuruConfig;

/** Agent that drives the page directly and finishes with what it did. */
function scripted(name: string, act: (episode: SolveEpisode) => Promise<string>): AgentUnderTest {
  return {
    name,
    model: MODEL,
    async run(episode): Promise<SolveOutcome> {
      const recorder = new TrajectoryRecorder(name, MODEL, sha256(episode.task.goal));
      const answer = await act(episode);
      episode.session.finished = { answer, infeasible: false };
      return { trajectory: recorder.finish(), status: 'completed' };
    },
  };
}

describe.skipIf(!process.env.SHOPGYM_SLOW_TESTS)('storefront episodes', () => {
  beforeAll(async () => {
    workDir = mkdtempSync(path.join(tmpdir(), 'shopgym-guru-storefront-'));
    const templateDir = path.join(workDir, 'storefront');
    copyTrackedFiles(STOREFRONT_TEMPLATE_DIR, templateDir);
    execFileSync('pnpm', ['install', '--ignore-workspace', '--frozen-lockfile'], {
      cwd: templateDir,
      stdio: 'pipe',
    });
    execFileSync('pnpm', ['build'], { cwd: templateDir, stdio: 'pipe' });

    backend = await startBackend();
    const storefrontPort = await freePort();
    const shopUrl = `http://127.0.0.1:${storefrontPort}`;
    storefront = spawn('node', ['server.mjs'], {
      cwd: templateDir,
      stdio: 'pipe',
      env: {
        ...process.env,
        NODE_ENV: 'production',
        PORT: String(storefrontPort),
        PUBLIC_STORE_DOMAIN: backend.url,
        SESSION_SECRET: 'guru-test-secret',
      },
    });
    await waitForHealth(`${shopUrl}/health`);

    config = parseGuruConfig({
      shop: 'fixture',
      shopUrl,
      backendUrl: backend.url,
      dataDir: FIXTURE_DIR,
      outDir: path.join(workDir, 'out'),
      model: { provider: LIVE_PROVIDER, id: LIVE_MODEL_ID },
      caps: { exact: 1, account: 1, checkout: 1, order_history: 1 },
      episodeTimeoutMs: 300_000,
    });
    await build(config);
  }, 600_000);

  afterAll(async () => {
    storefront?.kill();
    await backend?.server.close();
    if (workDir) rmSync(workDir, { recursive: true, force: true });
  });

  async function benchmarkTask(skill: string) {
    const [task] = await readBenchmarks(path.join(config.outDir, config.shop), [skill]);
    if (task === undefined) throw new Error(`no ${skill} task on the fixture`);
    return task;
  }

  it('logs the persona in through the storefront for an account task', async () => {
    const task = await benchmarkTask('account');
    const agent = scripted('page-reader', async ({ session, baseUrl }) => {
      await session.page.goto(`${baseUrl}/account`);
      const profile = await session.page.innerText('body');
      await session.page.goto(`${baseUrl}/account/addresses`);
      return `${profile}\n${await session.page.innerText('body')}`;
    });
    const result = await runEpisode(task, {
      agent,
      baseUrl: config.shopUrl,
      backendUrl: config.backendUrl,
      customers: backend.data.customers,
      runDir: path.join(workDir, 'runs', 'account'),
      grade: true,
      episodeTimeoutMs: 60_000,
    });
    expect(result.status).toBe('completed');
    expect(result.finalUrl).toBe(`${config.shopUrl}/account/addresses`);
    expect(result.checks.map((c) => c.detail)).toEqual(['matched']);
    expect(result.passed).toBe(true);
  }, 120_000);

  it('places the pre-filled cart order and passes the state_check', async () => {
    const task = await benchmarkTask('checkout');
    const persona = backend.data.customers[0];
    const address = persona?.addresses[0];
    if (persona === undefined || address === undefined) throw new Error('fixture persona missing');
    const agent = scripted('form-poster', async ({ session, baseUrl }) => {
      const response = await session.page.request.post(`${baseUrl}/checkout`, {
        form: {
          email: persona.email,
          firstName: address.first_name ?? '',
          lastName: address.last_name ?? '',
          address1: address.address1,
          city: address.city,
          province: address.province ?? '',
          country: address.country,
          zip: address.zip,
          shippingMethodHandle: 'standard',
          paymentMethodHandle: 'card',
        },
        maxRedirects: 0,
      });
      const location = response.headers().location ?? '/';
      await session.page.goto(new URL(location, baseUrl).toString());
      return location;
    });
    const result = await runEpisode(task, {
      agent,
      baseUrl: config.shopUrl,
      backendUrl: config.backendUrl,
      customers: backend.data.customers,
      runDir: path.join(workDir, 'runs', 'checkout'),
      grade: true,
      episodeTimeoutMs: 60_000,
    });
    expect(result.status).toBe('completed');
    expect(result.answer).toMatch(/^\/account\/orders\/\d+$/);
    expect(result.checks[0]).toMatchObject({ check: { type: 'state_check' }, passed: true });
    expect(result.passed).toBe(true);
  }, 120_000);

  it.skipIf(!process.env.SHOPGYM_LIVE)(
    'solves an exact search task with the pi browser agent',
    async () => {
      const task = await benchmarkTask('exact');
      const credentials = loadCredentials(REPO_ROOT, process.env);
      const result = await runEpisode(task, {
        agent: createPiBrowserAgent(config, credentials),
        baseUrl: config.shopUrl,
        backendUrl: config.backendUrl,
        customers: backend.data.customers,
        runDir: path.join(workDir, 'runs', 'live'),
        grade: true,
        judge: createPiJudge(config, credentials),
        episodeTimeoutMs: config.episodeTimeoutMs,
      });
      console.log(
        'live episode',
        JSON.stringify({
          status: result.status,
          passed: result.passed,
          checks: result.checks,
          usage: result.usage,
        }),
      );
      expect(result.status).toBe('completed');
      expect(result.passed).toBe(true);
    },
    600_000,
  );
});

function copyTrackedFiles(sourceDir: string, targetDir: string): void {
  const listing = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard'], {
    cwd: sourceDir,
    encoding: 'utf8',
  });
  for (const relative of listing.split('\n').filter((line) => line.length > 0)) {
    const target = path.join(targetDir, relative);
    mkdirSync(path.dirname(target), { recursive: true });
    cpSync(path.join(sourceDir, relative), target);
  }
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (address === null || typeof address === 'string') {
        reject(new Error('Could not allocate a port.'));
        return;
      }
      server.close(() => resolve(address.port));
    });
  });
}

async function waitForHealth(url: string): Promise<void> {
  const deadline = Date.now() + BOOT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Not listening yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for ${url}`);
}
