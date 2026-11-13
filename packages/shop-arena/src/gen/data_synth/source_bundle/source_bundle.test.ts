import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';
import { FakeRuntime } from '@shop-gym/agent/testing';
import { BundleValidationError, StepFailedError, runPipeline } from '@shop-gym/core';
import {
  type Customer,
  type Order,
  type Product,
  createSandboxServer,
  datasetSchema,
  loadShopData,
} from '@shop-gym/shop-backend';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ZodError } from 'zod';

import { STOREFRONT_TEMPLATE_DIR } from '../../../templates.js';
import type { SidecarLaunch } from '../../build/sidecar.js';
import type { CommandRunner } from '../../build/verifiers/subprocess.js';
import { parseGenConfig } from '../../config.js';
import { createGenContext } from '../../context.js';
import { checkDataset } from '../../data_validation/schema_check.js';
import { type GenResult, genSteps, generateShop } from '../../pipeline.js';
import { readShopManifest } from '../../publish/publish.js';
import {
  ScriptedJudge,
  ScriptedSynthLlm,
  stubStorefrontLaunch,
  writeManualFixture,
  writeSourceDatasetFixture,
} from '../../testing.js';
import { encodePng } from '../images/png.js';

const DASH = '\u2014'; // the harness plan grammar's task separator (U+2014)
const DONE_PLAN = `# Plan - test\n\n## Tasks\n\n- [x] gen_homepage ${DASH} render the homepage [priority: 7]\n\n## Omitted Areas\n\n- (none)\n`;
const CUTOFF = '2024-03-01T00:00:00.000Z';
/** Whole days from the cutoff to the Episode clock start, 2026-01-01. */
const OFFSET_DAYS = 671;
const KETTLE = 'copper-kettle-1-7-l';
const LAMP = 'desk-lamp-with-adjustable-arm-and-warm-white-light-for';
const MUG = 'stoneware-mug';
const TOWEL = 'linen-tea-towel';
/** Ids that only the hidden `users/` directory may name. */
const USER_IDS = ['user-ana', 'user-ben'];
const EVENT_IDS = ['ev-01', 'ev-02', 'ev-03', 'ev-04', 'ev-05', 'ev-06', 'ev-07', 'ev-08'];

const shift = (time: string): string =>
  new Date(Date.parse(time) + OFFSET_DAYS * 86_400_000).toISOString();

const fakeRunner: CommandRunner = async (argv, options) => {
  if (argv[0] === 'git' && argv[1] === 'ls-files') {
    const files =
      options.cwd === STOREFRONT_TEMPLATE_DIR
        ? ['package.json', 'app/routes/home.tsx']
        : ['package.json', 'src/cli.ts'];
    return { exitCode: 0, stdout: `${files.join('\0')}\0`, stderr: '', timedOut: false };
  }
  return {
    exitCode: 0,
    stdout: argv[0] === 'git' ? 'deadbeef\n' : '',
    stderr: '',
    timedOut: false,
  };
};

const inProcessLaunch: SidecarLaunch = async (options) => {
  const server = createSandboxServer({
    data: loadShopData(options.dataDir),
    dataDir: options.dataDir,
    port: options.port,
  });
  await server.listen();
  return { stop: () => server.close() };
};

/** Synthesis prompts are strings; judge prompts carry screenshots. */
class PipelineLlm implements LlmClient {
  readonly synth = new ScriptedSynthLlm();
  private readonly judge = new ScriptedJudge();
  complete(request: CompleteRequest): Promise<Completion> {
    return typeof request.prompt === 'string'
      ? this.synth.complete(request)
      : this.judge.complete(request);
  }
}

const jsonl = (records: readonly unknown[]): string =>
  records.map((r) => `${JSON.stringify(r)}\n`).join('');

/** A minimal JPEG: start of image, one baseline frame header of 6x5 pixels, end of image. */
function tinyJpeg(): Buffer {
  return Buffer.from([
    0xff, 0xd8, 0xff, 0xe0, 0x00, 0x04, 0x00, 0x00, 0xff, 0xc0, 0x00, 0x11, 0x08, 0x00, 0x05, 0x00,
    0x06, 0x03, 0x01, 0x22, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01, 0xff, 0xd9,
  ]);
}

