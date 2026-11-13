/**
 * Amazon Reviews 2023 (AR23) adapter: one category of the dataset to a raw
 * Source bundle.
 *
 * Field map: `parent_asin` is the product and each reviewed `asin` is one
 * of its variants. `features` become bullets, `details.Brand` the brand,
 * `store` the seller, `categories` the category path, the other text
 * `details` the attributes, and the large images the image source URLs.
 * The one source price goes on every variant, marked `inferred`.
 *
 * Reviews are catalog content. User events exist only for modeled users:
 * each review is a `review` event, and a verified review is also an
 * inferred `purchase` event at the review time, with the precision of an
 * order. Exact duplicate reviews (same user, asin, time, rating, title and
 * text) are dropped.
 *
 * The adapter reads the review file twice and the meta file twice, and
 * keeps only small per-row numbers in memory between the passes, so the
 * source files can be far larger than memory.
 */

import { createHash } from 'node:crypto';
import * as path from 'node:path';

import {
  BUNDLE_FILES,
  BUNDLE_VERSION,
  type BundleManifest,
  type BundleProduct,
  type BundleReview,
  type UserEvent,
  readJsonlLines,
} from '@shop-gym/core';

import { writeJsonFile } from '../../gen/io.js';
import { writeJsonl } from '../jsonl.js';
import {
  type ProductStats,
  capReviews,
  compareStrings,
  pickProducts,
  pickUsers,
} from '../sample.js';
import { type MetaRow, type ReviewRow, metaRowSchema, parseRow, reviewRowSchema } from './rows.js';

export const AR23_DATASET = 'amazon_reviews_2023';

const AR23_SOURCE = {
  dataset: AR23_DATASET,
  license:
    'No license; the authors share the data primarily for research purposes. Research use only.',
  url: 'https://amazon-reviews-2023.github.io/',
} as const;

const LOCALE = 'en-US';
const CURRENCY = 'USD';

/** The two files of one AR23 category, in the layout of the dataset download. */
export interface Ar23Files {
  readonly reviews: string;
  readonly meta: string;
}

export function ar23Files(sourceDir: string, category: string): Ar23Files {
  return {
    reviews: path.join(sourceDir, 'review_categories', `${category}.jsonl`),
    meta: path.join(sourceDir, 'meta_categories', `meta_${category}.jsonl`),
  };
}

export interface Ar23BundleOptions {
  readonly name: string;
  readonly category: string;
  /** ISO 8601 time. */
  readonly cutoff: string;
  readonly products: number;
  readonly users: number;
  readonly seed: string;
  readonly minEventsBefore: number;
  readonly reviewsPerProduct?: number | undefined;
}

/** What the adapter read, dropped and kept. */
export interface Ar23Report {
  readonly meta_rows: number;
  /** Meta rows of a product that an earlier row already gave. */
  readonly meta_rows_repeated: number;
  readonly products_without_title: number;
  readonly review_rows: number;
  readonly duplicate_reviews: number;
  /** Reviews of a product that has no meta row with a title. */
  readonly reviews_without_product: number;
  readonly candidate_users: number;
  readonly modeled_users: number;
  readonly history_products: number;
  readonly products_dropped_after_cutoff: number;
  readonly filler_products: number;
  readonly products: number;
  readonly variants: number;
  readonly products_without_price: number;
  readonly reviews: number;
  /** Reviews of kept products that the per-product cap left out. */
  readonly reviews_over_cap: number;
  readonly review_events: number;
  readonly purchase_events: number;
  /** Events of modeled users on products that the sample dropped. */
  readonly events_dropped: number;
}

/**
 * Sample one AR23 category and write a raw Source bundle into `outDir`.
 *
 * @throws Error naming the file and line of a source row that is not valid.
 */
