import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { FakeRuntime } from '@shop-gym/agent/testing';
import { createSandboxServer, loadShopData } from '@shop-gym/shop-backend';
import { beforeEach, describe, expect, it } from 'vitest';

import { STOREFRONT_TEMPLATE_DIR } from '../../templates.js';
import { stubStorefrontLaunch } from '../testing.js';
import { BUILD_JSON, type BuildRunInfo, CHECKPOINTS_DIRNAME, runBuildLoop } from './build_loop.js';
import { ArtifactCheckpoints } from './checkpoints.js';
import { defaultBackendTemplateDir } from './seed.js';
import type { SidecarLaunch, SidecarLaunchOptions } from './sidecar.js';
import type { CommandRunner } from './verifiers/subprocess.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');
const MODEL = { provider: 'fake', id: 'scripted' };
const DASH = '\u2014'; // the harness plan grammar's task separator
const STOREFRONT_FILES = [
  'package.json',
  'tsconfig.json',
  'app/lib/queries.ts',
  'app/routes/home.tsx',
];
const BACKEND_FILES = ['package.json', 'tsconfig.json', 'src/schema/shop.ts', 'src/data/schema.ts'];
const PLAN = [
  '# Plan - test',
  '',
  '## Tasks',
  '',
  `- [ ] gen_backend ${DASH} add a loyalty query [priority: 10]`,
  `- [ ] gen_homepage ${DASH} render the homepage [priority: 7]`,
  '',
  '## Omitted Areas',
  '',
  '- (none)',
  '',
].join('\n');

let root: string;
let seedDir: string;
let commands: string[][];
let launches: SidecarLaunchOptions[];

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'build-loop-'));
  seedDir = path.join(root, 'seed');
  await fs.cp(FIXTURE_DIR, path.join(seedDir, 'data'), { recursive: true });
  await fs.mkdir(path.join(seedDir, 'manual'));
  await fs.writeFile(path.join(seedDir, 'manual', 'manual.md'), '# manual\n');
  commands = [];
  launches = [];
});

/** `git ls-files` answers a fixed subset per template; every other command succeeds. */
const fakeRunner: CommandRunner = async (argv, options) => {
  commands.push([...argv]);
  if (argv[0] === 'git' && argv[1] === 'ls-files') {
    const files = options.cwd === STOREFRONT_TEMPLATE_DIR ? STOREFRONT_FILES : BACKEND_FILES;
    return { exitCode: 0, stdout: `${files.join('\0')}\0`, stderr: '', timedOut: false };
  }
  if (argv[0] === 'git') {
    return { exitCode: 0, stdout: 'deadbeef\n', stderr: '', timedOut: false };
  }
  return { exitCode: 0, stdout: '', stderr: '', timedOut: false };
};

/** Serve the run's dataset in-process on the requested port, like the real CLI would. */
const inProcessLaunch: SidecarLaunch = async (options) => {
  launches.push(options);
  const server = createSandboxServer({
    data: loadShopData(options.dataDir),
    dataDir: options.dataDir,
    port: options.port,
  });
  await server.listen();
  return { stop: () => server.close() };
};

function plannerScript() {
  return { writeFiles: { 'plan.md': PLAN } };
}