/** A tiny complete bundle: four products, five reviews, two modeled users, eight User events. */
async function writeBundleFixture(dir: string, brandOfMug = 'Larkfield'): Promise<string> {
  const images = path.join(dir, 'catalog', 'images');
  await fs.mkdir(images, { recursive: true });
  await fs.writeFile(path.join(images, 'kettle.png'), encodePng(4, 3, new Uint8Array(4 * 3 * 3)));
  await fs.writeFile(path.join(images, 'kettle.jpg'), tinyJpeg());
  await fs.writeFile(path.join(images, 'kettle.gif'), 'GIF89a');
  await fs.mkdir(path.join(dir, 'users'), { recursive: true });
  await fs.mkdir(path.join(dir, 'events'), { recursive: true });
  await fs.writeFile(
    path.join(dir, 'bundle.json'),
    JSON.stringify({
      version: '0.1',
      name: 'fixture-bundle',
      sources: [{ dataset: 'fixture_reviews', license: 'Test data only.' }],
      locale: 'en-US',
      currency: 'USD',
      cutoff: CUTOFF,
    }),
  );
  const usd = (amount: number) => ({ amount, currency: 'USD' });
  await fs.writeFile(
    path.join(dir, 'catalog', 'products.jsonl'),
    jsonl([
      {
        product_id: 'P-TOWEL',
        title: 'Linen Tea Towel',
        description: 'A towel for drying cups.',
        brand: 'Larkfield',
        seller: 'Larkfield Home',
        category_path: ['Kitchen', 'Linens'],
        variants: [{ variant_id: 'V-TOWEL', price: usd(11), inventory: 3 }],
      },
      {
        product_id: 'P-KETTLE',
        title: 'Copper Kettle, 1.7 L',
        description: 'A stovetop kettle.\n\nWhistles when ready & pours clean.',
        bullets: ['1.7 L', 'Copper finish'],
        brand: 'Brightmoor',
        category_path: ['Kitchen', 'Cookware', 'Kettles'],
        attributes: { material: 'Copper' },
        options: [{ name: 'Color', values: ['Copper', 'Black'] }],
        variants: [
          {
            variant_id: 'V-KETTLE-CU',
            option_values: { Color: 'Copper' },
            price: usd(24),
            inventory: 5,
          },
          {
            variant_id: 'V-KETTLE-BK',
            option_values: { Color: 'Black' },
            price: usd(26.5),
            inventory: 0,
          },
        ],
        images: [
          { path: 'images/kettle.png', alt: 'Copper kettle' },
          { path: 'images/kettle.jpg' },
          { path: 'images/kettle.gif' },
          { source_url: 'https://img.example.com/kettle-3.jpg' },
        ],
        rating: { average: 4.9, count: 900 },
        related: { also_bought: ['P-MUG'] },
        source: { dataset: 'fixture_reviews', id: 'K-100' },
        provenance: { 'variants[].price': 'inferred' },
      },
      {
        product_id: 'P-MUG',
        title: 'Stoneware Mug',
        description: 'A heavy mug.',
        brand: brandOfMug,
        category_path: ['Kitchen', 'Drinkware'],
        variants: [{ variant_id: 'V-MUG', price: usd(8), inventory: 12 }],
      },
      {
        product_id: 'P-LAMP',
        title: 'Desk Lamp with Adjustable Arm and Warm White Light for Reading and Study',
        description: 'A desk lamp.',
        brand: 'Brightmoor',
        category_path: ['Home', 'Lighting'],
        variants: [{ variant_id: 'V-LAMP', price: usd(40), inventory: 2 }],
      },
    ]),
  );
  const review = (
    id: string,
    product: string,
    variant: string,
    rating: number,
    createdAt: string,
    extra: Record<string, unknown> = {},
  ) => ({
    review_id: id,
    product_id: product,
    variant_id: variant,
    rating,
    title: `Review ${id}`,
    body: `Body of ${id}.`,
    created_at: createdAt,
    verified_purchase: true,
    helpful_votes: 1,
    ...extra,
  });
  await fs.writeFile(
    path.join(dir, 'catalog', 'reviews.jsonl'),
    jsonl([
      review('r-4', 'P-MUG', 'V-MUG', 4, '2024-01-15T10:00:00.000Z', { user_id: 'user-ben' }),
      review('r-1', 'P-KETTLE', 'V-KETTLE-CU', 5, '2023-06-10T08:00:00.000Z', {
        user_id: 'user-ana',
        helpful_votes: 3,
      }),
      review('r-2', 'P-KETTLE', 'V-KETTLE-BK', 2, '2022-11-02T12:30:00.000Z', {
        title: '',
        verified_purchase: false,
        helpful_votes: 0,
      }),
      review('r-3', 'P-KETTLE', 'V-KETTLE-CU', 4, '2024-03-05T00:00:00.000Z'),
      review('r-5', 'P-LAMP', 'V-LAMP', 5, '2024-04-01T00:00:00.000Z', { user_id: 'user-ana' }),
    ]),
  );
  const profile = (id: string) => ({
    user_id: id,
    preferences: { price_sensitivity: 'mid', category_interests: [['Kitchen']] },
    narrative: `${id} cooks at home.`,
  });
  await fs.writeFile(
    path.join(dir, 'users', 'profiles.jsonl'),
    jsonl([profile('user-ben'), profile('user-ana')]),
  );
  const event = (
    id: string,
    user: string,
    type: string,
    timestamp: string,
    extra: Record<string, unknown>,
  ) => ({
    event_id: id,
    user_id: user,
    timestamp,
    timestamp_precision: 'ms',
    event_type: type,
    ...extra,
  });
  await fs.writeFile(
    path.join(dir, 'events', 'events.jsonl'),
    jsonl([
      event('ev-01', 'user-ana', 'purchase', '2023-06-01T09:00:00.000Z', {
        product_id: 'P-KETTLE',
        variant_id: 'V-KETTLE-CU',
      }),
      event('ev-02', 'user-ana', 'product_view', '2023-05-20T00:00:00.000Z', {
        product_id: 'P-TOWEL',
      }),
      event('ev-03', 'user-ana', 'purchase', '2023-06-01T09:00:00.000Z', { product_id: 'P-MUG' }),
      event('ev-04', 'user-ben', 'purchase', '2023-12-20T15:00:00.000Z', {
        product_id: 'P-MUG',
        variant_id: 'V-MUG',
        quantity: 2,
        order_id: 'O-9',
      }),
      event('ev-05', 'user-ben', 'purchase', '2023-12-20T15:05:00.000Z', {
        product_id: 'P-TOWEL',
        variant_id: 'V-TOWEL',
        price: usd(9.5),
        order_id: 'O-9',
      }),
      event('ev-06', 'user-ana', 'purchase', '2024-03-10T00:00:00.000Z', {
        product_id: 'P-LAMP',
        variant_id: 'V-LAMP',
      }),
      event('ev-07', 'user-ben', 'product_view', CUTOFF, { product_id: 'P-LAMP' }),
      event('ev-08', 'user-ben', 'add_to_cart', '2023-12-01T00:00:00.000Z', {
        product_id: 'P-KETTLE',
        variant_id: 'V-KETTLE-CU',
      }),
    ]),
  );
  return dir;
}

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await fs.readFile(file, 'utf-8'));
}