export async function writeAr23Bundle(
  files: Ar23Files,
  options: Ar23BundleOptions,
  outDir: string,
  log: (line: string) => void,
): Promise<Ar23Report> {
  const cutoffMs = Date.parse(options.cutoff);
  const catalog = await readCatalog(files.meta);
  log(`[sample] meta: ${catalog.ids.length} products from ${catalog.rows} rows`);
  const source = await readReviews(files.reviews, catalog, cutoffMs);
  log(
    `[sample] reviews: ${source.rows.user.length} of ${source.reviewRows} rows (${source.duplicates} duplicates)`,
  );

  const userPick = pickUsers(source.users, options);
  const modeled = new Uint8Array(source.users.userIds.length);
  for (const user of userPick.users) modeled[user] = 1;
  const history = new Set<number>();
  const targets = new Set<number>();
  source.rows.user.forEach((user, row) => {
    if (modeled[user] !== 1) return;
    const product = source.rows.product[row] ?? -1;
    history.add(product);
    if ((source.rows.verified[row] ?? 0) === 1 && (source.rows.timeMs[row] ?? 0) >= cutoffMs) {
      targets.add(product);
    }
  });
  const stats: ProductStats[] = catalog.ids.map((id, product) => ({
    id,
    category: catalog.category[product] ?? '',
    firstSeenMs: source.firstSeenMs[product] ?? Number.POSITIVE_INFINITY,
    reviewsBefore: source.reviewsBefore[product] ?? 0,
  }));
  const productPick = pickProducts(
    stats,
    { history, targets },
    { products: options.products, cutoffMs },
  );
  const keptProduct = new Uint8Array(catalog.ids.length);
  for (const product of productPick.products) keptProduct[product] = 1;
  log(
    `[sample] ${userPick.users.length} of ${userPick.candidates} candidate users; ${productPick.products.length} products (${productPick.filler} filler)`,
  );

  const keptRow = keepReviews(source.rows, catalog.ids, modeled, keptProduct, options);
  const written = await writeReviewsAndEvents(files.reviews, outDir, {
    rows: source.rows,
    keptRow,
    modeled,
  });
  const products = await writeProducts(files.meta, outDir, {
    catalog,
    keptProduct,
    variants: source.variants,
  });
  await writeJsonFile(path.join(outDir, BUNDLE_FILES.manifest), manifest(options));

  let keptProductRows = 0;
  let eventsDropped = 0;
  source.rows.product.forEach((product, row) => {
    const events = (source.rows.verified[row] ?? 0) + 1;
    if (keptProduct[product] === 1) keptProductRows += 1;
    else if (modeled[source.rows.user[row] ?? -1] === 1) eventsDropped += events;
  });
  return {
    meta_rows: catalog.rows,
    meta_rows_repeated: catalog.repeated,
    products_without_title: catalog.withoutTitle,
    review_rows: source.reviewRows,
    duplicate_reviews: source.duplicates,
    reviews_without_product: source.withoutProduct,
    candidate_users: userPick.candidates,
    modeled_users: userPick.users.length,
    history_products: productPick.history,
    products_dropped_after_cutoff: productPick.droppedAfterCutoff,
    filler_products: productPick.filler,
    products: products.products,
    variants: products.variants,
    products_without_price: products.withoutPrice,
    reviews: written.reviews,
    reviews_over_cap: keptProductRows - written.reviews,
    review_events: written.reviewEvents,
    purchase_events: written.purchaseEvents,
    events_dropped: eventsDropped,
  };
}

function manifest(options: Ar23BundleOptions): BundleManifest {
  return {
    version: BUNDLE_VERSION,
    name: options.name,
    sources: [{ ...AR23_SOURCE, subsets: [options.category] }],
    locale: LOCALE,
    currency: CURRENCY,
    cutoff: options.cutoff,
    sample: {
      seed: options.seed,
      products: options.products,
      users: options.users,
      min_events_before: options.minEventsBefore,
      ...(options.reviewsPerProduct !== undefined
        ? { reviews_per_product: options.reviewsPerProduct }
        : {}),
    },
  };
}

/** The products with a title, by index, from the first meta row of each. */
interface Catalog {
  readonly ids: readonly string[];
  readonly index: ReadonlyMap<string, number>;
  /** Category path key by product index; empty when the product has no category. */
  readonly category: readonly string[];
  readonly rows: number;
  readonly repeated: number;
  readonly withoutTitle: number;
}

