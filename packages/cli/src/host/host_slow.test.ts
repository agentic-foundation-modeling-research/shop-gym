/**
 * End-to-end host check: seeds both templates, publishes them through
 * `publishShop` with the shop_backend fixture dataset, then runs the real
 * `host start` / `list` / `stop` path (including `pnpm install` + `pnpm build`
 * inside the published shop). Gated behind `SHOPGYM_SLOW_TESTS=1`.
 */
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { STOREFRONT_TEMPLATE_DIR, build, publish } from '@shop-gym/shop-arena';
import { afterAll, describe, expect, it } from 'vitest';

import { defaultHostDeps, listShops, startShop, stopShop } from './host.js';
import { pidAlive } from './process.js';
import { readState, shopRunDir } from './state.js';

const FIXTURE_DATA = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../shop_backend/tests/fixtures/sandbox_shop_v0',
);
const SHOP = 'fixture_shop';

/** Real `git` for fingerprinting; `pnpm` skipped because `host start` installs anyway. */
const seedRunner: build.CommandRunner = (argv, options) =>
  argv[0] === 'git'
    ? build.runCommand(argv, options)
    : Promise.resolve({ exitCode: 0, stdout: '', stderr: '', timedOut: false });

let repoRoot: string | undefined;

afterAll(async () => {
  if (repoRoot !== undefined) {
    await stopShop(repoRoot, SHOP);
  }
});

describe.skipIf(!process.env.SHOPGYM_SLOW_TESTS)(
  'host start/list/stop against a published shop',
  () => {
    it('serves /health on both processes and leaves nothing behind after stop', async () => {
      repoRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'host-slow-'));
      const runDir = path.join(repoRoot, 'run');
      const storefront = await build.seedTemplate({
        templateDir: STOREFRONT_TEMPLATE_DIR,
        destDir: path.join(runDir, 'artifact', 'storefront'),
        runner: seedRunner,
      });
      const backend = await build.seedBackend({
        destDir: path.join(runDir, 'artifact', 'backend'),
        runner: seedRunner,
      });
      const buildInfo: build.BuildRunInfo = {
        genBackend: false,
        backendPort: 0,
        backendUrl: '',
        templates: { storefront, backend },
      };
      await fs.writeFile(path.join(runDir, build.BUILD_JSON), JSON.stringify(buildInfo));
      await fs.writeFile(
        path.join(runDir, 'run.json'),
        JSON.stringify({ finalStatus: 'completed' }),
      );

      const shopDir = path.join(repoRoot, 'outputs', 'shops', SHOP);
      await publish.publishShop({ runDir, shopDir });
      await fs.cp(FIXTURE_DATA, path.join(shopDir, 'data'), { recursive: true });

      const state = await startShop({ repoRoot, shop: SHOP, force: false }, defaultHostDeps);
      expect((await fetch(`${state.backend.url}/health`)).ok).toBe(true);
      expect((await fetch(`${state.storefront.url}/health`)).ok).toBe(true);
      const page = await fetch(state.storefront.url);
      expect(page.ok).toBe(true);
      expect(await page.text()).toContain('<html');
      expect(await listShops(repoRoot, false)).toMatchObject([{ name: SHOP, status: 'running' }]);

      expect(await stopShop(repoRoot, SHOP)).toBe(true);
      expect(pidAlive(state.backend.pid)).toBe(false);
      expect(pidAlive(state.storefront.pid)).toBe(false);
      expect(await readState(shopRunDir(repoRoot, SHOP))).toBeUndefined();
      expect(await listShops(repoRoot, false)).toEqual([]);
    }, 900_000);
  },
);