describe('runBuildLoop', () => {
  it('seeds both templates, runs the sidecar, and dispatches the verifier set', async () => {
    const runDir = path.join(root, 'run');
    const runtime = new FakeRuntime([
      plannerScript(),
      {
        writeFiles: {
          'artifact/backend/src/schema/shop.ts': '# loyalty\n',
          'plan.md': PLAN.replace('- [ ] gen_backend', '- [x] gen_backend'),
        },
      },
      {
        writeFiles: {
          'artifact/storefront/app/routes/home.tsx':
            'const Q = `#graphql\n query Home { shop { nope } }`;\n',
          'plan.md': PLAN.replace('- [ ] gen_backend', '- [x] gen_backend').replace(
            '- [ ] gen_homepage',
            '- [x] gen_homepage',
          ),
        },
      },
    ]);
    const events: string[] = [];
    const result = await runBuildLoop({
      runDir,
      seedDir,
      storefrontTemplateDir: STOREFRONT_TEMPLATE_DIR,
      backendTemplateDir: defaultBackendTemplateDir(),
      genBackend: true,
      runtime,
      model: MODEL,
      tools: [],
      maxIters: 2,
      timeoutMs: 60_000,
      commandRunner: fakeRunner,
      sidecarLaunch: inProcessLaunch,
      storefrontLaunch: stubStorefrontLaunch,
      onEvent: (iterId, event) => events.push(`${iterId}:${event.kind}`),
    });

    expect(result.finalStatus).toBe('budget_exhausted');
    expect(result.planIterCount).toBe(1);
    expect(result.execIterCount).toBe(2);
    expect(result.build.genBackend).toBe(true);
    expect(result.build.backendUrl).toBe(`http://127.0.0.1:${result.build.backendPort}`);
    expect(result.build.templates.backend.name).toBe('shop_backend');
    expect(result.build.templates.storefront.name).toBe('storefront');

    const buildJson = JSON.parse(
      await fs.readFile(path.join(runDir, BUILD_JSON), 'utf-8'),
    ) as BuildRunInfo;
    expect(buildJson.backendPort).toBe(result.build.backendPort);
    const env = await fs.readFile(path.join(runDir, 'artifact', 'storefront', '.env'), 'utf-8');
    expect(env).toContain(`PUBLIC_STORE_DOMAIN=${result.build.backendUrl}`);
    await expect(
      fs.stat(path.join(runDir, 'artifact', 'backend', 'template.json')),
    ).resolves.toBeDefined();
    await expect(
      fs.stat(path.join(runDir, 'artifact', 'backend', 'src', 'data', 'schema.ts')),
    ).resolves.toBeDefined();
    await expect(
      fs.stat(path.join(runDir, 'artifact', 'storefront', 'app', 'lib', 'queries.ts')),
    ).resolves.toBeDefined();

    const agentsMd = await fs.readFile(path.join(runDir, 'AGENTS.md'), 'utf-8');
    expect(agentsMd).toContain(result.build.backendUrl);
    expect(runtime.requests[0]?.cwd).toBe(runDir);

    const installs = commands.filter((argv) => argv[0] === 'pnpm' && argv[1] === 'install');
    expect(installs).toHaveLength(2);
    expect(commands).toContainEqual(['pnpm', 'typecheck']);
    expect(commands).toContainEqual(['pnpm', 'test']);
    expect(commands).toContainEqual(['pnpm', 'exec', 'vitest', 'run', 'tests/contract']);

    const byIter = (iterId: string) =>
      result.verifierRuns
        .filter((run) => run.iterId === iterId)
        .map((run) => [run.name, run.verdict]);
    expect(byIter('exec-0001')).toEqual([
      ['owned_files', 'pass'],
      ['backend_typecheck', 'pass'],
      ['backend_test', 'pass'],
      ['sandbox_contract', 'pass'],
      ['data_in_use', 'pass'],
    ]);
    expect(byIter('exec-0002')).toEqual([
      ['owned_files', 'pass'],
      ['typecheck', 'pass'],
      ['build', 'pass'],
      ['routes_200', 'pass'],
      ['data_in_use', 'fail'],
    ]);
    expect(commands).toContainEqual(['pnpm', 'build']);
    expect(result.tasksFinal.map((task) => [task.id, task.status])).toEqual([
      ['gen_backend', 'done'],
      ['gen_homepage', 'in_progress'],
    ]);
    const feedback = await fs.readFile(
      path.join(runDir, 'iters', 'exec-0002', 'checks', 'verifiers', 'feedback.md'),
      'utf-8',
    );
    expect(feedback).toContain('Cannot query field "nope"');

    expect(launches).toHaveLength(2);
    expect(launches.every((l) => l.dataDir === path.join(runDir, 'artifact', 'data'))).toBe(true);
    expect(events).toContain('plan:message');
  });

  it('rolls an abandoned iteration back so the next task is not blamed for it', async () => {
    const runDir = path.join(root, 'run');
    const schema = path.join(runDir, 'artifact', 'backend', 'src', 'schema');
    const runtime = new FakeRuntime([
      plannerScript(),
      {
        writeFiles: {
          'artifact/backend/src/schema/shop.ts': 'half done',
          'artifact/backend/src/schema/loyalty.ts': 'half done',
        },
        status: 'aborted',
      },
      {
        writeFiles: {
          'artifact/storefront/app/routes/home.tsx': 'export default function Home() {}\n',
          'plan.md': PLAN.replace('- [ ] gen_homepage', '- [x] gen_homepage'),
        },
      },
    ]);
    const result = await runBuildLoop({
      runDir,
      seedDir,
      storefrontTemplateDir: STOREFRONT_TEMPLATE_DIR,
      backendTemplateDir: defaultBackendTemplateDir(),
      genBackend: true,
      runtime,
      model: MODEL,
      tools: [],
      maxIters: 2,
      timeoutMs: 60_000,
      commandRunner: fakeRunner,
      sidecarLaunch: inProcessLaunch,
      storefrontLaunch: stubStorefrontLaunch,
    });

    expect(result.finalStatus).toBe('timeout');
    expect(await fs.readFile(path.join(schema, 'shop.ts'), 'utf-8')).toBe(
      await fs.readFile(
        path.join(defaultBackendTemplateDir(), 'src', 'schema', 'shop.ts'),
        'utf-8',
      ),
    );
    await expect(fs.stat(path.join(schema, 'loyalty.ts'))).rejects.toThrow();
    const ownedFiles = JSON.parse(
      await fs.readFile(
        path.join(runDir, 'iters', 'exec-0001', 'checks', 'verifiers', 'owned_files.json'),
        'utf-8',
      ),
    ) as { taskId: string; verdict: string; details: { changedPaths: string[] } };
    expect(ownedFiles).toMatchObject({
      taskId: 'gen_homepage',
      verdict: 'pass',
      details: { changedPaths: ['storefront/app/routes/home.tsx'] },
    });
    const checkpoints = new ArtifactCheckpoints({
      gitDir: path.join(runDir, CHECKPOINTS_DIRNAME),
      workTree: path.join(runDir, 'artifact'),
    });
    expect(await checkpoints.changedPaths()).toEqual([]);
  });

  it('resumes a run with the recorded port and flags', async () => {
    const runDir = path.join(root, 'run');
    const base = {
      runDir,
      seedDir,
      storefrontTemplateDir: STOREFRONT_TEMPLATE_DIR,
      backendTemplateDir: defaultBackendTemplateDir(),
      genBackend: false,
      model: MODEL,
      tools: [] as const,
      maxIters: 1,
      timeoutMs: 60_000,
      commandRunner: fakeRunner,
      sidecarLaunch: inProcessLaunch,
    };
    const first = await runBuildLoop({
      ...base,
      runtime: new FakeRuntime([plannerScript(), { writeFiles: { 'plan.md': PLAN } }]),
    });
    expect(first.finalStatus).toBe('budget_exhausted');
    const second = await runBuildLoop({
      ...base,
      genBackend: true,
      runtime: new FakeRuntime([{ writeFiles: { 'plan.md': PLAN } }]),
    });
    expect(second.build.backendPort).toBe(first.build.backendPort);
    expect(second.build.genBackend).toBe(false);
    expect(second.planIterCount).toBe(1);
    expect(second.execIterCount).toBe(2);
    expect(commands.filter((argv) => argv[1] === 'install')).toHaveLength(2);
  });
});