async function readCatalog(file: string): Promise<Catalog> {
  const ids: string[] = [];
  const index = new Map<string, number>();
  const category: string[] = [];
  const seen = new Set<string>();
  let rows = 0;
  let repeated = 0;
  let withoutTitle = 0;
  for await (const { line, text } of readJsonlLines(file)) {
    rows += 1;
    const row = parseRow(metaRowSchema, text, file, line);
    if (seen.has(row.parent_asin)) {
      repeated += 1;
      continue;
    }
    seen.add(row.parent_asin);
    if (cleanText(row.title) === undefined) {
      withoutTitle += 1;
      continue;
    }
    index.set(row.parent_asin, ids.length);
    ids.push(row.parent_asin);
    category.push(categoryPath(row).join('\u001f'));
  }
  return { ids, index, category, rows, repeated, withoutTitle };
}

/** The kept review rows, as parallel arrays indexed by row number. */
interface Rows {
  readonly user: number[];
  readonly product: number[];
  readonly timeMs: number[];
  /** 1 for a verified purchase. */
  readonly verified: number[];
  /** Line in the review file. */
  readonly line: number[];
}

interface ReviewIndex {
  readonly users: { userIds: string[]; eventsBefore: number[]; purchasesAfter: number[] };
  readonly rows: Rows;
  /** By product index. */
  readonly firstSeenMs: number[];
  readonly reviewsBefore: number[];
  readonly variants: Set<string>[];
  readonly reviewRows: number;
  readonly duplicates: number;
  readonly withoutProduct: number;
}

/** First pass over the reviews: dedup, then count per user and per product. */
async function readReviews(file: string, catalog: Catalog, cutoffMs: number): Promise<ReviewIndex> {
  const userIndex = new Map<string, number>();
  const users = {
    userIds: [] as string[],
    eventsBefore: [] as number[],
    purchasesAfter: [] as number[],
  };
  const rows: Rows = { user: [], product: [], timeMs: [], verified: [], line: [] };
  const firstSeenMs = catalog.ids.map(() => Number.POSITIVE_INFINITY);
  const reviewsBefore = catalog.ids.map(() => 0);
  const variants = catalog.ids.map(() => new Set<string>());
  const seen = new Set<string>();
  let reviewRows = 0;
  let duplicates = 0;
  let withoutProduct = 0;
  for await (const { line, text } of readJsonlLines(file)) {
    reviewRows += 1;
    const row = parseRow(reviewRowSchema, text, file, line);
    const product = catalog.index.get(row.parent_asin);
    if (product === undefined) {
      withoutProduct += 1;
      continue;
    }
    const key = reviewKey(row);
    if (seen.has(key)) {
      duplicates += 1;
      continue;
    }
    seen.add(key);
    let user = userIndex.get(row.user_id);
    if (user === undefined) {
      user = users.userIds.length;
      userIndex.set(row.user_id, user);
      users.userIds.push(row.user_id);
      users.eventsBefore.push(0);
      users.purchasesAfter.push(0);
    }
    const verified = row.verified_purchase ? 1 : 0;
    if (row.timestamp < cutoffMs) {
      users.eventsBefore[user] = (users.eventsBefore[user] ?? 0) + 1 + verified;
      reviewsBefore[product] = (reviewsBefore[product] ?? 0) + 1;
    } else {
      users.purchasesAfter[user] = (users.purchasesAfter[user] ?? 0) + verified;
    }
    firstSeenMs[product] = Math.min(firstSeenMs[product] ?? row.timestamp, row.timestamp);
    variants[product]?.add(row.asin);
    rows.user.push(user);
    rows.product.push(product);
    rows.timeMs.push(row.timestamp);
    rows.verified.push(verified);
    rows.line.push(line);
  }
  return {
    users,
    rows,
    firstSeenMs,
    reviewsBefore,
    variants,
    reviewRows,
    duplicates,
    withoutProduct,
  };
}

