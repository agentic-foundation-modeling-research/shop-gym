import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { FakeRuntime } from '@shop-gym/agent/testing';
import { datasetSchema } from '@shop-gym/shop-backend';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { parseGenConfig } from '../config.js';
import { createGenContext } from '../context.js';
import { checkDataset } from '../data_validation/schema_check.js';
import { SynthError } from '../llm.js';
import {
  SCRIPTED_DISCOUNT_CODES,
  ScriptedSynthLlm,
  type ScriptedSynthOptions,
  scriptedReviewText,
  writeManualFixture,
} from '../testing.js';
import { runDataSynth } from './index.js';
import { synthOrders } from './orders.js';
import type { Review } from './reviews.js';

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

const TINY_CATALOG = { collections: 2, productsPerCollection: 2, imagesPerProduct: 1 };

function stepContext(llm: ScriptedSynthLlm, log: string[] = [], catalog = TINY_CATALOG) {
  const config = parseGenConfig({
    name: 'tiny',
    manualDirs: [path.join(shopDir, 'manual')],
    outDir: shopDir,
    catalog,
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
      'reviews.json',
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
    // Five Personas; the LLM writes names and addresses, code assigns emails, passwords and ids.
    expect(customers.map((c) => c.email)).toEqual([
      'jane.doe@example.com',
      'omar.haddad@example.com',
      'lena.berg@example.com',
      'kenji.sato@example.com',
      'ana.silva@example.com',
    ]);
    expect(customers.map((c) => c.addresses.length)).toEqual([1, 2, 3, 1, 2]);
    expect(customers.every((c) => c.default_address_id === c.addresses[0]?.id)).toBe(true);
    expect(new Set(customers.flatMap((c) => c.addresses.map((a) => a.id))).size).toBe(9);
    expect(new Set(customers.map((c) => c.password)).size).toBe(5);
    const orders = datasetSchema.ordersFileSchema.parse(
      await readJson(path.join(dataDir, 'orders.json')),
    );
    expect(orders).toHaveLength(15);
    expect(orders.some((o) => o.email === 'ana.silva@example.com')).toBe(false);
    const reviews = datasetSchema.reviewsFileSchema.parse(
      await readJson(path.join(dataDir, 'reviews.json')),
    );
    expect(reviews.length).toBeGreaterThan(0);
    const identity = (await readJson(path.join(shopDir, 'identity.json'))) as { name: string };
    const store = datasetSchema.storeSchema.parse(await readJson(path.join(dataDir, 'store.json')));
    expect(store.name).toBe(identity.name);
    expect(await checkDataset(dataDir)).toEqual([]);
    const navigation = datasetSchema.navigationSchema.parse(
      await readJson(path.join(dataDir, 'navigation.json')),
    );
    const footerUrls = navigation.footer.map((item) => item.url);
    expect(footerUrls.some((url) => url.startsWith('/pages/'))).toBe(true);
    expect(footerUrls.some((url) => url.startsWith('/policies/'))).toBe(true);
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
      'reviews.json',
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

  it('writes the Discount codes of the checkout rules reply to commerce.json', async () => {
    await runDataSynth(stepContext(new ScriptedSynthLlm()));
    const commerce = datasetSchema.commerceSchema.parse(
      await readJson(path.join(shopDir, 'data', 'commerce.json')),
    );
    expect(commerce.discount_codes).toEqual(SCRIPTED_DISCOUNT_CODES);
  });

  it('gives four seeded orders a Discount code that lowers their total', async () => {
    await runDataSynth(stepContext(new ScriptedSynthLlm()));
    const orders = datasetSchema.ordersFileSchema.parse(
      await readJson(path.join(shopDir, 'data', 'orders.json')),
    );
    const used = orders.filter((o) => o.discount_code !== null);
    expect(used).toHaveLength(4);
    expect(used.every((o) => Number(o.discount_amount) > 0)).toBe(true);
  });

  const [percent, fixed, freeShipping] = SCRIPTED_DISCOUNT_CODES;
  it.each([
    ['two codes', [percent, fixed], 'expected array to have >=3 items'],
    [
      'six codes',
      [...SCRIPTED_DISCOUNT_CODES, ...['A1', 'B2', 'C3'].map((code) => ({ ...percent, code }))],
      'expected array to have <=5 items',
    ],
    [
      'no free-shipping code',
      [percent, fixed, { ...fixed, code: 'SAVE10' }],
      'of kind free_shipping',
    ],
    [
      'no percent or fixed code without a minimum',
      [{ ...percent, minimum_subtotal: '20.00' }, fixed, freeShipping],
      'no percentage or fixed_amount Discount code without a minimum_subtotal',
    ],
    [
      // The scripted checkout rules make shipping free from 50.00.
      'a free-shipping code that saves nothing',
      [percent, fixed, { ...freeShipping, minimum_subtotal: '50.00' }],
      'free_shipping Discount code FREESHIP has a minimum_subtotal at or above free_shipping_threshold 50.00',
    ],
    [
      'a code repeated in another case',
      [...SCRIPTED_DISCOUNT_CODES, { ...percent, code: 'welcome10' }],
      'Discount code welcome10 repeats a code when case is ignored',
    ],
    [
      'a 100 percent code',
      [{ ...percent, amount: '100' }, fixed, freeShipping],
      'Discount code WELCOME10 percent 100 is not below 100',
    ],
    [
      'a zero fixed amount',
      [percent, { ...fixed, amount: '0.00' }, freeShipping],
      'Discount code SAVE5 amount 0.00 is not positive',
    ],
    [
      'a negative minimum',
      [percent, { ...fixed, minimum_subtotal: '-1.00' }, freeShipping],
      '"minimum_subtotal"',
    ],
  ])('retries checkout rules with %s', async (_, codes, error) => {
    const llm = new ScriptedSynthLlm({ discountCodeReplies: [codes] });
    await runDataSynth(stepContext(llm));
    const commercePrompts = llm.requests.filter((r) =>
      String(r.prompt).includes('deriving the checkout rules'),
    );
    expect(commercePrompts).toHaveLength(2);
    expect(String(commercePrompts[1]?.prompt)).toContain(error);
    const commerce = datasetSchema.commerceSchema.parse(
      await readJson(path.join(shopDir, 'data', 'commerce.json')),
    );
    expect(commerce.discount_codes).toEqual(SCRIPTED_DISCOUNT_CODES);
  });

  it('fails when the checkout rules retry is invalid too', async () => {
    const bad = [percent, fixed, { ...fixed, code: 'SAVE10' }];
    const llm = new ScriptedSynthLlm({ discountCodeReplies: [bad, bad] });
    await expect(runDataSynth(stepContext(llm))).rejects.toThrow(SynthError);
    await expect(fs.access(path.join(shopDir, 'data'))).rejects.toThrow();
  });

  it('gives the same Personas, orders, Discount codes and Reviews on a fresh run', async () => {
    const dataFiles = () =>
      Promise.all(
        ['customers.json', 'orders.json', 'commerce.json', 'reviews.json'].map((f) =>
          fs.readFile(path.join(shopDir, 'data', f), 'utf-8'),
        ),
      );
    await runDataSynth(stepContext(new ScriptedSynthLlm()));
    const before = await dataFiles();
    await fs.rm(path.join(shopDir, 'data'), { recursive: true });
    await fs.rm(path.join(shopDir, '.shop_gen'), { recursive: true });
    await runDataSynth(stepContext(new ScriptedSynthLlm()));
    expect(await dataFiles()).toEqual(before);
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

  it('retries Personas when fewer than two have more than one address', async () => {
    const llm = new ScriptedSynthLlm({ singleAddressFirst: true });
    await runDataSynth(stepContext(llm));
    const personaPrompts = llm.requests.filter((r) =>
      String(r.prompt).includes('customer personas'),
    );
    expect(personaPrompts).toHaveLength(2);
    expect(String(personaPrompts[1]?.prompt)).toContain(
      'need at least 2 personas with 2 or more addresses, got 0',
    );
  });
});

describe('Review synthesis', () => {
  // 200 products, enough for the share without Reviews and the average rating to show.
  const LARGE_CATALOG = { collections: 4, productsPerCollection: 50, imagesPerProduct: 0 };

  async function synthLargeCatalog(options: ScriptedSynthOptions = {}) {
    const llm = new ScriptedSynthLlm(options);
    await runDataSynth(stepContext(llm, [], LARGE_CATALOG));
    const dataDir = path.join(shopDir, 'data');
    const products = datasetSchema.productsFileSchema.parse(
      await readJson(path.join(dataDir, 'products.json')),
    );
    const reviews = datasetSchema.reviewsFileSchema.parse(
      await readJson(path.join(dataDir, 'reviews.json')),
    );
    const reviewPrompts = llm.requests
      .map((r) => String(r.prompt))
      .filter((p) => p.includes('writing product reviews'));
    return { dataDir, products, reviews, reviewPrompts };
  }

  function byProduct(reviews: readonly Review[], handle: string): Review[] {
    return reviews.filter((r) => r.product_handle === handle);
  }

  it('plans one to eight Reviews for each product, and none for 15% of them', async () => {
    const { dataDir, products, reviews } = await synthLargeCatalog();
    expect(products).toHaveLength(200);
    const counts = products.map((p) => byProduct(reviews, p.handle).length);
    expect(counts.filter((n) => n === 0)).toHaveLength(30);
    const reviewed = counts.filter((n) => n > 0);
    expect(Math.min(...reviewed)).toBe(1);
    expect(Math.max(...reviewed)).toBe(8);
    expect(reviews.map((r) => r.id)).toEqual(reviews.map((_, i) => i + 1));
    expect(await checkDataset(dataDir)).toEqual([]);
  });

  it('rates Reviews from 1 to 5 with an average of about 4.3', async () => {
    const { reviews } = await synthLargeCatalog();
    const mean = reviews.reduce((sum, r) => sum + r.rating, 0) / reviews.length;
    expect(mean).toBeGreaterThan(4.28);
    expect(mean).toBeLessThan(4.32);
    expect(new Set(reviews.map((r) => r.rating))).toEqual(new Set([1, 2, 3, 4, 5]));
  });

  it('gives each Review a reviewer, a date before the clock start, the variant bought, a Verified Buyer flag and a helpful count', async () => {
    const { products, reviews } = await synthLargeCatalog();
    for (const review of reviews) {
      expect(review.reviewer_name).toMatch(/^[A-Z][a-z]+ [A-Z]\.$/);
      expect(review.created_at < '2026-01-01T00:00:00.000Z').toBe(true);
      expect(review.created_at >= '2024-01-01T00:00:00.000Z').toBe(true);
      const product = products.find((p) => p.handle === review.product_handle);
      expect(product?.variants.map((v) => v.id)).toContain(review.variant_id);
    }
    expect(new Set(reviews.map((r) => r.reviewer_name)).size).toBeGreaterThan(50);
    expect(new Set(reviews.map((r) => r.variant_id)).size).toBeGreaterThan(200);
    const verified = reviews.filter((r) => r.verified_buyer).length / reviews.length;
    expect(verified).toBeGreaterThan(0.7);
    expect(verified).toBeLessThan(0.9);
    const helpful = reviews.map((r) => r.helpful_count);
    expect(helpful.filter((n) => n === 0).length).toBeGreaterThan(reviews.length / 5);
    expect(Math.max(...helpful)).toBeGreaterThanOrEqual(20);
  });

  it('has the LLM write only the title and text, in batches of whole products, from the product facts and the rating', async () => {
    const { products, reviews, reviewPrompts } = await synthLargeCatalog();
    type PromptProduct = {
      title: string;
      product_type: string;
      tags: string[];
      description_html: string;
      reviews: { id: number; rating: number; variant: string }[];
    };
    const batches = reviewPrompts.map(
      (prompt) =>
        JSON.parse(/```json\n([\s\S]*?)\n```/.exec(prompt)?.[1] ?? '[]') as PromptProduct[],
    );
    expect(batches.length).toBeGreaterThan(1);
    for (const batch of batches) {
      expect(batch.flatMap((p) => p.reviews).length).toBeLessThanOrEqual(20);
    }
    const asked = batches.flat();
    expect(asked.map((p) => p.title)).toEqual(
      products.filter((p) => byProduct(reviews, p.handle).length > 0).map((p) => p.title),
    );
    for (const facts of asked) {
      const product = products.find((p) => p.title === facts.title);
      expect(facts).toMatchObject({
        product_type: product?.product_type,
        tags: product?.tags,
        description_html: product?.description_html,
      });
      for (const { id, rating, variant } of facts.reviews) {
        const review = reviews.find((r) => r.id === id);
        expect(review?.rating).toBe(rating);
        expect(product?.variants.find((v) => v.id === review?.variant_id)?.title).toBe(variant);
        expect({ title: review?.title, body: review?.body }).toEqual(
          scriptedReviewText(facts.title, rating),
        );
      }
    }
  });

  it.each([
    [
      'leaves out a Review',
      (texts: readonly { id: number }[]) => texts.slice(1),
      'expected one entry for each review id',
    ],
    [
      'names a brand',
      (texts: readonly { id: number }[]) =>
        texts.map((t, i) =>
          i === 0 ? { ...t, body: 'Better than anything from AisleArena.' } : t,
        ),
      'review 1 contains brand token AisleArena',
    ],
    [
      'writes too short a text',
      (texts: readonly { id: number }[]) =>
        texts.map((t, i) => (i === 0 ? { ...t, body: 'Nice.' } : t)),
      'body of review 1 must be 20-600 chars',
    ],
  ])('retries a reviews batch whose reply %s', async (_, edit, error) => {
    const { reviews, reviewPrompts } = await synthLargeCatalog({ editFirstReviewsReply: edit });
    const retried = reviewPrompts.filter((p) => p.includes(error));
    expect(retried).toHaveLength(1);
    expect(reviews.every((r) => !r.body.includes('AisleArena') && r.body.length >= 20)).toBe(true);
  });
});

describe('synthOrders', () => {
  const variant = {
    sku: null,
    compare_at_price: null,
    available: true,
    option1: null,
    option2: null,
    option3: null,
    requires_shipping: true,
  };
  const products = [
    {
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
        { ...variant, id: 11, title: 'Small', price: '20.00', position: 1 },
        { ...variant, id: 12, title: 'Large', price: '45.50', position: 2 },
        { ...variant, id: 13, title: 'Huge', price: '99.00', position: 3, available: false },
      ],
    },
  ];
  const address = (id: number, address1: string) => ({
    id,
    first_name: null,
    last_name: null,
    company: null,
    address1,
    address2: null,
    city: 'Springfield',
    province: null,
    province_code: null,
    country: 'United States',
    country_code: 'US',
    zip: '62701',
    phone: null,
  });
  const customers = [1, 2, 3, 4, 5].map((id) => ({
    id,
    email: `persona${id}@example.com`,
    password: 'x',
    first_name: null,
    last_name: null,
    phone: null,
    accepts_marketing: false,
    created_at: '',
    addresses: [address(id * 10, `${id} Home Road`), address(id * 10 + 1, `${id} Work Road`)],
    default_address_id: id * 10,
  }));
  const commerce = {
    tax_rate: 0.1,
    free_shipping_threshold: '100.00',
    shipping_methods: [
      { handle: 'standard', title: 'Standard', price: '5.00' },
      { handle: 'express', title: 'Express', price: '15.00' },
    ],
    payment_methods: [
      { handle: 'card', title: 'Card' },
      { handle: 'paypal', title: 'PayPal' },
    ],
    discount_codes: [],
  };
  const orders = synthOrders(customers, products, commerce, 'USD');

  it('is the same for the same inputs', () => {
    expect(synthOrders(customers, products, commerce, 'USD')).toEqual(orders);
  });

  it('makes 15 orders: none for the last Persona, 1 to 6 for every other', () => {
    expect(orders).toHaveLength(15);
    const counts = customers.map((c) => orders.filter((o) => o.customer_id === c.id).length);
    expect(counts.at(-1)).toBe(0);
    for (const count of counts.slice(0, -1)) {
      expect(count).toBeGreaterThanOrEqual(1);
      expect(count).toBeLessThanOrEqual(6);
    }
    expect(orders.every((o) => o.email === `persona${o.customer_id}@example.com`)).toBe(true);
  });

  it('dates orders in the 12 months before 2026-01-01 and numbers them by date from 1001', () => {
    expect(orders.map((o) => o.id)).toEqual(Array.from({ length: 15 }, (_, i) => 1001 + i));
    const dates = orders.map((o) => o.processed_at);
    expect([...dates].sort()).toEqual(dates);
    for (const date of dates) {
      expect(date >= '2025-01-01T00:00:00.000Z' && date < '2026-01-01T00:00:00.000Z').toBe(true);
    }
  });

  it('makes most orders paid and shipped, the newest not shipped, one each refunded, partly refunded and partly shipped', () => {
    const statuses = orders.map((o) => `${o.financial_status}/${o.fulfillment_status}`);
    expect(statuses.at(-1)).toBe('PAID/UNFULFILLED');
    expect(statuses.filter((s) => s === 'REFUNDED/FULFILLED')).toHaveLength(1);
    expect(statuses.filter((s) => s === 'PARTIALLY_REFUNDED/FULFILLED')).toHaveLength(1);
    expect(statuses.filter((s) => s === 'PAID/PARTIALLY_FULFILLED')).toHaveLength(1);
    expect(statuses.filter((s) => s === 'PAID/FULFILLED')).toHaveLength(11);
  });

  it('mixes shipping methods, payment methods and saved shipping addresses', () => {
    expect(new Set(orders.map((o) => o.shipping_method))).toEqual(new Set(['standard', 'express']));
    expect(new Set(orders.map((o) => o.payment_method))).toEqual(new Set(['card', 'paypal']));
    const saved = (o: (typeof orders)[number]) =>
      customers.find((c) => c.id === o.customer_id)?.addresses.map((a) => a.address1) ?? [];
    expect(orders.every((o) => saved(o).includes(o.shipping_address?.address1 ?? ''))).toBe(true);
    const lines = new Set(orders.map((o) => o.shipping_address?.address1.split(' ')[1]));
    expect(lines).toEqual(new Set(['Home', 'Work']));
  });

  it('buys available variants only and prices orders by the commerce rules', () => {
    for (const o of orders) {
      expect(o.line_items.every((li) => li.variant_id !== 13)).toBe(true);
      const subtotal = o.line_items.reduce(
        (s, li) => s + Math.round(Number(li.price) * 100) * li.quantity,
        0,
      );
      const method = o.shipping_method === 'express' ? 1500 : 500;
      const shipping = subtotal >= 10000 ? 0 : method;
      const tax = Math.round(subtotal * 0.1);
      expect([o.subtotal_price, o.total_shipping_price, o.total_tax, o.total_price]).toEqual(
        [subtotal, shipping, tax, subtotal + shipping + tax].map((c) => (c / 100).toFixed(2)),
      );
      expect(o.discount_code).toBeNull();
      expect(datasetSchema.orderSchema.safeParse(o).success).toBe(true);
    }
  });

  describe('with Discount codes', () => {
    const withCodes = { ...commerce, discount_codes: SCRIPTED_DISCOUNT_CODES };
    const discounted = synthOrders(customers, products, withCodes, 'USD');

    it('is the same for the same inputs', () => {
      expect(synthOrders(customers, products, withCodes, 'USD')).toEqual(discounted);
    });

    it('gives four orders a code that lowers the total by the pricing rules', () => {
      const used = discounted.filter((o) => o.discount_code !== null);
      expect(used).toHaveLength(4);
      for (const o of used) {
        const subtotal = o.line_items.reduce(
          (s, li) => s + Math.round(Number(li.price) * 100) * li.quantity,
          0,
        );
        const methodShipping = subtotal >= 10000 ? 0 : o.shipping_method === 'express' ? 1500 : 500;
        const off =
          o.discount_code === 'WELCOME10'
            ? Math.round(subtotal * 0.1)
            : o.discount_code === 'SAVE5'
              ? 500
              : 0;
        const shipping = o.discount_code === 'FREESHIP' ? 0 : methodShipping;
        const tax = Math.round((subtotal - off) * 0.1);
        const saved = o.discount_code === 'FREESHIP' ? methodShipping : off;
        expect(saved).toBeGreaterThan(0);
        if (o.discount_code === 'SAVE5') expect(subtotal).toBeGreaterThanOrEqual(4000);
        expect([
          o.subtotal_price,
          o.total_shipping_price,
          o.total_tax,
          o.total_price,
          o.discount_amount,
        ]).toEqual(
          [subtotal, shipping, tax, subtotal - off + shipping + tax, saved].map((c) =>
            (c / 100).toFixed(2),
          ),
        );
      }
    });

    it('gives no order a code that would not lower its total', () => {
      const unreachable = {
        ...commerce,
        discount_codes: [
          {
            code: 'BIG',
            kind: 'fixed_amount',
            amount: '5.00',
            minimum_subtotal: '1000.00',
            hint: '',
          },
        ],
      } as const;
      const orders = synthOrders(customers, products, unreachable, 'USD');
      expect(orders.every((o) => o.discount_code === null && o.discount_amount === '0.00')).toBe(
        true,
      );
    });
  });
});
