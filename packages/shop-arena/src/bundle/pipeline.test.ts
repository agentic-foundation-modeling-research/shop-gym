import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';
import { validateBundle } from '@shop-gym/core';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { type BundleOptionsInput, type BundleResult, buildBundle } from './index.js';

/**
 * A tiny hand-written Amazon Reviews 2023 category, cutoff 2022-07-16.
 *
 * - U1 has 5 events before the cutoff (two verified reviews and one
 *   unverified) and buys G8 after it: the only candidate at the default
 *   minimum of 5 events.
 * - U2 has 4 events before the cutoff and buys G5 after it.
 * - U3 has 6 events before the cutoff but buys nothing after it.
 * - G7 is first seen after the cutoff and U1 only reviews it: rule 5 drops it.
 * - G8 is first seen after the cutoff, but U1 buys it: a Task target.
 * - G4 and G5 share the Accessories path of the history; G6 is more
 *   reviewed than G5 but in another path.
 * - G9 has no title, and one review row is an exact duplicate.
 * - Gaps for the rule fills: G2 has only a seller and bullets, G3 and G8
 *   have no price, G3, G4 and G8 have no brand and no seller, and G8 has
 *   no category. G1 has two variants and no options.
 * - U2, O1 and O2 bought both G1 and G4 before the cutoff; U1 bought G1
 *   and G2.
 */
const CATEGORY = 'Tiny_Games';
const CUTOFF = '2022-07-16';
const ACCESSORIES = ['Video Games', 'PC', 'Accessories'];

function meta(parent: string, fields: Record<string, unknown>): Record<string, unknown> {
  return {
    main_category: 'Video Games',
    title: `Product ${parent}`,
    average_rating: 4.2,
    rating_number: 12,
    features: [],
    description: [],
    price: 15,
    images: [],
    videos: [],
    store: null,
    categories: ACCESSORIES,
    details: {},
    parent_asin: parent,
    bought_together: null,
    ...fields,
  };
}

const META = [
  meta('G3', { title: 'Zentrova Racing', categories: ['Video Games', 'PC', 'Games'], price: null }),
  meta('G1', {
    title: ' Glimmerdeck Wireless Controller ',
    features: ['40 hour battery', ' '],
    // U+2028 is valid inside a JSON string and must not end a JSONL line.
    description: ['A controller for long sessions.', 'Works on PC.\u2028Plug and play.'],
    price: 29.99,
    images: [
      {
        thumb: 'https://images.example.test/g1-thumb.jpg',
        large: 'https://images.example.test/g1.jpg',
        variant: 'MAIN',
        hi_res: null,
      },
    ],
    store: 'Glimmerdeck Store',
    details: { Brand: 'Glimmerdeck', Color: 'Black', 'Best Sellers Rank': { 'Video Games': 12 } },
    bought_together: ['G4', 'G6'],
  }),
  meta('G2', {
    title: 'Quillforge Headset',
    features: ['Closed-back ear cups'],
    price: 'from 19.5',
    store: 'Quillforge',
  }),
  meta('G4', { title: 'Brightmoor Mouse Pad' }),
  meta('G5', { title: 'Brightmoor Cable' }),
  meta('G6', { title: 'Retrovale Console', categories: ['Video Games', 'Retro', 'Consoles'] }),
  meta('G7', { title: 'Zentrova Sequel' }),
  meta('G8', { title: 'Quillforge Stand', price: '—', categories: [] }),
  meta('G9', { title: '' }),
  meta('G1', { title: 'Repeated row' }),
];

function review(
  user: string,
  asin: string,
  time: string,
  fields: { verified?: boolean; rating?: number; text?: string } = {},
): Record<string, unknown> {
  return {
    rating: fields.rating ?? 4,
    title: `About ${asin}`,
    text: fields.text ?? `${user} on ${asin}`,
    images: [],
    asin,
    parent_asin: asin.split('-')[0],
    user_id: user,
    timestamp: Date.parse(time),
    helpful_vote: 1,
    verified_purchase: fields.verified ?? true,
  };
}