/** Rule 4: 1 for each kept row, by row number. */
function keepReviews(
  rows: Rows,
  productIds: readonly string[],
  modeled: Uint8Array,
  keptProduct: Uint8Array,
  options: Ar23BundleOptions,
): Uint8Array {
  const kept = new Uint8Array(rows.user.length);
  const cap = options.reviewsPerProduct;
  const others = new Map<number, number[]>();
  const modeledCount = new Map<number, number>();
  rows.product.forEach((product, row) => {
    if (keptProduct[product] !== 1) return;
    if (cap === undefined) {
      kept[row] = 1;
    } else if (modeled[rows.user[row] ?? -1] === 1) {
      kept[row] = 1;
      modeledCount.set(product, (modeledCount.get(product) ?? 0) + 1);
    } else {
      const list = others.get(product);
      if (list === undefined) others.set(product, [row]);
      else list.push(row);
    }
  });
  if (cap !== undefined) {
    for (const [product, list] of others) {
      const chosen = capReviews(productIds[product] ?? '', list, modeledCount.get(product) ?? 0, {
        cap,
        seed: options.seed,
      });
      for (const row of chosen) kept[row] = 1;
    }
  }
  return kept;
}

/**
 * Second pass over the reviews: write the kept reviews in source order,
 * and the User events of the modeled users sorted by user and time.
 */
async function writeReviewsAndEvents(
  file: string,
  outDir: string,
  sample: { readonly rows: Rows; readonly keptRow: Uint8Array; readonly modeled: Uint8Array },
): Promise<{ reviews: number; reviewEvents: number; purchaseEvents: number }> {
  const events: UserEvent[] = [];
  async function* keptReviews(): AsyncGenerator<BundleReview> {
    let next = 0;
    for await (const { line, text } of readJsonlLines(file)) {
      if (sample.rows.line[next] !== line) continue;
      const row = next;
      next += 1;
      if (sample.keptRow[row] !== 1) continue;
      const review = parseRow(reviewRowSchema, text, file, line);
      const hash = reviewKey(review);
      const isModeled = sample.modeled[sample.rows.user[row] ?? -1] === 1;
      yield toReview(review, hash, isModeled);
      if (isModeled) events.push(...toEvents(review, hash));
    }
  }
  const reviews = await writeJsonl(path.join(outDir, BUNDLE_FILES.reviews), keptReviews());
  events.sort(
    (a, b) =>
      compareStrings(a.user_id, b.user_id) ||
      compareStrings(a.timestamp, b.timestamp) ||
      eventOrder(a) - eventOrder(b) ||
      compareStrings(a.event_id, b.event_id),
  );
  await writeJsonl(path.join(outDir, BUNDLE_FILES.events), events);
  const purchaseEvents = events.filter((event) => event.event_type === 'purchase').length;
  return { reviews, reviewEvents: events.length - purchaseEvents, purchaseEvents };
}

/** A purchase comes before the review that it gave. */
function eventOrder(event: UserEvent): number {
  return event.event_type === 'purchase' ? 0 : 1;
}

function toReview(row: ReviewRow, hash: string, isModeled: boolean): BundleReview {
  return {
    review_id: `r-${hash}`,
    product_id: row.parent_asin,
    variant_id: row.asin,
    ...(isModeled ? { user_id: row.user_id } : {}),
    rating: row.rating,
    title: row.title,
    body: row.text,
    created_at: new Date(row.timestamp).toISOString(),
    verified_purchase: row.verified_purchase,
    helpful_votes: Math.max(0, row.helpful_vote),
  };
}

function toEvents(row: ReviewRow, hash: string): UserEvent[] {
  const base = {
    user_id: row.user_id,
    timestamp: new Date(row.timestamp).toISOString(),
    product_id: row.parent_asin,
    variant_id: row.asin,
  };
  const review: UserEvent = {
    event_id: `e-${hash}-review`,
    ...base,
    timestamp_precision: 'ms',
    event_type: 'review',
    raw_type: 'review',
  };
  if (!row.verified_purchase) return [review];
  const purchase: UserEvent = {
    event_id: `e-${hash}-purchase`,
    ...base,
    timestamp_precision: 'order',
    event_type: 'purchase',
    raw_type: 'verified_purchase',
    provenance: { '*': 'inferred' },
  };
  return [purchase, review];
}

