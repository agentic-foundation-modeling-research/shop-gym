/**
 * User profiles of the complete step, for a bundle that has User events
 * but no profiles. An LLM writes one profile per modeled user from that
 * user's history before the cutoff: the products that the user bought
 * and reviewed, with the review text. The prompt also gives the catalog's
 * top categories and its price range, and each interest of the profile
 * must be a category path of the catalog. The profile is marked
 * `synthetic` as a whole and has no account fields.
 */

import { fileURLToPath } from 'node:url';

import {
  type BundleProduct,
  type BundleReview,
  COMPLETE_SCHEMAS,
  type UserEvent,
  type UserProfile,
} from '@shop-gym/core';
import type { z } from 'zod';

import { mapLimit } from '../../gen/io.js';
import { type LlmCall, loadPrompt } from '../../gen/llm.js';
import { compareStrings } from '../sample.js';
import { cachedStructured } from './llm_cache.js';

const PROMPTS_DIR = fileURLToPath(new URL('./prompts/', import.meta.url));
/** The prompt shows at most this many of the latest history items. */
const MAX_HISTORY = 40;
const MAX_REVIEW_CHARS = 400;
/** The prompt shows category paths down to this depth, the largest first. */
const CATEGORY_DEPTH = 3;
const MAX_CATEGORIES = 50;
const MAX_INTERESTS = 5;
const PATH_SEPARATOR = '\u001f';

const profileReplySchema = COMPLETE_SCHEMAS.profile.omit({ user_id: true, provenance: true });

type ProfileReply = z.infer<typeof profileReplySchema>;

export interface ProfileInputs {
  readonly products: readonly BundleProduct[];
  readonly events: readonly UserEvent[];
  /** The reviews that name a user. */
  readonly reviews: readonly BundleReview[];
  /** ISO 8601 time. */
  readonly cutoff: string;
  readonly currency: string;
}

export interface ProfileDeps {
  readonly call: LlmCall;
  readonly cacheDir: string;
  readonly concurrency: number;
  readonly log: (line: string) => void;
}

interface HistoryItem {
  readonly date: string;
  readonly product: {
    readonly title: string;
    readonly brand?: string;
    readonly category_path?: readonly string[];
    readonly price?: number;
  };
  readonly bought: boolean;
  readonly review?: { readonly rating: number; readonly title: string; readonly text: string };
}

/**
 * One profile per user that has User events, sorted by user id.
 *
 * @throws SynthError when a reply is still not valid after one repair call.
 */
export async function writeProfiles(
  inputs: ProfileInputs,
  deps: ProfileDeps,
): Promise<UserProfile[]> {
  const catalog = catalogSummary(inputs.products);
  const histories = historiesBefore(inputs);
  const users = [...histories.keys()].sort(compareStrings);
  const cutoffDate = inputs.cutoff.slice(0, 10);
  let cached = 0;
  const profiles = await mapLimit(users, deps.concurrency, async (userId) => {
    const prompt = loadPrompt(PROMPTS_DIR, 'user_profile', {
      cutoff: cutoffDate,
      categories: JSON.stringify(catalog.categories, null, 2),
      price_min: catalog.prices.min,
      price_median: catalog.prices.median,
      price_max: catalog.prices.max,
      currency: inputs.currency,
      history: JSON.stringify(histories.get(userId) ?? [], null, 2),
    });
    const reply = await cachedStructured(
      deps.cacheDir,
      deps.call,
      prompt,
      profileReplySchema,
      (value) => checkInterests(value, catalog.prefixes),
    );
    if (reply.cached) cached += 1;
    return COMPLETE_SCHEMAS.profile.parse({
      user_id: userId,
      ...reply.value,
      provenance: { '*': 'synthetic' },
    });
  });
  deps.log(`[complete] profiles: ${users.length} users (${cached} from the cache)`);
  return profiles;
}

interface CatalogSummary {
  readonly categories: readonly { readonly path: readonly string[]; readonly products: number }[];
  /** Every category path prefix of the catalog. */
  readonly prefixes: ReadonlySet<string>;
  readonly prices: { readonly min: string; readonly median: string; readonly max: string };
}