const REVIEWS = [
  // A negative helpful vote count is a source quirk; the bundle keeps zero.
  { ...review('U1', 'G1-BLK', '2021-01-10T10:00:00Z', { rating: 5 }), helpful_vote: -1 },
  review('U1', 'G2', '2021-02-10T10:00:00Z'),
  review('U1', 'G3', '2021-03-10T10:00:00Z', { verified: false }),
  review('U1', 'G8', '2022-08-01T10:00:00Z'),
  review('U1', 'G7', '2022-08-05T10:00:00Z', { verified: false }),
  review('U2', 'G1-WHT', '2021-04-01T10:00:00Z'),
  review('U2', 'G4', '2021-05-01T10:00:00Z'),
  review('U2', 'G5', '2022-09-01T10:00:00Z'),
  review('U3', 'G6', '2020-01-01T10:00:00Z'),
  review('U3', 'G6', '2020-02-01T10:00:00Z'),
  review('U3', 'G4', '2020-03-01T10:00:00Z'),
  review('U3', 'G1-BLK', '2022-09-10T10:00:00Z', { verified: false }),
  review('O1', 'G4', '2021-06-01T10:00:00Z'),
  review('O1', 'G4', '2021-06-01T10:00:00Z'),
  review('O2', 'G4', '2021-07-01T10:00:00Z'),
  review('O3', 'G6', '2021-08-01T10:00:00Z'),
  review('O4', 'G5', '2021-09-01T10:00:00Z'),
  review('O1', 'G1-BLK', '2021-10-01T10:00:00Z'),
  review('O2', 'G1-WHT', '2021-11-01T10:00:00Z'),
  review('O3', 'G1-BLK', '2022-01-01T10:00:00Z'),
  review('O5', 'G9', '2021-01-01T10:00:00Z'),
  review('O6', 'G7', '2022-07-20T10:00:00Z'),
];

const RETRY_PREFIX = /^Your previous attempt failed validation[\s\S]*?Output JSON only[^\n]*\n\n/;

interface ScriptedFaults {
  /** The first n variant option replies have one value too many. */
  readonly badOptions?: number;
  /** The first n profile replies name a category that the catalog does not have. */
  readonly badProfiles?: number;
}

/**
 * Answers the variant option and User profile prompts of the complete
 * step with valid replies built from the prompt: values `Edition 1` to
 * `Edition n`, and a profile interested in the category of the first
 * history item.
 */
class ScriptedBundleLlm implements LlmClient {
  readonly prompts: string[] = [];
  private optionCalls = 0;
  private profileCalls = 0;

  constructor(private readonly faults: ScriptedFaults = {}) {}

  async complete(request: CompleteRequest): Promise<Completion> {
    if (typeof request.prompt !== 'string') {
      throw new Error('ScriptedBundleLlm: expected a string prompt');
    }
    this.prompts.push(request.prompt);
    return {
      text: JSON.stringify(this.reply(request.prompt.replace(RETRY_PREFIX, ''))),
      model: request.model.id,
      stopReason: 'end_turn',
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
    };
  }

  private reply(prompt: string): unknown {
    const blocks = [...prompt.matchAll(/```json\n([\s\S]*?)\n```/g)].map(
      (match) => JSON.parse(match[1] ?? 'null') as unknown,
    );
    if (prompt.startsWith('You are naming the variants')) {
      this.optionCalls += 1;
      const { variant_count: count } = blocks[0] as { variant_count: number };
      const extra = this.optionCalls <= (this.faults.badOptions ?? 0) ? 1 : 0;
      return {
        name: 'Edition',
        values: Array.from({ length: count + extra }, (_, i) => `Edition ${i + 1}`),
      };
    }
    if (prompt.startsWith('You are writing the profile')) {
      this.profileCalls += 1;
      const categories = blocks[0] as { path: string[] }[];
      const history = blocks[1] as { product: { category_path?: string[] } }[];
      const interest =
        this.profileCalls <= (this.faults.badProfiles ?? 0)
          ? ['Garden']
          : (history[0]?.product.category_path ?? categories[0]?.path);
      return {
        preferences: {
          price_sensitivity: 'mid',
          category_interests: [interest],
          brand_preferences: [],
          focus_aspects: ['value for money'],
        },
        habits: { reviews: 'often' },
        narrative: `A shopper with ${history.length} items in the history.`,
      };
    }
    throw new Error(`ScriptedBundleLlm: unknown prompt ${JSON.stringify(prompt.slice(0, 60))}`);
  }
}

let root: string;
let sourceDir: string;

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'shopgym-bundle-'));
  sourceDir = path.join(root, 'raw');
  writeLines(path.join(sourceDir, 'meta_categories', `meta_${CATEGORY}.jsonl`), META);
  writeLines(path.join(sourceDir, 'review_categories', `${CATEGORY}.jsonl`), REVIEWS);
});

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

