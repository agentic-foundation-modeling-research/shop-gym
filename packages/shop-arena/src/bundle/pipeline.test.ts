import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { type BundleOptionsInput, buildBundle } from './index.js';

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
  meta('G2', { title: 'Quillforge Headset', price: 'from 19.5', store: 'Quillforge' }),
  meta('G4', { title: 'Brightmoor Mouse Pad' }),
  meta('G5', { title: 'Brightmoor Cable' }),
  meta('G6', { title: 'Retrovale Console', categories: ['Video Games', 'Retro', 'Consoles'] }),
  meta('G7', { title: 'Zentrova Sequel' }),
  meta('G8', { title: 'Quillforge Stand', price: '—' }),
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
    const result = await buildBundle(options());
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

    const more = await buildBundle(
      options({ outDir: path.join(root, 'more', 'tiny'), products: 6 }),
    );
    const moreIds = readJsonl(more.bundleDir, 'catalog/products.jsonl').map((p) => p.product_id);
    expect(moreIds).toEqual(['G1', 'G2', 'G3', 'G4', 'G5', 'G8']);
  });

  it('maps the AR23 fields to the catalog standard', async () => {
    const result = await buildBundle(options());
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
      variants: [
        { variant_id: 'G1-BLK', price: { amount: 29.99, currency: 'USD' } },
        { variant_id: 'G1-WHT', price: { amount: 29.99, currency: 'USD' } },
      ],
      images: [{ source_url: 'https://images.example.test/g1.jpg' }],
      related: { bought_together: ['G4'] },
      source: { dataset: 'amazon_reviews_2023', id: 'G1' },
      provenance: { 'variants[].price': 'inferred' },
    });
    const byId = new Map(products.map((p) => [p.product_id, p]));
    expect(byId.get('G2')).toMatchObject({
      seller: 'Quillforge',
      variants: [{ variant_id: 'G2', price: { amount: 19.5, currency: 'USD' } }],
    });
    expect(byId.get('G2')).not.toHaveProperty('brand');
    for (const id of ['G3', 'G8']) {
      expect(byId.get(id)).toMatchObject({ variants: [{ variant_id: id }] });
      expect(byId.get(id)).not.toHaveProperty('provenance');
    }
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
    const result = await buildBundle(options());
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
    const result = await buildBundle(options());
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
      validation: {
        level: 'raw',
        counts: { products: 5, variants: 6, reviews: 13, profiles: 0, events: 7 },
      },
    });
  });

  it('caps the reviews of each product and always keeps the reviews of modeled users', async () => {
    const result = await buildBundle(options({ reviewsPerProduct: 2 }));
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
    const result = await buildBundle(options({ minEventsBefore: 4, users: 3 }));
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
  });

  it('gives the same bytes for the same options and seed', async () => {
    const files = [
      'bundle.json',
      'catalog/products.jsonl',
      'catalog/reviews.jsonl',
      'events/events.jsonl',
      'report.json',
    ];
    const first = await buildBundle(options({ reviewsPerProduct: 2 }));
    const second = await buildBundle(
      options({ reviewsPerProduct: 2, outDir: path.join(root, 'again', 'tiny') }),
    );
    for (const file of files) {
      expect(fs.readFileSync(path.join(second.bundleDir, file), 'utf-8')).toBe(
        fs.readFileSync(path.join(first.bundleDir, file), 'utf-8'),
      );
    }
  });

  it('runs on the pipeline runner: a rerun skips, --from reruns, new options rerun', async () => {
    const first = await buildBundle(options());
    expect(first.reports.map((r) => [r.id, r.status])).toEqual([
      ['sample', 'ran'],
      ['publish', 'ran'],
    ]);
    const again = await buildBundle(options());
    expect(again.reports.map((r) => r.status)).toEqual(['skipped', 'skipped']);
    const fromPublish = await buildBundle(options({ from: 'publish' }));
    expect(fromPublish.reports.map((r) => r.status)).toEqual(['skipped', 'ran']);
    const newSeed = await buildBundle(options({ seed: '8' }));
    expect(newSeed.reports.map((r) => r.status)).toEqual(['ran', 'ran']);
    expect(readJson(newSeed.manifestPath).sample).toMatchObject({ seed: '8' });
  });

  it('names the file and line of a source row that is not valid', async () => {
    const bad = [...REVIEWS.slice(0, 2), { ...REVIEWS[2], rating: 4.5 }];
    writeLines(path.join(sourceDir, 'review_categories', `${CATEGORY}.jsonl`), bad);
    await expect(buildBundle(options())).rejects.toThrow(`${CATEGORY}.jsonl:3: rating:`);
  });
});
