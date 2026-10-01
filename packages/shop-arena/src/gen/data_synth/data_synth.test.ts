import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { FakeRuntime } from '@shop-gym/agent/testing';
import { datasetSchema } from '@shop-gym/shop-backend';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { parseGenConfig } from '../config.js';
import { createGenContext } from '../context.js';
import { checkDataset } from '../data_validation/schema_check.js';
import { ScriptedSynthLlm, writeManualFixture } from '../testing.js';
import { runDataSynth } from './index.js';
import { synthOrders } from './orders.js';

let root: string;
let shopDir: string;

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'data-synth-'));
  shopDir = path.join(root, 'shop');
  await writeManualFixture(path.join(shopDir, 'manual'));
});

afterEach(async () => {
  await fs.rm(root, { recursive: true, force: true });
});

function stepContext(llm: ScriptedSynthLlm, log: string[] = []) {
  const config = parseGenConfig({
    name: 'tiny',
    manualDirs: [path.join(shopDir, 'manual')],
    outDir: shopDir,
    catalog: { collections: 2, productsPerCollection: 2, imagesPerProduct: 1 },
  });
  const context = createGenContext(config, { llm, runtime: new FakeRuntime(), credentials: {} });
  return {
    outDir: shopDir,
    context,
    log: (line: string) => log.push(line),
    signal: new AbortController().signal,
  };
}

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await fs.readFile(file, 'utf-8'));
}

describe('runDataSynth', () => {
  it('writes a dataset that passes the backend schema and invariants', async () => {
    const llm = new ScriptedSynthLlm();
    await runDataSynth(stepContext(llm));
    const dataDir = path.join(shopDir, 'data');
    const files = (await fs.readdir(dataDir)).sort();
    expect(files).toEqual([
      'collections.json',
      'commerce.json',
      'customers.json',
      'images',
      'inventory.json',
      'navigation.json',
      'orders.json',
      'pages.json',
      'policies.json',
      'products.json',
      'store.json',
    ]);
    const products = datasetSchema.productsFileSchema.parse(
      await readJson(path.join(dataDir, 'products.json')),
    );
    expect(products.length).toBe(4);
    expect(products[0]?.images[0]?.src).toBe('collection-1-item-1-1.png');
    expect(await fs.readdir(path.join(dataDir, 'images'))).toHaveLength(4);
    const customers = datasetSchema.customersFileSchema.parse(
      await readJson(path.join(dataDir, 'customers.json')),
    );
    expect(customers.map((c) => c.email)).toEqual([
      'jane.doe@example.com',
      'omar.haddad@example.com',
      'lena.berg@example.com',
    ]);
    const orders = datasetSchema.ordersFileSchema.parse(
      await readJson(path.join(dataDir, 'orders.json')),
    );
    expect(orders.length).toBeGreaterThanOrEqual(3);
    const identity = (await readJson(path.join(shopDir, 'identity.json'))) as { name: string };
    const store = datasetSchema.storeSchema.parse(await readJson(path.join(dataDir, 'store.json')));
    expect(store.name).toBe(identity.name);
    expect(await checkDataset(dataDir)).toEqual([]);
    const cache = (await fs.readdir(path.join(shopDir, '.shop_gen', 'stage_cache'))).sort();
    expect(cache).toEqual([
      'alt_text.json',
      'collections.json',
      'commerce.json',
      'customers.json',
      'details',
      'images_manifest.json',
      'navigation.json',
      'pages.json',
      'policies.json',
      'skeletons.json',
      'store.json',
    ]);
  });

  it('is deterministic and reuses the cache on a second run', async () => {
    const first = new ScriptedSynthLlm();
    await runDataSynth(stepContext(first));
    const before = await fs.readFile(path.join(shopDir, 'data', 'products.json'), 'utf-8');
    const second = new ScriptedSynthLlm();
    await runDataSynth(stepContext(second));
    expect(second.requests).toHaveLength(0);
    expect(await fs.readFile(path.join(shopDir, 'data', 'products.json'), 'utf-8')).toBe(before);
    expect(first.requests.length).toBeGreaterThan(8);
  });

  it('resumes synth_product_details per collection', async () => {
    await runDataSynth(stepContext(new ScriptedSynthLlm()));
    await fs.rm(path.join(shopDir, 'data'), { recursive: true });
    await fs.rm(path.join(shopDir, '.shop_gen', 'stage_cache', 'details', 'collection-2.json'));
    const llm = new ScriptedSynthLlm();
    await runDataSynth(stepContext(llm));
    expect(llm.requests).toHaveLength(1);
    expect(String(llm.requests[0]?.prompt)).toContain('"handle": "collection-2"');
    expect(await checkDataset(path.join(shopDir, 'data'))).toEqual([]);
  });

  it('retries a details row whose vendor is outside the allowlist', async () => {
    const llm = new ScriptedSynthLlm({ firstVendor: 'Zorblax' });
    const log: string[] = [];
    await runDataSynth(stepContext(llm, log));
    const detailPrompts = llm.requests.filter((r) =>
      String(r.prompt).includes('rich product details'),
    );
    expect(detailPrompts).toHaveLength(3);
    expect(log.some((l) => l.includes('not in the fake-brand allowlist'))).toBe(true);
    const products = datasetSchema.productsFileSchema.parse(
      await readJson(path.join(shopDir, 'data', 'products.json')),
    );
    expect(products.every((p) => p.vendor === 'AisleArena')).toBe(true);
  });
});

describe('synthOrders', () => {
  it('derives totals from commerce rules deterministically', () => {
    const product = {
      id: 1,
      title: 'Oak Bowl',
      handle: 'oak-bowl',
      description_html: '',
      vendor: 'AisleArena',
      product_type: 'Bowl',
      tags: [],
      published_at: '',
      created_at: '',
      updated_at: '',
      options: [],
      images: [],
      variants: [
        {
          id: 11,
          title: 'Small',
          sku: null,
          price: '20.00',
          compare_at_price: null,
          available: true,
          option1: null,
          option2: null,
          option3: null,
          position: 1,
          requires_shipping: true,
        },
      ],
    };
    const customer = {
      id: 5,
      email: 'jane.doe@example.com',
      password: 'x',
      first_name: 'Jane',
      last_name: 'Doe',
      phone: null,
      accepts_marketing: false,
      created_at: '',
      addresses: [],
      default_address_id: null,
    };
    const commerce = {
      tax_rate: 0.1,
      free_shipping_threshold: '100.00',
      shipping_methods: [{ handle: 'standard', title: 'Standard', price: '5.00' }],
      payment_methods: [{ handle: 'card', title: 'Card' }],
    };
    const orders = synthOrders([customer], [product], commerce, 'USD');
    expect(orders).toEqual(synthOrders([customer], [product], commerce, 'USD'));
    for (const o of orders) {
      const subtotal = o.line_items.reduce((s, li) => s + Number(li.price) * li.quantity, 0);
      expect(Number(o.subtotal_price)).toBeCloseTo(subtotal);
      expect(o.total_shipping_price).toBe(subtotal >= 100 ? '0.00' : '5.00');
      expect(Number(o.total_tax)).toBeCloseTo(Math.round(subtotal * 10) / 100);
      expect(datasetSchema.orderSchema.safeParse(o).success).toBe(true);
    }
  });
});