function writeLines(file: string, rows: readonly unknown[]): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, rows.map((row) => `${JSON.stringify(row)}\n`).join(''));
}

function options(overrides: Partial<BundleOptionsInput> = {}): BundleOptionsInput {
  return {
    adapter: 'amazon_reviews_2023',
    sourceDir,
    category: CATEGORY,
    outDir: path.join(root, 'out', 'tiny'),
    cutoff: CUTOFF,
    products: 5,
    users: 1,
    seed: '7',
    ...overrides,
  };
}

/** Every file of a published bundle. */
const BUNDLE_OUTPUT = [
  'bundle.json',
  'catalog/products.jsonl',
  'catalog/reviews.jsonl',
  'users/profiles.jsonl',
  'events/events.jsonl',
  'report.json',
] as const;

function build(
  overrides: Partial<BundleOptionsInput> = {},
  llm: LlmClient = new ScriptedBundleLlm(),
): Promise<BundleResult> {
  return buildBundle(options(overrides), { llm });
}

function readJsonl(dir: string, file: string): Record<string, unknown>[] {
  return fs
    .readFileSync(path.join(dir, file), 'utf-8')
    .split('\n')
    .filter((line) => line !== '')
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

function readJson(file: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(file, 'utf-8')) as Record<string, unknown>;
}