// Real `git ls-files` + `pnpm install` for both templates, a real `tsx` sidecar process, and the
// real backend typecheck / test / contract suites. Run with `SHOPGYM_SLOW_TESTS=1 pnpm test`.
describe.skipIf(!process.env.SHOPGYM_SLOW_TESTS)('runBuildLoop (slow, real processes)', () => {
  it('seeds, boots the backend, and passes every verifier on an untouched template', async () => {
    const runDir = path.join(root, 'run');
    const runtime = new FakeRuntime([
      plannerScript(),
      { writeFiles: { 'plan.md': PLAN.replace('- [ ] gen_backend', '- [x] gen_backend') } },
    ]);
    const result = await runBuildLoop({
      runDir,
      seedDir,
      storefrontTemplateDir: STOREFRONT_TEMPLATE_DIR,
      backendTemplateDir: defaultBackendTemplateDir(),
      genBackend: true,
      runtime,
      model: MODEL,
      tools: [],
      maxIters: 1,
      timeoutMs: 600_000,
    });
    expect(result.execIterCount).toBe(1);
    expect(result.verifierRuns.map((run) => [run.name, run.verdict])).toEqual([
      ['owned_files', 'pass'],
      ['backend_typecheck', 'pass'],
      ['backend_test', 'pass'],
      ['sandbox_contract', 'pass'],
      ['data_in_use', 'pass'],
    ]);
    expect(result.tasksFinal.find((task) => task.id === 'gen_backend')?.status).toBe('done');
    const health = await fs.readFile(path.join(runDir, 'sidecar.log'), 'utf-8');
    expect(health.length).toBeGreaterThan(0);
    await expect(
      fs.stat(path.join(runDir, 'artifact', 'storefront', 'node_modules', '.pnpm')),
    ).resolves.toBeDefined();
  }, 900_000);
});