async function gql<T>(url: string, query: string): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  const body = (await response.json()) as { data?: T; errors?: unknown };
  expect(body.errors).toBeUndefined();
  return body.data as T;
}

let root: string;

beforeAll(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'gen-bundle-'));
});

afterAll(async () => {
  await fs.rm(root, { recursive: true, force: true });
});

describe('generateShop with a Source bundle', () => {
  let bundleDir: string;
  let manualDir: string;
  let result: GenResult;
  let llm: PipelineLlm;
  let products: Product[];
  let customers: Customer[];

  beforeAll(async () => {
    bundleDir = await writeBundleFixture(path.join(root, 'bundle'));
    manualDir = await writeManualFixture(path.join(root, 'manual'));
    llm = new PipelineLlm();
    result = await generateShop(
      {
        name: 'bundle-shop',
        manualDirs: [manualDir],
        bundleDir,
        outDir: path.join(root, 'shop'),
        model: 'fake/scripted',
        maxIters: 2,
      },
      {
        llm,
        runtime: new FakeRuntime([{ writeFiles: { 'plan.md': DONE_PLAN }, reply: 'planned' }]),
        credentials: {},
        commandRunner: fakeRunner,
        sidecarLaunch: inProcessLaunch,
        storefrontLaunch: stubStorefrontLaunch,
      },
    );
    products = datasetSchema.productsFileSchema
      .parse(await readJson(path.join(result.dataDir, 'products.json')))
      .slice();
    customers = datasetSchema.customersFileSchema
      .parse(await readJson(path.join(result.dataDir, 'customers.json')))
      .slice();
  }, 180_000);

  it('runs every step and writes a Dataset that passes the checks', async () => {
    expect(result.reports.map((r) => `${r.id}:${r.status}`)).toEqual([
      'manual_merge:ran',
      'data_synth:ran',
      'data_validation:ran',
      'build:ran',
      'final_eval:ran',
      'publish:ran',
    ]);
    expect(await checkDataset(result.dataDir)).toEqual([]);
    const firstLines = llm.synth.requests.map((r) => String(r.prompt).split('\n')[0] ?? '');
    for (const skipped of [
      'collections (categories)',
      'catalog skeleton',
      'rich product details',
      'image alt-text',
      'navigation menus',
      'customer personas',
      'product reviews',
    ]) {
      expect(firstLines.filter((line) => line.includes(skipped))).toEqual([]);
    }
    const store = datasetSchema.storeSchema.parse(
      await readJson(path.join(result.dataDir, 'store.json')),
    );
    expect(store).toMatchObject({ currency_code: 'USD', country_code: 'US' });
  });

  it('numbers the products by bundle id and keeps the marketplace fields', () => {
    expect(products.map((p) => [p.id, p.handle])).toEqual([
      [1, KETTLE],
      [2, LAMP],
      [3, MUG],
      [4, TOWEL],
    ]);
    expect(products[0]).toEqual({
      id: 1,
      title: 'Copper Kettle, 1.7 L',
      handle: KETTLE,
      description_html:
        '<p>A stovetop kettle.</p><p>Whistles when ready &#38; pours clean.</p><ul><li>1.7 L</li><li>Copper finish</li></ul>',
      vendor: 'Brightmoor',
      product_type: 'Kettles',
      tags: ['Kitchen', 'Cookware', 'Kettles'],
      published_at: shift('2022-11-02T12:30:00.000Z'),
      created_at: shift('2022-11-02T12:30:00.000Z'),
      updated_at: shift('2022-11-02T12:30:00.000Z'),
      options: [{ name: 'Color', position: 1, values: ['Copper', 'Black'] }],
      variants: [
        {
          id: 1,
          title: 'Copper',
          sku: 'V-KETTLE-CU',
          price: '24.00',
          compare_at_price: null,
          available: true,
          option1: 'Copper',
          option2: null,
          option3: null,
          position: 1,
          requires_shipping: true,
        },
        {
          id: 2,
          title: 'Black',
          sku: 'V-KETTLE-BK',
          price: '26.50',
          compare_at_price: null,
          available: false,
          option1: 'Black',
          option2: null,
          option3: null,
          position: 2,
          requires_shipping: true,
        },
      ],
      images: [
        {
          id: 1,
          src: `${KETTLE}-1.png`,
          alt: 'Copper kettle',
          width: 4,
          height: 3,
          position: 1,
        },
        { id: 2, src: `${KETTLE}-2.jpg`, alt: null, width: 6, height: 5, position: 2 },
      ],
      brand: 'Brightmoor',
      category_path: ['Kitchen', 'Cookware', 'Kettles'],
      attributes: { material: 'Copper' },
      related: { bought_together: [], also_bought: [MUG] },
      source: { dataset: 'fixture_reviews', id: 'K-100' },
      provenance: { 'variants[].price': 'inferred' },
    });
    expect(products[2]).toMatchObject({
      options: [{ name: 'Title', position: 1, values: ['Default Title'] }],
      variants: [{ id: 4, title: 'Default Title', option1: 'Default Title', price: '8.00' }],
    });
    expect(products[3]?.vendor).toBe('Larkfield Home');
    // A product seen only after the cutoff is listed from the Episode clock start.
    expect(products[1]?.created_at).toBe('2026-01-01T00:00:00.000Z');
  });

  it('copies the bundle images and renders a placeholder for a product without one', async () => {
    const imagesDir = path.join(result.dataDir, 'images');
    expect((await fs.readdir(imagesDir)).sort()).toEqual(
      [
        `${KETTLE}-1.png`,
        `${KETTLE}-2.jpg`,
        `${LAMP}-1.png`,
        `${TOWEL}-1.png`,
        `${MUG}-1.png`,
      ].sort(),
    );
    expect(await fs.readFile(path.join(imagesDir, `${KETTLE}-2.jpg`))).toEqual(tinyJpeg());
    expect(products[2]?.images).toEqual([
      { id: 4, src: `${MUG}-1.png`, alt: 'Stoneware Mug', width: 800, height: 800, position: 1 },
    ]);
  });

  it('makes a collection per category node and a department menu', async () => {
    const collections = datasetSchema.collectionsFileSchema.parse(
      await readJson(path.join(result.dataDir, 'collections.json')),
    );
    expect(collections.map((c) => [c.id, c.handle, c.title, c.product_handles])).toEqual([
      [1, 'home', 'Home', [LAMP]],
      [2, 'home-lighting', 'Lighting', [LAMP]],
      [3, 'kitchen', 'Kitchen', [KETTLE, MUG, TOWEL]],
      [4, 'kitchen-cookware', 'Cookware', [KETTLE]],
      [5, 'kitchen-cookware-kettles', 'Kettles', [KETTLE]],
      [6, 'kitchen-drinkware', 'Drinkware', [MUG]],
      [7, 'kitchen-linens', 'Linens', [TOWEL]],
    ]);
    const navigation = datasetSchema.navigationSchema.parse(
      await readJson(path.join(result.dataDir, 'navigation.json')),
    );
    const menu = (navigation['main-menu'] ?? []).map((item) => [
      item.url,
      item.children.map((child) => child.url),
    ]);
    expect(menu).toEqual([
      ['/collections/home', ['/collections/home-lighting']],
      [
        '/collections/kitchen',
        [
          '/collections/kitchen-cookware',
          '/collections/kitchen-drinkware',
          '/collections/kitchen-linens',
        ],
      ],
    ]);
    expect(navigation.footer?.map((item) => item.url)).toContain('/policies/refund-policy');
  });

  it('keeps the Reviews before the cutoff and computes the ratings from them', async () => {
    const reviews = datasetSchema.reviewsFileSchema.parse(
      await readJson(path.join(result.dataDir, 'reviews.json')),
    );
    const [ana, ben] = customers;
    expect(reviews).toEqual([
      {
        id: 1,
        product_handle: KETTLE,
        variant_id: 1,
        rating: 5,
        title: 'Review r-1',
        body: 'Body of r-1.',
        reviewer_name: `${ana?.first_name} ${ana?.last_name?.[0]}.`,
        created_at: shift('2023-06-10T08:00:00.000Z'),
        verified_buyer: true,
        helpful_count: 3,
        customer_id: ana?.id,
      },
      {
        id: 2,
        product_handle: KETTLE,
        variant_id: 2,
        rating: 2,
        title: '',
        body: 'Body of r-2.',
        reviewer_name: expect.stringMatching(/^[A-Z][a-z]+ [A-Z]\.$/),
        created_at: shift('2022-11-02T12:30:00.000Z'),
        verified_buyer: false,
        helpful_count: 0,
      },
      {
        id: 3,
        product_handle: MUG,
        variant_id: 4,
        rating: 4,
        title: 'Review r-4',
        body: 'Body of r-4.',
        reviewer_name: `${ben?.first_name} ${ben?.last_name?.[0]}.`,
        created_at: shift('2024-01-15T10:00:00.000Z'),
        verified_buyer: true,
        helpful_count: 1,
        customer_id: ben?.id,
      },
    ]);
    expect(reviews[1]).not.toHaveProperty('customer_id');

    const server = createSandboxServer({
      data: loadShopData(result.dataDir),
      dataDir: result.dataDir,
      port: 0,
    });
    await server.listen();
    try {
      const rating = (handle: string) =>
        gql<{
          product: {
            rating: { value: string } | null;
            count: { value: string } | null;
            reviews: { nodes: { rating: number }[] };
          };
        }>(
          server.url,
          `{ product(handle: "${handle}") { rating: metafield(namespace: "reviews", key: "rating") { value } count: metafield(namespace: "reviews", key: "rating_count") { value } reviews(first: 10) { nodes { rating } } } }`,
        );
      const kettle = (await rating(KETTLE)).product;
      expect(JSON.parse(kettle.rating?.value ?? '{}')).toMatchObject({ value: '3.5' });
      expect(kettle.count?.value).toBe('2');
      expect(kettle.reviews.nodes.map((n) => n.rating).sort()).toEqual([2, 5]);
      expect((await rating(LAMP)).product).toMatchObject({ rating: null, reviews: { nodes: [] } });
    } finally {
      await server.close();
    }
  });

  it('makes one Persona per modeled user with orders from the purchases before the cutoff', async () => {
    expect(customers).toHaveLength(2);
    const [ana, ben] = customers;
    for (const customer of customers) {
      expect(customer.email).toMatch(/^[a-z]+\.[a-z]+@example\.com$/);
      expect(customer.password).toMatch(/^pw-/);
      expect(customer.addresses.length).toBeGreaterThan(0);
      expect(customer.default_address_id).toBe(customer.addresses[0]?.id);
    }
    expect(ana?.email).not.toBe(ben?.email);
    expect(ana?.created_at).toBe(shift('2023-05-20T00:00:00.000Z'));
    expect(ben?.created_at).toBe(shift('2023-12-01T00:00:00.000Z'));

    const orders: readonly Order[] = datasetSchema.ordersFileSchema.parse(
      await readJson(path.join(result.dataDir, 'orders.json')),
    );
    expect(
      orders.map((o) => ({
        id: o.id,
        customer_id: o.customer_id,
        processed_at: o.processed_at,
        status: [o.financial_status, o.fulfillment_status],
        lines: o.line_items.map((l) => [l.variant_id, l.quantity, l.price]),
        subtotal: o.subtotal_price,
      })),
    ).toEqual([
      {
        id: 1001,
        customer_id: ana?.id,
        processed_at: shift('2023-06-01T09:00:00.000Z'),
        status: ['PAID', 'FULFILLED'],
        lines: [
          [1, 1, '24.00'],
          [4, 1, '8.00'],
        ],
        subtotal: '32.00',
      },
      {
        id: 1002,
        customer_id: ben?.id,
        processed_at: shift('2023-12-20T15:05:00.000Z'),
        status: ['PAID', 'FULFILLED'],
        lines: [
          [4, 2, '8.00'],
          [5, 1, '9.50'],
        ],
        subtotal: '25.50',
      },
    ]);

    const server = createSandboxServer({
      data: loadShopData(result.dataDir),
      dataDir: result.dataDir,
      port: 0,
    });
    await server.listen();
    try {
      const login = await gql<{
        customerAccessTokenCreate: { customerAccessToken: { accessToken: string } | null };
      }>(
        server.url,
        `mutation { customerAccessTokenCreate(input: { email: "${ana?.email}", password: "${ana?.password}" }) { customerAccessToken { accessToken } } }`,
      );
      const token = login.customerAccessTokenCreate.customerAccessToken?.accessToken ?? '';
      const account = await gql<{
        customer: { orders: { nodes: { processedAt: string }[] } } | null;
      }>(
        server.url,
        `{ customer(customerAccessToken: "${token}") { orders(first: 10) { nodes { processedAt } } } }`,
      );
      expect(account.customer?.orders.nodes.map((n) => n.processedAt)).toEqual([
        shift('2023-06-01T09:00:00.000Z'),
      ]);
    } finally {
      await server.close();
    }
  });

  it('writes the hidden users/ directory with the shop ids and handles', async () => {
    const usersDir = path.join(result.shopDir, 'users');
    expect((await fs.readdir(usersDir)).sort()).toEqual([
      'future_events.jsonl',
      'persona_map.json',
      'profiles.jsonl',
    ]);
    expect(await fs.readFile(path.join(usersDir, 'profiles.jsonl'), 'utf-8')).toBe(
      await fs.readFile(path.join(bundleDir, 'users', 'profiles.jsonl'), 'utf-8'),
    );
    const [ana, ben] = customers;
    expect(await readJson(path.join(usersDir, 'persona_map.json'))).toEqual({
      'user-ana': ana?.id,
      'user-ben': ben?.id,
    });
    const future = (await fs.readFile(path.join(usersDir, 'future_events.jsonl'), 'utf-8'))
      .trim()
      .split('\n')
      .map((line) => JSON.parse(line));
    expect(future).toEqual([
      {
        event_id: 'ev-06',
        user_id: 'user-ana',
        timestamp: '2024-03-10T00:00:00.000Z',
        timestamp_precision: 'ms',
        event_type: 'purchase',
        product_id: 'P-LAMP',
        variant_id: 'V-LAMP',
        shop: {
          timestamp: '2026-01-10T00:00:00.000Z',
          customer_id: ana?.id,
          product_id: 2,
          product_handle: LAMP,
          variant_id: 3,
        },
      },
      {
        event_id: 'ev-07',
        user_id: 'user-ben',
        timestamp: CUTOFF,
        timestamp_precision: 'ms',
        event_type: 'product_view',
        product_id: 'P-LAMP',
        shop: {
          timestamp: '2026-01-01T00:00:00.000Z',
          customer_id: ben?.id,
          product_id: 2,
          product_handle: LAMP,
        },
      },
    ]);
  });

  it('serves nothing from users/ and names no bundle user or event in data/', async () => {
    const server = createSandboxServer({
      data: loadShopData(result.dataDir),
      dataDir: result.dataDir,
      port: 0,
    });
    await server.listen();
    try {
      const base = server.url.replace(/\/graphql$/, '');
      for (const target of [
        '/users/persona_map.json',
        '/images/..%2F..%2Fusers%2Fpersona_map.json',
        '/images/%2e%2e%2f%2e%2e%2fusers%2fpersona_map.json',
        '/images/..%5C..%5Cusers%5Cpersona_map.json',
      ]) {
        const response = await fetch(`${base}${target}`);
        expect(response.status, target).not.toBe(200);
        expect(await response.text()).not.toContain('user-ana');
      }
    } finally {
      await server.close();
    }
    for (const name of await fs.readdir(result.dataDir)) {
      if (!name.endsWith('.json')) continue;
      const text = await fs.readFile(path.join(result.dataDir, name), 'utf-8');
      for (const id of [...USER_IDS, ...EVENT_IDS]) expect(text, name).not.toContain(id);
    }
    const artifact = path.join(result.buildRunDir, 'artifact');
    expect(await fs.readdir(artifact)).not.toContain('users');
  });

  it('records the bundle, the cutoff, the clock offset and the licenses in shop.json', async () => {
    const manifest = await readShopManifest(result.shopDir);
    expect(manifest.sourceManuals).toEqual([manualDir]);
    expect(manifest.sourceBundle).toEqual({
      dir: bundleDir,
      name: 'fixture-bundle',
      cutoff: CUTOFF,
      clockOffsetDays: OFFSET_DAYS,
      sources: [{ dataset: 'fixture_reviews', license: 'Test data only.' }],
    });
  });
});