describe('buildBundle on Amazon Reviews 2023', () => {
  it('samples users first, then their products, then filler from the same categories', async () => {
    const result = await build();
    const products = readJsonl(result.bundleDir, 'catalog/products.jsonl');
    expect(products.map((p) => p.product_id)).toEqual(['G1', 'G2', 'G3', 'G4', 'G8']);
    expect(readJson(result.reportPath).sample).toMatchObject({
      candidate_users: 1,
      modeled_users: 1,
      history_products: 4,
      products_dropped_after_cutoff: 1,
      filler_products: 1,
      products: 5,
    });

    const more = await build({ outDir: path.join(root, 'more', 'tiny'), products: 6 });
    const moreIds = readJsonl(more.bundleDir, 'catalog/products.jsonl').map((p) => p.product_id);
    expect(moreIds).toEqual(['G1', 'G2', 'G3', 'G4', 'G5', 'G8']);
  });

  it('maps the AR23 fields to the catalog standard', async () => {
    const result = await build();
    const products = readJsonl(result.bundleDir, 'catalog/products.jsonl');
    expect(products[0]).toEqual({
      product_id: 'G1',
      title: 'Glimmerdeck Wireless Controller',
      description: 'A controller for long sessions.\nWorks on PC.\u2028Plug and play.',
      bullets: ['40 hour battery'],
      brand: 'Glimmerdeck',
      seller: 'Glimmerdeck Store',
      category_path: ACCESSORIES,
      attributes: { Color: 'Black' },
      options: [{ name: 'Edition', values: ['Edition 1', 'Edition 2'] }],
      variants: [
        {
          variant_id: 'G1-BLK',
          option_values: { Edition: 'Edition 1' },
          price: { amount: 29.99, currency: 'USD' },
          inventory: expect.any(Number),
        },
        {
          variant_id: 'G1-WHT',
          option_values: { Edition: 'Edition 2' },
          price: { amount: 29.99, currency: 'USD' },
          inventory: expect.any(Number),
        },
      ],
      images: [{ source_url: 'https://images.example.test/g1.jpg' }],
      related: { bought_together: ['G4'], also_bought: ['G4'] },
      source: { dataset: 'amazon_reviews_2023', id: 'G1' },
      provenance: {
        'variants[].price': 'inferred',
        'related.also_bought': 'inferred',
        'variants[].inventory': 'synthetic',
        options: 'synthetic',
        'variants[].option_values': 'synthetic',
      },
    });
    expect(readJson(result.manifestPath)).toEqual({
      version: '0.1',
      name: 'tiny',
      sources: [
        {
          dataset: 'amazon_reviews_2023',
          license: expect.stringContaining('research'),
          url: expect.any(String),
          subsets: [CATEGORY],
        },
      ],
      locale: 'en-US',
      currency: 'USD',
      cutoff: '2022-07-16T00:00:00.000Z',
      sample: { seed: '7', products: 5, users: 1, min_events_before: 5 },
    });
  });

  it('makes User events only for modeled users, with an inferred purchase per verified review', async () => {
    const result = await build();
    const events = readJsonl(result.bundleDir, 'events/events.jsonl');
    expect(events.map((e) => [e.event_type, e.product_id])).toEqual([
      ['purchase', 'G1'],
      ['review', 'G1'],
      ['purchase', 'G2'],
      ['review', 'G2'],
      ['review', 'G3'],
      ['purchase', 'G8'],
      ['review', 'G8'],
    ]);
    expect(new Set(events.map((e) => e.user_id))).toEqual(new Set(['U1']));
    const [purchase, reviewEvent] = events;
    expect(purchase).toEqual({
      event_id: expect.stringMatching(/^e-[0-9a-f]{16}-purchase$/),
      user_id: 'U1',
      timestamp: '2021-01-10T10:00:00.000Z',
      product_id: 'G1',
      variant_id: 'G1-BLK',
      timestamp_precision: 'order',
      event_type: 'purchase',
      raw_type: 'verified_purchase',
      provenance: { '*': 'inferred' },
    });
    expect(reviewEvent).toMatchObject({ timestamp_precision: 'ms', event_type: 'review' });
    expect(reviewEvent).not.toHaveProperty('provenance');
    expect(readJson(result.reportPath).sample).toMatchObject({
      review_events: 4,
      purchase_events: 3,
      events_dropped: 1,
    });
  });

  it('keeps the reviews of kept products, drops exact duplicates, and names only modeled reviewers', async () => {
    const result = await build();
    const reviews = readJsonl(result.bundleDir, 'catalog/reviews.jsonl');
    expect(reviews).toHaveLength(13);
    expect(reviews[0]).toEqual({
      review_id: expect.stringMatching(/^r-[0-9a-f]{16}$/),
      product_id: 'G1',
      variant_id: 'G1-BLK',
      user_id: 'U1',
      rating: 5,
      title: 'About G1-BLK',
      body: 'U1 on G1-BLK',
      created_at: '2021-01-10T10:00:00.000Z',
      verified_purchase: true,
      helpful_votes: 0,
    });
    expect(reviews.filter((r) => r.user_id !== undefined)).toHaveLength(4);
    expect(reviews.filter((r) => r.product_id === 'G4')).toHaveLength(4);
    expect(readJson(result.reportPath)).toEqual({
      sample: expect.objectContaining({
        meta_rows: 10,
        meta_rows_repeated: 1,
        products_without_title: 1,
        review_rows: 22,
        duplicate_reviews: 1,
        reviews_without_product: 1,
        variants: 6,
        products_without_price: 2,
        reviews: 13,
        reviews_over_cap: 0,
      }),
      complete: expect.any(Object),
      validation: {
        level: 'complete',
        counts: { products: 5, variants: 6, reviews: 13, profiles: 1, events: 7 },
      },
    });
  });

  it('caps the reviews of each product and always keeps the reviews of modeled users', async () => {
    const result = await build({ reviewsPerProduct: 2 });
    const reviews = readJsonl(result.bundleDir, 'catalog/reviews.jsonl');
    const ofProduct = (id: string) => reviews.filter((r) => r.product_id === id);
    expect(ofProduct('G1')).toHaveLength(2);
    expect(ofProduct('G1').some((r) => r.user_id === 'U1')).toBe(true);
    expect(ofProduct('G4')).toHaveLength(2);
    expect(reviews).toHaveLength(7);
    expect(readJson(result.reportPath).sample).toMatchObject({ reviews: 7, reviews_over_cap: 6 });
    expect(readJson(result.manifestPath).sample).toMatchObject({ reviews_per_product: 2 });
  });

  it('takes the minimum events before the cutoff as an option', async () => {
    const result = await build({ minEventsBefore: 4, users: 3 });
    const events = readJsonl(result.bundleDir, 'events/events.jsonl');
    expect(new Set(events.map((e) => e.user_id))).toEqual(new Set(['U1', 'U2']));
    const products = readJsonl(result.bundleDir, 'catalog/products.jsonl');
    expect(products.map((p) => p.product_id)).toEqual(['G1', 'G2', 'G3', 'G4', 'G5', 'G8']);
    expect(readJson(result.reportPath).sample).toMatchObject({
      candidate_users: 2,
      modeled_users: 2,
      filler_products: 0,
    });
    expect(readJson(result.manifestPath).sample).toMatchObject({ min_events_before: 4 });
    expect(readJsonl(result.bundleDir, 'users/profiles.jsonl').map((p) => p.user_id)).toEqual([
      'U1',
      'U2',
    ]);
  });

  it('gives the same bytes for the same options and seed', async () => {
    const first = await build({ reviewsPerProduct: 2 });
    const second = await build({ reviewsPerProduct: 2, outDir: path.join(root, 'again', 'tiny') });
    for (const file of BUNDLE_OUTPUT) {
      expect(fs.readFileSync(path.join(second.bundleDir, file), 'utf-8')).toBe(
        fs.readFileSync(path.join(first.bundleDir, file), 'utf-8'),
      );
    }
  });

  it('runs on the pipeline runner: a rerun skips, --from reruns, new options rerun', async () => {
    const first = await build();
    expect(first.reports.map((r) => [r.id, r.status])).toEqual([
      ['sample', 'ran'],
      ['complete', 'ran'],
      ['publish', 'ran'],
    ]);
    const again = await build();
    expect(again.reports.map((r) => r.status)).toEqual(['skipped', 'skipped', 'skipped']);
    const fromPublish = await build({ from: 'publish' });
    expect(fromPublish.reports.map((r) => r.status)).toEqual(['skipped', 'skipped', 'ran']);
    const newModel = await build({ model: 'scripted/other' });
    expect(newModel.reports.map((r) => r.status)).toEqual(['skipped', 'ran', 'skipped']);
    const newSeed = await build({ seed: '8' });
    expect(newSeed.reports.map((r) => r.status)).toEqual(['ran', 'ran', 'ran']);
    expect(readJson(newSeed.manifestPath).sample).toMatchObject({ seed: '8' });
  });

  it('names the file and line of a source row that is not valid', async () => {
    const bad = [...REVIEWS.slice(0, 2), { ...REVIEWS[2], rating: 4.5 }];
    writeLines(path.join(sourceDir, 'review_categories', `${CATEGORY}.jsonl`), bad);
    await expect(build()).rejects.toThrow(`${CATEGORY}.jsonl:3: rating:`);
  });
});