/** Second pass over the meta file: write the kept products sorted by id. */
async function writeProducts(
  file: string,
  outDir: string,
  sample: {
    readonly catalog: Catalog;
    readonly keptProduct: Uint8Array;
    readonly variants: readonly ReadonlySet<string>[];
  },
): Promise<{ products: number; variants: number; withoutPrice: number }> {
  const keptIds = new Set(sample.catalog.ids.filter((_, i) => sample.keptProduct[i] === 1));
  const products: BundleProduct[] = [];
  const done = new Set<string>();
  for await (const { line, text } of readJsonlLines(file)) {
    const row = parseRow(metaRowSchema, text, file, line);
    const product = sample.catalog.index.get(row.parent_asin);
    if (product === undefined || sample.keptProduct[product] !== 1 || done.has(row.parent_asin)) {
      continue;
    }
    done.add(row.parent_asin);
    const variants = [...(sample.variants[product] ?? [])].sort(compareStrings);
    products.push(toProduct(row, variants, keptIds));
  }
  products.sort((a, b) => compareStrings(a.product_id, b.product_id));
  await writeJsonl(path.join(outDir, BUNDLE_FILES.products), products);
  return {
    products: products.length,
    variants: products.reduce((sum, product) => sum + product.variants.length, 0),
    withoutPrice: products.filter((product) => product.variants[0]?.price === undefined).length,
  };
}

function toProduct(
  row: MetaRow,
  variantIds: readonly string[],
  keptIds: ReadonlySet<string>,
): BundleProduct {
  const amount = parsePrice(row.price);
  const description = (row.description ?? []).flatMap(nonEmpty).join('\n');
  const bullets = (row.features ?? []).flatMap(nonEmpty);
  const brand = typeof row.details?.Brand === 'string' ? cleanText(row.details.Brand) : undefined;
  const seller = cleanText(row.store);
  const category = categoryPath(row);
  const attributes = Object.fromEntries(
    Object.entries(row.details ?? {}).flatMap(([key, value]) => {
      const name = cleanText(key);
      const text = typeof value === 'string' ? cleanText(value) : undefined;
      return name !== undefined && name !== 'Brand' && text !== undefined ? [[name, text]] : [];
    }),
  );
  const images = (row.images ?? []).flatMap((image) => {
    const url = cleanText(image.large);
    return url !== undefined ? [{ source_url: url }] : [];
  });
  const boughtTogether = (row.bought_together ?? []).filter(
    (id) => id !== row.parent_asin && keptIds.has(id),
  );
  return {
    product_id: row.parent_asin,
    // The catalog holds only products with a title, so the fallback is never used.
    title: cleanText(row.title) ?? row.parent_asin,
    ...(description !== '' ? { description } : {}),
    ...(bullets.length > 0 ? { bullets } : {}),
    ...(brand !== undefined ? { brand } : {}),
    ...(seller !== undefined ? { seller } : {}),
    ...(category.length > 0 ? { category_path: category } : {}),
    ...(Object.keys(attributes).length > 0 ? { attributes } : {}),
    variants: variantIds.map((variant_id) => ({
      variant_id,
      ...(amount !== undefined ? { price: { amount, currency: CURRENCY } } : {}),
    })),
    ...(images.length > 0 ? { images } : {}),
    ...(boughtTogether.length > 0 ? { related: { bought_together: boughtTogether } } : {}),
    source: { dataset: AR23_DATASET, id: row.parent_asin },
    ...(amount !== undefined ? { provenance: { 'variants[].price': 'inferred' } } : {}),
  };
}

/** A number, or text such as `from 29.99`; other text (for example a dash) is no price. */
function parsePrice(price: MetaRow['price']): number | undefined {
  if (typeof price === 'number') return Number.isFinite(price) && price >= 0 ? price : undefined;
  const match = /^(?:from\s+)?\$?(\d+(?:\.\d+)?)$/i.exec(price?.trim() ?? '');
  return match?.[1] !== undefined ? Number(match[1]) : undefined;
}

function categoryPath(row: MetaRow): string[] {
  return (row.categories ?? []).flatMap(nonEmpty);
}

function cleanText(value: string | null | undefined): string | undefined {
  const text = value?.trim();
  return text !== undefined && text !== '' ? text : undefined;
}

function nonEmpty(value: string): string[] {
  const text = cleanText(value);
  return text !== undefined ? [text] : [];
}

/** The fields that make two review rows exact duplicates. */
function reviewKey(row: ReviewRow): string {
  return hashKey(
    [row.user_id, row.asin, row.timestamp, row.rating, row.title, row.text].join('\0'),
  );
}

function hashKey(text: string): string {
  return createHash('sha256').update(text).digest('hex').slice(0, 16);
}