describe('generateShop with an unusable Source bundle', () => {
  it('fails data_synth when the bundle is not complete', async () => {
    const dir = path.join(root, 'incomplete');
    const bundleDir = await writeBundleFixture(path.join(dir, 'bundle'));
    const products = (await fs.readFile(path.join(bundleDir, 'catalog', 'products.jsonl'), 'utf-8'))
      .trim()
      .split('\n')
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    await fs.writeFile(
      path.join(bundleDir, 'catalog', 'products.jsonl'),
      jsonl(products.map(({ brand: _, ...product }) => product)),
    );
    const failure = await generateShop(
      {
        name: 'incomplete',
        manualDirs: [await writeManualFixture(path.join(dir, 'manual'))],
        bundleDir,
        outDir: path.join(dir, 'shop'),
      },
      { llm: new ScriptedSynthLlm(), runtime: new FakeRuntime(), credentials: {} },
    ).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(StepFailedError);
    expect((failure as StepFailedError).cause).toBeInstanceOf(BundleValidationError);
    expect(String((failure as StepFailedError).cause)).toContain('brand');
  });

  it('rejects a bundle together with a source Dataset', async () => {
    const dir = path.join(root, 'both');
    await expect(
      generateShop(
        {
          name: 'both',
          manualDirs: [await writeManualFixture(path.join(dir, 'manual'))],
          bundleDir: await writeBundleFixture(path.join(dir, 'bundle')),
          sourceDataDir: await writeSourceDatasetFixture(path.join(dir, 'source')),
          outDir: path.join(dir, 'shop'),
        },
        { llm: new ScriptedSynthLlm(), runtime: new FakeRuntime(), credentials: {} },
      ),
    ).rejects.toThrow(ZodError);
  });
});