describe('buildBundle complete step', () => {
  it('fills the missing catalog fields by rules and marks each one', async () => {
    const result = await build();
    const byId = new Map(
      readJsonl(result.bundleDir, 'catalog/products.jsonl').map((p) => [p.product_id, p]),
    );
    const price = (amount: number) => ({ amount, currency: 'USD' });
    expect(byId.get('G2')).toMatchObject({
      brand: 'Quillforge',
      seller: 'Quillforge',
      description: 'Closed-back ear cups',
      variants: [{ variant_id: 'G2', price: price(19.5) }],
      provenance: { brand: 'inferred', description: 'inferred', 'variants[].price': 'inferred' },
    });
    // The median price of the PC products: G4 15, G2 19.5 and G1 29.99.
    expect(byId.get('G3')).toMatchObject({
      brand: 'Generic',
      description: 'Zentrova Racing',
      variants: [{ variant_id: 'G3', price: price(19.5) }],
      provenance: { brand: 'synthetic', description: 'inferred', 'variants[].price': 'inferred' },
    });
    expect(byId.get('G8')).toMatchObject({
      category_path: ['Video Games'],
      variants: [{ variant_id: 'G8', price: price(19.5) }],
      provenance: { category_path: 'inferred', 'variants[].price': 'inferred' },
    });
    for (const product of byId.values()) {
      expect(product.provenance).toMatchObject({ 'variants[].inventory': 'synthetic' });
      for (const variant of product.variants as { inventory: number }[]) {
        expect(Number.isInteger(variant.inventory)).toBe(true);
        expect(variant.inventory).toBeGreaterThanOrEqual(1);
        expect(variant.inventory).toBeLessThanOrEqual(50);
      }
    }
    expect(readJson(result.reportPath).complete).toEqual({
      categories_inferred: 1,
      brands_from_seller: 1,
      brands_synthetic: 3,
      descriptions_inferred: 4,
      prices_inferred: 2,
      inventories_synthetic: 6,
      options_synthetic: 1,
      profiles_synthetic: 1,
    });
    await expect(validateBundle(result.bundleDir, 'complete')).resolves.toMatchObject({
      counts: { products: 5, profiles: 1 },
    });
  });

  it('relates products that the same users bought before the cutoff, by every reviewer, before the review cap', async () => {
    // O4 buys G1 before the cutoff and G8 after it, as U1 does: no relation.
    writeLines(path.join(sourceDir, 'review_categories', `${CATEGORY}.jsonl`), [
      ...REVIEWS,
      review('O4', 'G1-BLK', '2021-12-01T10:00:00Z'),
      review('O4', 'G8', '2022-08-10T10:00:00Z'),
    ]);
    const result = await build({ reviewsPerProduct: 1 });
    const byId = new Map(
      readJsonl(result.bundleDir, 'catalog/products.jsonl').map((p) => [p.product_id, p]),
    );
    // U2, O1 and O2 bought G1 and G4; only U1 bought G1 and G2.
    expect(byId.get('G1')).toMatchObject({ related: { also_bought: ['G4'] } });
    expect(byId.get('G4')).toMatchObject({
      related: { also_bought: ['G1'] },
      provenance: { 'related.also_bought': 'inferred' },
    });
    for (const id of ['G2', 'G3', 'G8']) {
      expect(byId.get(id)).not.toHaveProperty('related');
    }
    expect(readJson(result.reportPath).sample).toMatchObject({ products_with_also_bought: 2 });
  });

  it('asks the LLM for the options of each product with more than one variant', async () => {
    const llm = new ScriptedBundleLlm();
    await build({}, llm);
    const prompts = llm.prompts.filter((p) => p.startsWith('You are naming the variants'));
    expect(prompts).toHaveLength(1);
    expect(prompts[0]).toContain('Glimmerdeck Wireless Controller');
    expect(prompts[0]).toContain('exactly 2 values');
  });

  it('writes one User profile per modeled user from the history before the cutoff', async () => {
    const llm = new ScriptedBundleLlm();
    const result = await build({}, llm);
    expect(readJsonl(result.bundleDir, 'users/profiles.jsonl')).toEqual([
      {
        user_id: 'U1',
        preferences: {
          price_sensitivity: 'mid',
          category_interests: [ACCESSORIES],
          brand_preferences: [],
          focus_aspects: ['value for money'],
        },
        habits: { reviews: 'often' },
        narrative: 'A shopper with 3 items in the history.',
        provenance: { '*': 'synthetic' },
      },
    ]);
    const prompt = llm.prompts.find((p) => p.startsWith('You are writing the profile')) ?? '';
    expect(prompt).toContain('as of\n2022-07-16');
    expect(prompt).toContain('Glimmerdeck Wireless Controller');
    expect(prompt).toContain('U1 on G1-BLK');
    expect(prompt).toContain('from 15.00 to 29.99');
    // U1 buys G8 after the cutoff: a Task target, not history.
    expect(prompt).not.toContain('Quillforge Stand');
  });

  it('repairs a bad LLM reply with one more call, and fails the step after a second one', async () => {
    const repaired = new ScriptedBundleLlm({ badOptions: 1, badProfiles: 1 });
    await build({}, repaired);
    const retries = repaired.prompts.filter((p) => p.startsWith('Your previous attempt'));
    expect(repaired.prompts).toHaveLength(4);
    expect(retries).toHaveLength(2);
    expect(retries.join('\n')).toContain('values must have exactly 2 entries, got 3');
    expect(retries.join('\n')).toContain('["Garden"] is not a category path of the catalog');

    await expect(
      build({ outDir: path.join(root, 'bad', 'tiny') }, new ScriptedBundleLlm({ badOptions: 2 })),
    ).rejects.toThrow("Step 'complete' failed: LLM reply rejected after retry");
  });

  it('caches each LLM reply by its input, so a rerun makes no LLM call and writes the same bytes', async () => {
    const first = new ScriptedBundleLlm();
    const result = await build({}, first);
    expect(first.prompts).toHaveLength(2);
    const before = BUNDLE_OUTPUT.map((file) =>
      fs.readFileSync(path.join(result.bundleDir, file), 'utf-8'),
    );

    const rerun = new ScriptedBundleLlm();
    const again = await build({ from: 'complete' }, rerun);
    expect(again.reports.map((r) => r.status)).toEqual(['skipped', 'ran', 'skipped']);
    expect(rerun.prompts).toHaveLength(0);
    expect(
      BUNDLE_OUTPUT.map((file) => fs.readFileSync(path.join(result.bundleDir, file), 'utf-8')),
    ).toEqual(before);

    const otherModel = new ScriptedBundleLlm();
    await build({ model: 'scripted/other' }, otherModel);
    expect(otherModel.prompts).toHaveLength(2);
  });
});
