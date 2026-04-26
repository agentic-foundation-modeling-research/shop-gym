import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { InvalidDatasetError, MissingDatasetFileError, loadShopData } from './loader.js';

const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../tests/fixtures/sandbox_shop_v0',
);

/**
 * Copy the canonical fixture into a fresh tmpdir so each test can mutate it
 * (drop files, corrupt JSON, etc.) without touching the committed copy.
 */
function copyFixture(): string {
  const dest = fs.mkdtempSync(path.join(os.tmpdir(), 'sandbox-shop-'));
  fs.cpSync(FIXTURE_DIR, dest, { recursive: true });
  return dest;
}

describe('loadShopData', () => {
  let tmpDir: string | null = null;

  beforeEach(() => {
    tmpDir = null;
  });

  afterEach(() => {
    if (tmpDir !== null) {
      fs.rmSync(tmpDir, { recursive: true, force: true });
      tmpDir = null;
    }
  });

  it('loads the canonical fixture and populates indices', () => {
    const data = loadShopData(FIXTURE_DIR);

    expect(data.store.name).toBe('Mock Pet Foods');
    expect(data.store.currency_code).toBe('CAD');
    expect(data.store.brand.colors.primary).toBe('#1f6f43');
    expect(data.store.dataset_version).toBe('0.1');

    expect(data.products).toHaveLength(5);
    expect(data.collections).toHaveLength(2);
    expect(data.pages).toHaveLength(1);
    expect(data.policies).toHaveLength(1);
    expect(data.blogs).toHaveLength(1);
    expect(data.blogs[0]?.articles).toHaveLength(1);

    expect(data.navigation['main-menu']).toBeDefined();
    expect(data.navigation['main-menu']).toHaveLength(3);

    expect(data.metafields.shop).toHaveLength(1);
    expect(data.metafields.products['go-skin-and-coat-chicken-with-grains-12lb']).toHaveLength(1);
    expect(data.metafields.collections['dog-essentials']).toHaveLength(1);

    // inventory.json (since v0.2): tracked counts indexed by numeric variant id.
    expect(data.inventory['47242666836142']).toEqual({ quantity_available: 2 });
    expect(data.inventoryByVariantId.get(47242666836142)).toEqual({ quantity_available: 2 });
    expect(data.inventoryByVariantId.get(47242687709358)).toEqual({ quantity_available: 0 });
    expect(data.inventoryByVariantId.get(47242695737518)).toEqual({ quantity_available: null });
    expect(data.inventoryByVariantId.has(47242720215214)).toBe(false);
  });

  it('builds productsByHandle covering every product', () => {
    const data = loadShopData(FIXTURE_DIR);

    expect(data.productsByHandle.size).toBe(data.products.length);
    for (const product of data.products) {
      expect(data.productsByHandle.get(product.handle)).toBe(product);
    }
  });

  it('builds variantsByGid keyed by ProductVariant gid', () => {
    const data = loadShopData(FIXTURE_DIR);

    const expectedCount = data.products.reduce((sum, p) => sum + p.variants.length, 0);
    expect(data.variantsByGid.size).toBe(expectedCount);

    const sample = data.variantsByGid.get('gid://shopify/ProductVariant/47642512195758');
    expect(sample).toBeDefined();
    expect(sample?.product.handle).toBe('tickless-anti-tick-collar');
    expect(sample?.variant.title).toBe('Blue');
  });

  it('returns a frozen top-level object', () => {
    const data = loadShopData(FIXTURE_DIR);
    expect(Object.isFrozen(data)).toBe(true);
  });

  it('throws MissingDatasetFileError when a required file is absent', () => {
    tmpDir = copyFixture();
    fs.rmSync(path.join(tmpDir, 'products.json'));

    expect(() => loadShopData(tmpDir)).toThrow(MissingDatasetFileError);
  });

  it('throws InvalidDatasetError on malformed JSON', () => {
    tmpDir = copyFixture();
    fs.writeFileSync(path.join(tmpDir, 'store.json'), '{ not json');

    expect(() => loadShopData(tmpDir)).toThrow(InvalidDatasetError);
  });

  it('throws InvalidDatasetError with a path pointer on schema mismatch', () => {
    tmpDir = copyFixture();
    const broken = JSON.stringify({
      shop_id: 'not-a-number',
      name: 'Mock',
      domain: 'mock.example',
      description: '',
      currency_code: 'USD',
      country_code: 'US',
      payment_settings: { accepted_card_brands: [] },
      brand: { logo_url: null, colors: { primary: '#000', secondary: '#fff' } },
    });
    fs.writeFileSync(path.join(tmpDir, 'store.json'), broken);

    try {
      loadShopData(tmpDir);
      expect.fail('expected loadShopData to throw');
    } catch (err) {
      expect(err).toBeInstanceOf(InvalidDatasetError);
      const e = err as InvalidDatasetError;
      expect(e.fileName).toBe('store.json');
      expect(e.path).toBe('$.shop_id');
    }
  });

  it('defaults blogs and metafields when optional files are absent', () => {
    tmpDir = copyFixture();
    fs.rmSync(path.join(tmpDir, 'blogs.json'));
    fs.rmSync(path.join(tmpDir, 'metafields.json'));

    const data = loadShopData(tmpDir);
    expect(data.blogs).toEqual([]);
    expect(data.metafields).toEqual({ shop: [], products: {}, collections: {} });
  });

  it('defaults inventory to an empty file when inventory.json is absent', () => {
    tmpDir = copyFixture();
    fs.rmSync(path.join(tmpDir, 'inventory.json'));

    const data = loadShopData(tmpDir);
    expect(data.inventory).toEqual({});
    expect(data.inventoryByVariantId.size).toBe(0);
  });

  it('throws InvalidDatasetError when an inventory key is not an integer', () => {
    tmpDir = copyFixture();
    fs.writeFileSync(
      path.join(tmpDir, 'inventory.json'),
      JSON.stringify({ 'not-an-int': { quantity_available: 1 } }),
    );

    expect(() => loadShopData(tmpDir)).toThrow(InvalidDatasetError);
  });

  it('throws InvalidDatasetError when quantity_available is not a number or null', () => {
    tmpDir = copyFixture();
    fs.writeFileSync(
      path.join(tmpDir, 'inventory.json'),
      JSON.stringify({ '47242666836142': { quantity_available: 'lots' } }),
    );

    expect(() => loadShopData(tmpDir)).toThrow(InvalidDatasetError);
  });
});