describe('genSteps with a Source bundle', () => {
  async function runDataSteps(bundleDir: string, manualDir: string, outDir: string) {
    const context = createGenContext(
      parseGenConfig({ name: 'tiny', manualDirs: [manualDir], outDir, bundleDir }),
      { llm: new ScriptedSynthLlm(), runtime: new FakeRuntime(), credentials: {} },
    );
    const steps = genSteps(context).filter((s) => s.id === 'manual_merge' || s.id === 'data_synth');
    return (await runPipeline(steps, { outDir, context })).map((r) => `${r.id}:${r.status}`);
  }

  async function readTree(dir: string): Promise<Record<string, string>> {
    const files = await fs.readdir(dir, { recursive: true, withFileTypes: true });
    const entries = await Promise.all(
      files
        .filter((f) => f.isFile())
        .map(async (f) => {
          const file = path.join(f.parentPath, f.name);
          return [path.relative(dir, file), (await fs.readFile(file)).toString('base64')] as const;
        }),
    );
    return Object.fromEntries(entries.sort(([a], [b]) => (a < b ? -1 : 1)));
  }

  it('maps the same bundle to the same bytes and reruns data_synth when a bundle file changes', async () => {
    const dir = path.join(root, 'steps');
    const bundleDir = await writeBundleFixture(path.join(dir, 'bundle'));
    const manualDir = await writeManualFixture(path.join(dir, 'manual'));
    const [first, second] = [path.join(dir, 'shop-a'), path.join(dir, 'shop-b')];
    expect(await runDataSteps(bundleDir, manualDir, first)).toEqual([
      'manual_merge:ran',
      'data_synth:ran',
    ]);
    await runDataSteps(bundleDir, manualDir, second);
    for (const sub of ['data', 'users']) {
      expect(await readTree(path.join(second, sub))).toEqual(await readTree(path.join(first, sub)));
    }
    expect(await runDataSteps(bundleDir, manualDir, first)).toEqual([
      'manual_merge:skipped',
      'data_synth:skipped',
    ]);
    // Work files of `shopgym bundle` are not inputs; the bundle's own files are.
    await fs.mkdir(path.join(bundleDir, '.bundle'), { recursive: true });
    await fs.writeFile(path.join(bundleDir, '.bundle', 'note.txt'), 'work file');
    expect(await runDataSteps(bundleDir, manualDir, first)).toEqual([
      'manual_merge:skipped',
      'data_synth:skipped',
    ]);
    await fs.appendFile(
      path.join(bundleDir, 'events', 'events.jsonl'),
      jsonl([
        {
          event_id: 'ev-09',
          user_id: 'user-ben',
          timestamp: '2024-05-01T00:00:00.000Z',
          timestamp_precision: 'ms',
          event_type: 'search',
          query: 'kettle',
        },
      ]),
    );
    expect(await runDataSteps(bundleDir, manualDir, first)).toEqual([
      'manual_merge:skipped',
      'data_synth:ran',
    ]);
    const future = await fs.readFile(path.join(first, 'users', 'future_events.jsonl'), 'utf-8');
    expect(future.trim().split('\n').at(-1)).toContain('"query":"kettle"');
  });
});
