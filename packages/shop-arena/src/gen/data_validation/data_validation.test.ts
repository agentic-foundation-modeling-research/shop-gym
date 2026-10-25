import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { createSandboxServer, loadShopData } from '@shop-gym/shop-backend';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { defaultBackendTemplateDir } from '../build/seed.js';
import { type SidecarLaunch, spawnSidecar } from '../build/sidecar.js';
import { runHostingSmoke } from './hosting_check.js';
import { DataValidationError, runDataValidation } from './index.js';
import { checkDataset } from './schema_check.js';

const FIXTURE_DIR = path.join(defaultBackendTemplateDir(), 'tests', 'fixtures', 'sandbox_shop_v0');

const inProcessLaunch: SidecarLaunch = async (options) => {
  const server = createSandboxServer({
    data: loadShopData(options.dataDir),
    dataDir: options.dataDir,
    port: options.port,
  });
  await server.listen();
  return { stop: () => server.close() };
};

let root: string;
let dataDir: string;

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'data-validation-'));
  dataDir = path.join(root, 'data');
  await fs.cp(FIXTURE_DIR, dataDir, { recursive: true });
  // The fixture references image files it does not ship; materialise them from pixel.png.
  const products = JSON.parse(await fs.readFile(path.join(dataDir, 'products.json'), 'utf-8')) as {
    images: { src: string }[];
  }[];
  for (const src of products.flatMap((p) => p.images.map((i) => i.src))) {
    const target = path.join(dataDir, 'images', src);
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.copyFile(path.join(dataDir, 'images', 'pixel.png'), target);
  }
});

afterEach(async () => {
  await fs.rm(root, { recursive: true, force: true });
});

async function editJson(name: string, edit: (value: never) => unknown): Promise<void> {
  const file = path.join(dataDir, name);
  const value = JSON.parse(await fs.readFile(file, 'utf-8')) as never;
  await fs.writeFile(file, JSON.stringify(edit(value)));
}

describe('checkDataset', () => {
  it('passes on the backend fixture', async () => {
    expect(await checkDataset(dataDir)).toEqual([]);
  });

  it('reports dangling variant ids in orders and inventory', async () => {
    await editJson('orders.json', (orders: { line_items: { variant_id: number }[] }[]) => {
      const first = orders[0];
      if (first?.line_items[0] !== undefined) first.line_items[0].variant_id = 999999;
      return orders;
    });
    await editJson('inventory.json', (inv: Record<string, unknown>) => ({
      ...inv,
      '424242': { quantity_available: 1 },
    }));
    const problems = await checkDataset(dataDir);
    expect(problems.some((p) => p.startsWith('orders.json') && p.includes('999999'))).toBe(true);
    expect(problems.some((p) => p.startsWith('inventory.json') && p.includes('424242'))).toBe(true);
  });

  it('reports unknown collection members, navigation targets, and missing images', async () => {
    await editJson('collections.json', (cols: { product_handles: string[] }[]) => {
      cols[0]?.product_handles.push('ghost-product');
      return cols;
    });
    await editJson('navigation.json', (nav: Record<string, unknown[]>) => ({
      ...nav,
      'main-menu': [
        ...(nav['main-menu'] ?? []),
        { title: 'Ghost', url: '/collections/ghost', type: 'COLLECTION', children: [] },
      ],
    }));
    await editJson('products.json', (products: { images: { src: string }[] }[]) => {
      products[0]?.images.push({
        ...(products[0]?.images[0] ?? { src: '' }),
        id: 1,
        src: 'missing.png',
        position: 9,
      } as never);
      return products;
    });
    const problems = await checkDataset(dataDir);
    expect(problems.some((p) => p.includes('ghost-product'))).toBe(true);
    expect(problems.some((p) => p.includes('/collections/ghost'))).toBe(true);
    expect(problems.some((p) => p.includes('missing.png'))).toBe(true);
  });

  it('reports a file that fails the backend schema', async () => {
    await fs.writeFile(path.join(dataDir, 'store.json'), JSON.stringify({ name: 'x' }));
    const problems = await checkDataset(dataDir);
    expect(problems[0]).toMatch(/^store\.json/);
  });
});

describe('runHostingSmoke', () => {
  it('runs the fixed query set against an in-process backend', async () => {
    const result = await runHostingSmoke({
      dataDir,
      backendDir: defaultBackendTemplateDir(),
      logPath: path.join(root, 'sidecar.log'),
      launch: inProcessLaunch,
    });
    expect(result.checks.map((c) => c.name)).toEqual([
      'shop',
      'products',
      'collection',
      'search',
      'image',
      'cart_lifecycle',
    ]);
    expect(result.checks.filter((c) => !c.ok)).toEqual([]);
    expect(result.checks.at(-1)?.detail).toContain('as jane.doe@example.com');
  });

  it.skipIf(!process.env.SHOPGYM_SLOW_TESTS)(
    'boots the pristine backend template as a subprocess',
    async () => {
      const result = await runHostingSmoke({
        dataDir,
        backendDir: defaultBackendTemplateDir(),
        logPath: path.join(root, 'sidecar.log'),
        launch: spawnSidecar,
      });
      expect(result.checks.filter((c) => !c.ok)).toEqual([]);
    },
    120_000,
  );
});

describe('runDataValidation', () => {
  it('writes the report and throws a readable error on failure', async () => {
    const shopDir = root;
    await editJson('orders.json', (orders: { line_items: { variant_id: number }[] }[]) => {
      const first = orders[0];
      if (first?.line_items[0] !== undefined) first.line_items[0].variant_id = 999999;
      return orders;
    });
    const log: string[] = [];
    await expect(
      runDataValidation({
        outDir: shopDir,
        context: { sidecarLaunch: inProcessLaunch } as never,
        log: (l) => log.push(l),
        signal: new AbortController().signal,
      }),
    ).rejects.toSatisfy(
      (err: unknown) => err instanceof DataValidationError && /999999/.test(err.message),
    );
    const report = JSON.parse(
      await fs.readFile(path.join(shopDir, 'data_validation.json'), 'utf-8'),
    );
    expect(report.ok).toBe(false);
    expect(report.hosting).toBeNull();
  });
});
