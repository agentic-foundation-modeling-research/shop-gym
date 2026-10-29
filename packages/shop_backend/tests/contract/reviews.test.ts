/**
 * Contract: Reviews from the optional `reviews.json`. `Product.reviews` pages
 * a product's Reviews with `first` / `after` in one of four sort orders, and
 * the standard `reviews.rating` and `reviews.rating_count` product
 * metafields are computed from the same Reviews.
 */

import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { type ContractServer, FIXTURE_DIR, startContractServer } from './helpers.js';

const TOYS = 'shopliseum-mushroom-dog-toys';

let ctx: ContractServer;

interface ReviewPage {
  readonly nodes: readonly { readonly title: string }[];
  readonly pageInfo: { readonly hasNextPage: boolean; readonly endCursor: string | null };
}

/** One page of the Reviews of `handle`; `args` is the GraphQL argument list. */
async function reviewPage(handle: string, args: string): Promise<ReviewPage> {
  const result = await ctx.query<{ product: { reviews: ReviewPage } | null }>(
    `{ product(handle: "${handle}") {
      reviews(${args}) { nodes { title } pageInfo { hasNextPage endCursor } }
    } }`,
  );
  const reviews = result.data?.product?.reviews;
  if (reviews === undefined) throw new Error(JSON.stringify(result));
  return reviews;
}

interface RatingMetafields {
  readonly rating: { readonly value: string; readonly type: string } | null;
  readonly ratingCount: { readonly value: string; readonly type: string } | null;
}

/** The `reviews.rating` and `reviews.rating_count` metafields of `handle` on `server`. */
async function ratingMetafields(server: ContractServer, handle: string): Promise<RatingMetafields> {
  const result = await server.query<{ product: RatingMetafields | null }>(
    `{ product(handle: "${handle}") {
      rating: metafield(namespace: "reviews", key: "rating") { value type }
      ratingCount: metafield(namespace: "reviews", key: "rating_count") { value type }
    } }`,
  );
  const product = result.data?.product;
  if (product === undefined || product === null) throw new Error(JSON.stringify(result));
  return product;
}

function rating(value: string): { readonly value: string; readonly type: string } {
  return { value: JSON.stringify({ value, scale_min: '1.0', scale_max: '5.0' }), type: 'rating' };
}

async function reviewTitles(handle: string, args: string): Promise<readonly string[]> {
  return (await reviewPage(handle, args)).nodes.map((node) => node.title);
}

beforeAll(async () => {
  ctx = await startContractServer();
});

afterAll(async () => {
  await ctx.server.close();
});

describe('Product.reviews', () => {
  it('lists every field of a Review, most recent first by default', async () => {
    const result = await ctx.query<unknown>(/* GraphQL */ `
      {
        product(handle: "${TOYS}") {
          reviews(first: 1) {
            nodes {
              id
              rating
              title
              body
              reviewerName
              createdAt
              verifiedBuyer
              helpfulCount
              variant { id title selectedOptions { name value } }
            }
          }
        }
      }
    `);
    expect(result.errors).toBeUndefined();
    expect(result.data).toEqual({
      product: {
        reviews: {
          nodes: [
            {
              id: 'gid://shopify/Review/3',
              rating: 2,
              title: 'Too small for a large dog',
              body: 'Our labrador can fit the whole toy in her mouth. Buy it for a small dog only.',
              reviewerName: 'Ana P.',
              createdAt: '2025-12-14T18:45:00.000Z',
              verifiedBuyer: false,
              helpfulCount: 1,
              variant: {
                id: 'gid://shopify/ProductVariant/47242695737518',
                title: 'Green Mushroom',
                selectedOptions: [{ name: 'Red Mushroom', value: 'Green Mushroom' }],
              },
            },
          ],
        },
      },
    });
  });

  it('pages with first and after, and reports the next page', async () => {
    const first = await reviewPage(TOYS, 'first: 4');
    expect(first.nodes.map((node) => node.title)).toEqual([
      'Too small for a large dog',
      'Fine for gentle chewers',
      'Still squeaking after a month',
      'Good, but the stem came off',
    ]);
    expect(first.pageInfo.hasNextPage).toBe(true);

    const rest = await reviewPage(TOYS, `first: 4, after: "${first.pageInfo.endCursor}"`);
    expect(rest.nodes.map((node) => node.title)).toEqual([
      "Our puppy's favourite",
      'Bright colours',
    ]);
    expect(rest.pageInfo.hasNextPage).toBe(false);
  });

  // The toy Reviews: two share the most recent date, two share the helpful
  // count 1 and that date, and two pairs share a rating.
  it.each([
    [
      'MOST_RECENT',
      [
        'Too small for a large dog',
        'Fine for gentle chewers',
        'Still squeaking after a month',
        'Good, but the stem came off',
        "Our puppy's favourite",
        'Bright colours',
      ],
    ],
    [
      'HIGHEST_RATING',
      [
        'Still squeaking after a month',
        "Our puppy's favourite",
        'Good, but the stem came off',
        'Bright colours',
        'Fine for gentle chewers',
        'Too small for a large dog',
      ],
    ],
    [
      'LOWEST_RATING',
      [
        'Too small for a large dog',
        'Fine for gentle chewers',
        'Good, but the stem came off',
        'Bright colours',
        'Still squeaking after a month',
        "Our puppy's favourite",
      ],
    ],
    [
      'MOST_HELPFUL',
      [
        'Good, but the stem came off',
        'Still squeaking after a month',
        'Bright colours',
        'Too small for a large dog',
        'Fine for gentle chewers',
        "Our puppy's favourite",
      ],
    ],
  ])('sorts by %s, the more recent Review first on ties, then file order', async (key, titles) => {
    expect(await reviewTitles(TOYS, `first: 10, sortKey: ${key}`)).toEqual(titles);
    // Reads are deterministic: a second read gives the same order.
    expect(await reviewTitles(TOYS, `first: 10, sortKey: ${key}`)).toEqual(titles);
  });

  it('keeps the sort order across pages', async () => {
    const first = await reviewPage(TOYS, 'first: 3, sortKey: HIGHEST_RATING');
    const rest = await reviewTitles(
      TOYS,
      `first: 3, after: "${first.pageInfo.endCursor}", sortKey: HIGHEST_RATING`,
    );
    expect(rest).toEqual([
      'Bright colours',
      'Fine for gentle chewers',
      'Too small for a large dog',
    ]);
  });

  it('is empty for a product with no Reviews', async () => {
    const page = await reviewPage('cartanvil-mackerel-and-sardines-70g', 'first: 10');
    expect(page).toEqual({ nodes: [], pageInfo: { hasNextPage: false, endCursor: null } });
  });
});

