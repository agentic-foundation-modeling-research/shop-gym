import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import { PublishError, publishShop, readShopManifest } from './publish.js';

let runDir: string;
let shopDir: string;

const FINGERPRINT = (name: string) => ({
  name,
  commit: 'abc123',
  dirty: name === 'storefront',
  contentHash: `hash-${name}`,
  files: { 'package.json': 'f1' },
  seededAt: '2026-09-30T00:00:00.000Z',
});

async function write(file: string, content = 'x\n'): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, content);
}

beforeEach(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'publish-'));
  runDir = path.join(root, 'runs', 'build');
  shopDir = path.join(root, 'shops', 'sample-shop');
  const artifact = path.join(runDir, 'artifact');
  await write(
    path.join(artifact, 'storefront', 'template.json'),
    JSON.stringify(FINGERPRINT('storefront')),
  );
  await write(path.join(artifact, 'storefront', 'app', 'root.tsx'));
  await write(path.join(artifact, 'storefront', 'app', 'routes', 'home.tsx'));
  await write(
    path.join(artifact, 'storefront', '.env'),
    'PUBLIC_STORE_DOMAIN=http://127.0.0.1:1\n',
  );
  await write(path.join(artifact, 'storefront', 'node_modules', 'react', 'index.js'));
  await write(path.join(artifact, 'storefront', 'build', 'server', 'index.js'));
  await write(path.join(artifact, 'storefront', '.react-router', 'types', 'x.d.ts'));
  await write(path.join(artifact, 'storefront', 'dev.log'));
  await write(
    path.join(artifact, 'backend', 'template.json'),
    JSON.stringify(FINGERPRINT('shop_backend')),
  );
  await write(path.join(artifact, 'backend', 'src', 'index.ts'));
  await write(path.join(artifact, 'backend', 'data', 'products.json'), '[]');
  await write(path.join(artifact, 'backend', 'dist', 'index.js'));
  await write(path.join(artifact, 'backend', 'node_modules', 'graphql', 'index.js'));
  await write(path.join(artifact, 'data', 'products.json'), '[]');
  await write(
    path.join(runDir, 'build.json'),
    JSON.stringify({
      genBackend: true,
      backendPort: 1,
      backendUrl: 'http://127.0.0.1:1',
      templates: { storefront: FINGERPRINT('storefront'), backend: FINGERPRINT('shop_backend') },
    }),
  );
  await write(path.join(runDir, 'run.json'), JSON.stringify({ finalStatus: 'completed' }));
  await write(path.join(runDir, 'backend.log'));
});

async function listFiles(dir: string): Promise<string[]> {
  const entries = await fs.readdir(dir, { recursive: true, withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile())
    .map((entry) => path.relative(dir, path.join(entry.parentPath, entry.name)))
    .sort();
}

describe('publishShop', () => {
  it('copies storefront and backend sources, skipping build output, deps, logs and .env', async () => {
    const result = await publishShop({ runDir, shopDir });
    expect(await listFiles(shopDir)).toEqual([
      'backend/data/products.json',
      'backend/src/index.ts',
      'backend/template.json',
      'shop.json',
      'storefront/app/root.tsx',
      'storefront/app/routes/home.tsx',
      'storefront/template.json',
    ]);
    expect(result.manifest).toMatchObject({
      name: 'sample-shop',
      genBackend: true,
      finalStatus: 'completed',
      templates: {
        storefront: { name: 'storefront', dirty: true, contentHash: 'hash-storefront' },
        backend: { name: 'shop_backend', dirty: false, contentHash: 'hash-shop_backend' },
      },
    });
    expect(result.manifest.publishedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(await readShopManifest(shopDir)).toEqual(result.manifest);
  });

  it('is idempotent and drops files that no longer exist in the artifact', async () => {
    await publishShop({ runDir, shopDir });
    await write(path.join(shopDir, 'storefront', 'app', 'stale.tsx'));
    await fs.rm(path.join(runDir, 'artifact', 'storefront', 'app', 'routes', 'home.tsx'));
    await publishShop({ runDir, shopDir });
    const files = await listFiles(shopDir);
    expect(files).not.toContain('storefront/app/stale.tsx');
    expect(files).not.toContain('storefront/app/routes/home.tsx');
    expect(files).toContain('storefront/app/root.tsx');
  });

  it('records an unknown final status when run.json is missing', async () => {
    await fs.rm(path.join(runDir, 'run.json'));
    const result = await publishShop({ runDir, shopDir });
    expect(result.manifest.finalStatus).toBe('unknown');
  });

  it('reads a manifest whose fingerprints predate the dirty flag', async () => {
    await publishShop({ runDir, shopDir });
    const file = path.join(shopDir, 'shop.json');
    const raw: unknown = JSON.parse(await fs.readFile(file, 'utf-8'));
    await fs.writeFile(
      file,
      JSON.stringify(raw, (key, value: unknown) => (key === 'dirty' ? undefined : value)),
    );
    const manifest = await readShopManifest(shopDir);
    expect(manifest.templates.storefront.dirty).toBeUndefined();
  });

  it('refuses a run directory without build.json or template.json', async () => {
    await fs.rm(path.join(runDir, 'artifact', 'backend', 'template.json'));
    await expect(publishShop({ runDir, shopDir })).rejects.toBeInstanceOf(PublishError);
    await fs.rm(path.join(runDir, 'build.json'));
    await expect(publishShop({ runDir, shopDir })).rejects.toThrow(/build\.json/);
  });
});