function catalogSummary(products: readonly BundleProduct[]): CatalogSummary {
  const shown = new Map<string, number>();
  const prefixes = new Set<string>();
  const amounts: number[] = [];
  for (const product of products) {
    const categoryPath = product.category_path ?? [];
    for (let depth = 1; depth <= categoryPath.length; depth += 1) {
      const key = categoryPath.slice(0, depth).join(PATH_SEPARATOR);
      prefixes.add(key);
      if (depth <= CATEGORY_DEPTH) shown.set(key, (shown.get(key) ?? 0) + 1);
    }
    const price = product.variants.find((variant) => variant.price !== undefined)?.price;
    if (price !== undefined) amounts.push(price.amount);
  }
  const categories = [...shown]
    .sort((a, b) => b[1] - a[1] || compareStrings(a[0], b[0]))
    .slice(0, MAX_CATEGORIES)
    .map(([key, count]) => ({ path: key.split(PATH_SEPARATOR), products: count }));
  amounts.sort((a, b) => a - b);
  const at = (index: number): string => (amounts[index] ?? 0).toFixed(2);
  return {
    categories,
    prefixes,
    prices: {
      min: at(0),
      median: at(Math.floor((amounts.length - 1) / 2)),
      max: at(amounts.length - 1),
    },
  };
}

/** The history items of each user that has User events, from the events before the cutoff. */
function historiesBefore(inputs: ProfileInputs): Map<string, HistoryItem[]> {
  const cutoffMs = Date.parse(inputs.cutoff);
  const products = new Map(inputs.products.map((product) => [product.product_id, product]));
  const reviews = new Map(
    inputs.reviews.map((review) => [
      reviewKey(review.user_id ?? '', review.product_id, review.created_at),
      review,
    ]),
  );
  const groups = new Map<string, Map<string, UserEvent[]>>();
  for (const event of inputs.events) {
    let user = groups.get(event.user_id);
    if (user === undefined) {
      user = new Map();
      groups.set(event.user_id, user);
    }
    if (event.product_id === undefined || Date.parse(event.timestamp) >= cutoffMs) continue;
    const key = reviewKey(event.user_id, event.product_id, event.timestamp);
    const group = user.get(key);
    if (group === undefined) user.set(key, [event]);
    else group.push(event);
  }
  const histories = new Map<string, HistoryItem[]>();
  for (const [userId, user] of groups) {
    const items = [...user.entries()]
      .sort((a, b) => compareStrings(a[0], b[0]))
      .map(([key, events]) => historyItem(key, events, products, reviews));
    histories.set(userId, items.slice(-MAX_HISTORY));
  }
  return histories;
}

/** A user, a time and a product; the time comes first so that the keys of one user sort by time. */
function reviewKey(userId: string, productId: string, time: string): string {
  return [userId, String(Date.parse(time)).padStart(16, '0'), productId].join('\0');
}

function historyItem(
  key: string,
  events: readonly UserEvent[],
  products: ReadonlyMap<string, BundleProduct>,
  reviews: ReadonlyMap<string, BundleReview>,
): HistoryItem {
  // Every event of the group names the same product and time.
  const first = events[0] as UserEvent;
  const product = products.get(first.product_id ?? '');
  const review = events.some((event) => event.event_type === 'review')
    ? reviews.get(key)
    : undefined;
  const price = product?.variants.find((variant) => variant.price !== undefined)?.price;
  return {
    date: first.timestamp.slice(0, 10),
    product: {
      title: product?.title ?? first.product_id ?? '',
      ...(product?.brand !== undefined ? { brand: product.brand } : {}),
      ...(product?.category_path !== undefined ? { category_path: product.category_path } : {}),
      ...(price !== undefined ? { price: price.amount } : {}),
    },
    bought: events.some((event) => event.event_type === 'purchase'),
    ...(review !== undefined
      ? {
          review: {
            rating: review.rating,
            title: review.title,
            text: review.body.slice(0, MAX_REVIEW_CHARS),
          },
        }
      : {}),
  };
}

function checkInterests(reply: ProfileReply, prefixes: ReadonlySet<string>): string | undefined {
  const interests = reply.preferences.category_interests ?? [];
  if (interests.length === 0 || interests.length > MAX_INTERESTS) {
    return `preferences.category_interests must have 1 to ${MAX_INTERESTS} category paths`;
  }
  const unknown = interests.find((interest) => !prefixes.has(interest.join(PATH_SEPARATOR)));
  if (unknown !== undefined) {
    return `preferences.category_interests: ${JSON.stringify(unknown)} is not a category path of the catalog`;
  }
  return undefined;
}
