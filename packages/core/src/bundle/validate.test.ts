import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { EVENT_TYPES } from './schema.js';
import { BundleValidationError, validateBundle } from './validate.js';

const MANIFEST = {
  version: '0.1',
  name: 'tiny',
  sources: [{ dataset: 'tiny_source', license: 'research only' }],
  locale: 'en-US',
  currency: 'USD',
  cutoff: '2022-07-16T00:00:00.000Z',
  sample: { seed: '7', products: 2, users: 1, min_events_before: 1 },
};

const USD = (amount: number) => ({ amount, currency: 'USD' });

/** Raw records: the core fields only, with valid joins. */
const RAW = {
  products: [
    { product_id: 'P1', title: 'Glimmerdeck Controller', variants: [{ variant_id: 'V1' }] },
    {
      product_id: 'P2',
      title: 'Quillforge Headset',
      variants: [{ variant_id: 'V2', price: USD(20) }, { variant_id: 'V3' }],
      related: { bought_together: ['P1'] },
    },
  ],
  reviews: [
    {
      review_id: 'r1',
      product_id: 'P1',
      variant_id: 'V1',
      user_id: 'U1',
      rating: 5,
      title: 'Great',
      body: 'Works well.',
      created_at: '2021-03-14T09:12:00.000Z',
      verified_purchase: true,
      helpful_votes: 0,
    },
    {
      review_id: 'r2',
      product_id: 'P2',
      rating: 2,
      title: '',
      body: '',
      created_at: '2021-04-01T00:00:00.000Z',
      verified_purchase: false,
      helpful_votes: 3,
    },
  ],
  events: [
    {
      event_id: 'e1',
      user_id: 'U1',
      timestamp: '2021-03-14T09:12:00.000Z',
      timestamp_precision: 'order',
      event_type: 'purchase',
      product_id: 'P1',
      variant_id: 'V1',
      provenance: { '*': 'inferred' },
    },
  ],
};

/** The fields that the complete level adds to RAW. */
const COMPLETE = {
  products: [
    {
      ...RAW.products[0],
      description: 'A controller.',
      brand: 'Glimmerdeck',
      category_path: ['Games', 'Controllers'],
      variants: [{ variant_id: 'V1', price: USD(30), inventory: 4 }],
    },
    {
      ...RAW.products[1],
      description: 'A headset.',
      brand: 'Quillforge',
      category_path: ['Games', 'Headsets'],
      options: [{ name: 'Color', values: ['Black', 'White'] }],
      variants: [
        { variant_id: 'V2', option_values: { Color: 'Black' }, price: USD(20), inventory: 1 },
        { variant_id: 'V3', option_values: { Color: 'White' }, price: USD(20), inventory: 0 },
      ],
    },
  ],
  reviews: [RAW.reviews[0], { ...RAW.reviews[1], variant_id: 'V2' }],
  profiles: [
    {
      user_id: 'U1',
      preferences: { price_sensitivity: 'mid', category_interests: [['Games']] },
      narrative: 'Plays on weekends.',
      provenance: { '*': 'synthetic' },
    },
  ],
  events: RAW.events,
};

interface Files {
  readonly manifest?: unknown;
  readonly products?: readonly unknown[];
  readonly reviews?: readonly unknown[];
  readonly profiles?: readonly unknown[];
  readonly events?: readonly unknown[];
}

let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shopgym-bundle-'));
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

function writeBundle(files: Files): string {
  if (files.manifest !== undefined) {
    fs.writeFileSync(path.join(dir, 'bundle.json'), JSON.stringify(files.manifest));
  }
  const jsonl: [string, readonly unknown[] | undefined][] = [
    ['catalog/products.jsonl', files.products],
    ['catalog/reviews.jsonl', files.reviews],
    ['users/profiles.jsonl', files.profiles],
    ['events/events.jsonl', files.events],
  ];
  for (const [file, records] of jsonl) {
    if (records === undefined) continue;
    fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    const lines = records.map((record) => `${JSON.stringify(record)}\n`).join('');
    fs.writeFileSync(path.join(dir, file), lines);
  }
  return dir;
}

async function problemsOf(promise: Promise<unknown>): Promise<readonly string[]> {
  const err = await promise.then(
    () => undefined,
    (e: unknown) => e,
  );
  if (!(err instanceof BundleValidationError)) {
    throw new Error(`expected a BundleValidationError, got ${String(err)}`);
  }
  return err.problems;
}