describe('rating metafields', () => {
  it.each([
    // 5 + 4 + 2 + 5 + 3 + 4 = 23 over 6 Reviews is 3.83.
    [TOYS, '3.8', '6'],
    ['aislearena-anti-tick-collar', '4.5', '2'],
    ['agoracage-skin-and-coat-chicken-with-grains-12lb', '4.0', '1'],
  ])('computes reviews.rating and reviews.rating_count of %s', async (handle, value, count) => {
    expect(await ratingMetafields(ctx, handle)).toEqual({
      rating: rating(value),
      ratingCount: { value: count, type: 'number_integer' },
    });
  });

  it('serves them through Product.metafields too', async () => {
    const result = await ctx.query<{ product: { metafields: readonly unknown[] } }>(
      `{ product(handle: "${TOYS}") {
        metafields(identifiers: [
          { namespace: "reviews", key: "rating_count" },
          { namespace: "reviews", key: "rating" }
        ]) { namespace key value }
      } }`,
    );
    expect(result.data?.product.metafields).toEqual([
      { namespace: 'reviews', key: 'rating_count', value: '6' },
      { namespace: 'reviews', key: 'rating', value: rating('3.8').value },
    ]);
  });

  it('has none for a product with no Reviews', async () => {
    expect(await ratingMetafields(ctx, 'cartanvil-mackerel-and-sardines-70g')).toEqual({
      rating: null,
      ratingCount: null,
    });
  });
});

describe('a Dataset without reviews.json', () => {
  let withoutReviews: ContractServer;
  let dataDir: string;

  beforeAll(async () => {
    dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'reviews-absent-'));
    fs.cpSync(FIXTURE_DIR, dataDir, { recursive: true });
    fs.rmSync(path.join(dataDir, 'reviews.json'));
    // A stored rating must not show: the rating comes only from Reviews.
    const metafieldsPath = path.join(dataDir, 'metafields.json');
    const metafields = JSON.parse(fs.readFileSync(metafieldsPath, 'utf8')) as {
      products: Record<string, unknown[]>;
    };
    metafields.products[TOYS] = [
      { namespace: 'reviews', key: 'rating', value: rating('4.9').value, type: 'rating' },
      { namespace: 'reviews', key: 'rating_count', value: '120', type: 'number_integer' },
    ];
    fs.writeFileSync(metafieldsPath, JSON.stringify(metafields));
    withoutReviews = await startContractServer(dataDir);
  });

  afterAll(async () => {
    await withoutReviews.server.close();
    fs.rmSync(dataDir, { recursive: true, force: true });
  });

  it('loads, with no Reviews and no rating metafields', async () => {
    const result = await withoutReviews.query<unknown>(
      `{ product(handle: "${TOYS}") { title reviews(first: 5) { nodes { id } } } }`,
    );
    expect(result).toEqual({
      data: { product: { title: 'Shopliseum Mushroom Dog Toys', reviews: { nodes: [] } } },
    });
    expect(await ratingMetafields(withoutReviews, TOYS)).toEqual({
      rating: null,
      ratingCount: null,
    });
  });
});
