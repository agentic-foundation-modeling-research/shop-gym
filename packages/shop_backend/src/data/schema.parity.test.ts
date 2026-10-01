/**
 * Parity check: every dataset we ship or generate must load under the zod
 * schema. Covers the committed fixtures plus any shops present under
 * `SHOPGYM_SHOPS_DIR` (defaults to `<repo>/outputs/shops`), which is skipped
 * when the directory does not exist (e.g. in CI).
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { loadShopData } from './loader.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../../../..');

const FIXTURE_DIRS = [
  path.resolve(HERE, '../../tests/fixtures/sandbox_shop_v0'),
  path.join(REPO_ROOT, 'packages/shop-arena/templates/storefront/fixtures/sandbox_shop_v0'),
].filter((dir) => fs.existsSync(dir));

const SHOPS_DIR = process.env.SHOPGYM_SHOPS_DIR ?? path.join(REPO_ROOT, 'outputs/shops');
const SHOP_DATA_DIRS = fs.existsSync(SHOPS_DIR)
  ? fs
      .readdirSync(SHOPS_DIR)
      .map((name) => path.join(SHOPS_DIR, name, 'data'))
      .filter((dir) => fs.existsSync(path.join(dir, 'store.json')))
  : [];

describe('dataset schema parity', () => {
  it.each(FIXTURE_DIRS)('loads fixture %s', (dir) => {
    const data = loadShopData(dir);
    expect(data.products.length).toBeGreaterThan(0);
  });

  it.each(SHOP_DATA_DIRS)('loads generated shop %s', (dir) => {
    const data = loadShopData(dir);
    expect(data.products.length).toBeGreaterThan(0);
    expect(data.variantsByGid.size).toBeGreaterThan(0);
  });
});