describe('validateBundle', () => {
  it('passes a raw bundle and counts its records', async () => {
    const result = await validateBundle(writeBundle({ manifest: MANIFEST, ...RAW }), 'raw');
    expect(result.manifest.name).toBe('tiny');
    expect(result.counts).toEqual({ products: 2, variants: 3, reviews: 2, profiles: 0, events: 1 });
  });

  it('needs only bundle.json at the raw level', async () => {
    expect(await problemsOf(validateBundle(writeBundle({}), 'raw'))).toEqual([
      'bundle.json: missing',
    ]);
    const result = await validateBundle(writeBundle({ manifest: MANIFEST }), 'raw');
    expect(result.counts.products).toBe(0);
  });

  it('names the record and the field of a missing core field', async () => {
    const products = [RAW.products[0], { product_id: 'P2', variants: [{ variant_id: 'V2' }] }];
    const problems = await problemsOf(
      validateBundle(writeBundle({ manifest: MANIFEST, products }), 'raw'),
    );
    expect(problems).toEqual(['catalog/products.jsonl:2 (product_id "P2"): title: required']);
  });

  it('fails a broken join', async () => {
    const reviews = [
      { ...RAW.reviews[0], product_id: 'P9' },
      { ...RAW.reviews[1], variant_id: 'V1' },
    ];
    const events = [{ ...RAW.events[0], product_id: undefined, variant_id: 'V7' }];
    const problems = await problemsOf(
      validateBundle(writeBundle({ manifest: MANIFEST, ...RAW, reviews, events }), 'raw'),
    );
    expect(problems).toEqual([
      'catalog/reviews.jsonl:1 (review_id "r1"): product_id: no product "P9"',
      'catalog/reviews.jsonl:2 (review_id "r2"): variant_id: "V1" is a variant of product "P1", not "P2"',
      'events/events.jsonl:1 (event_id "e1"): variant_id: no variant "V7"',
    ]);
  });

  it('fails related ids outside the bundle and user ids without a profile', async () => {
    const products = [RAW.products[0], { ...RAW.products[1], related: { also_bought: ['P5'] } }];
    const problems = await problemsOf(
      validateBundle(
        writeBundle({ manifest: MANIFEST, ...RAW, products, profiles: [{ user_id: 'U2' }] }),
        'raw',
      ),
    );
    expect(problems).toEqual([
      'catalog/products.jsonl:2 (product_id "P2"): related.also_bought: no product "P5"',
      'catalog/reviews.jsonl:1 (review_id "r1"): user_id: no profile "U1"',
      'events/events.jsonl:1 (event_id "e1"): user_id: no profile "U1"',
    ]);
  });

  it('fails duplicate ids and a price in another currency', async () => {
    const products = [
      RAW.products[0],
      { product_id: 'P1', title: 'Again', variants: [{ variant_id: 'V8' }] },
      {
        product_id: 'P3',
        title: 'Third',
        variants: [{ variant_id: 'V1', price: { amount: 5, currency: 'EUR' } }],
      },
    ];
    const problems = await problemsOf(
      validateBundle(writeBundle({ manifest: MANIFEST, products }), 'raw'),
    );
    expect(problems).toEqual([
      'catalog/products.jsonl:2 (product_id "P1"): product_id: duplicate',
      'catalog/products.jsonl:3 (product_id "P3"): variants[0].variant_id: duplicate (also in product "P1")',
      'catalog/products.jsonl:3 (product_id "P3"): variants[0].price.currency: EUR is not the bundle currency USD',
    ]);
  });

  it('keeps event types and page types to their closed lists', async () => {
    const events = [
      ...EVENT_TYPES.map((event_type, i) => ({ ...RAW.events[0], event_id: `ok${i}`, event_type })),
      { ...RAW.events[0], event_id: 'e8', page_type: 'checkout_confirmation' },
      { ...RAW.events[0], event_id: 'e9', event_type: 'offer_make' },
      { ...RAW.events[0], event_id: 'e10', page_type: 'landing' },
    ];
    const problems = await problemsOf(
      validateBundle(writeBundle({ manifest: MANIFEST, ...RAW, events }), 'raw'),
    );
    expect(problems).toHaveLength(2);
    expect(problems[0]).toMatch(/^events\/events\.jsonl:13 \(event_id "e9"\): event_type: /);
    expect(problems[1]).toMatch(/^events\/events\.jsonl:14 \(event_id "e10"\): page_type: /);
  });

  it('refuses account fields in a profile', async () => {
    const profiles = [{ user_id: 'U1', email: 'someone@example.test' }];
    const problems = await problemsOf(
      validateBundle(writeBundle({ manifest: MANIFEST, profiles }), 'raw'),
    );
    expect(problems).toEqual([
      'users/profiles.jsonl:1 (user_id "U1"): record: Unrecognized key: "email"',
    ]);
  });

  it('needs the Shop generation fields at the complete level', async () => {
    const problems = await problemsOf(
      validateBundle(writeBundle({ manifest: MANIFEST, ...RAW }), 'complete'),
    );
    expect(problems).toEqual(
      expect.arrayContaining([
        'catalog/products.jsonl:1 (product_id "P1"): description: required',
        'catalog/products.jsonl:1 (product_id "P1"): variants[0].price: required',
        'catalog/products.jsonl:2 (product_id "P2"): variants[1].inventory: required',
        'catalog/reviews.jsonl:2 (review_id "r2"): variant_id: required',
        'users/profiles.jsonl: a complete bundle with User events needs profiles',
      ]),
    );
  });

  it('needs options when a product has more than one variant', async () => {
    const products = [COMPLETE.products[0], { ...COMPLETE.products[1], options: undefined }];
    const problems = await problemsOf(
      validateBundle(writeBundle({ manifest: MANIFEST, ...COMPLETE, products }), 'complete'),
    );
    expect(problems[0]).toBe(
      'catalog/products.jsonl:2 (product_id "P2"): options: required when there is more than one variant',
    );
  });

  it('passes a complete bundle', async () => {
    const result = await validateBundle(
      writeBundle({ manifest: MANIFEST, ...COMPLETE }),
      'complete',
    );
    expect(result.counts).toEqual({ products: 2, variants: 3, reviews: 2, profiles: 1, events: 1 });
  });

  it('lists the first fifty problems and gives the total', async () => {
    const reviews = Array.from({ length: 60 }, (_, i) => ({ review_id: `r${i}` }));
    const err = await validateBundle(writeBundle({ manifest: MANIFEST, reviews }), 'raw').catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(BundleValidationError);
    if (err instanceof BundleValidationError) {
      expect(err.problems).toHaveLength(50);
      expect(err.total).toBeGreaterThan(60);
      expect(err.message).toContain(`- ... and ${err.total - 50} more`);
    }
  });
});
