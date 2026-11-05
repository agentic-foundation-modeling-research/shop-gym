/**
 * `synth_reviews`: read-only product Reviews. Code plans every Review from
 * a fixed seed, so no LLM call decides its shape. About 15% of the
 * products get no Reviews. Each other product gets one to eight. The
 * ratings average about 4.3. Each Review gets a reviewer (first name and
 * last initial), a date in the two years before the Episode clock starts,
 * a variant of its product, a Verified Buyer flag and a helpful count.
 * The LLM writes only the title and text of each Review. It gets the
 * product facts and the planned rating, in batches of whole products.
 */

import { DEFAULT_EPISODE_START, datasetSchema } from '@shop-gym/shop-backend';
import type { z } from 'zod';

import { findAllowlistedToken } from '../brands/allowlist.js';
import { mapLimit } from '../io.js';
import { completeStructured } from '../llm.js';
import { type SynthContext, cached, pretty, synthPrompt } from './context.js';
import { pick, randomMinuteBefore, seededRandom, takeRandom } from './ids.js';
import { type ReviewText, reviewTextsSchema } from './schemas.js';

type Product = z.infer<typeof datasetSchema.productSchema>;
export type Review = z.infer<typeof datasetSchema.reviewSchema>;
/** A Review before the LLM writes its title and text. */
type PlannedReview = Omit<Review, 'title' | 'body'>;

/** One product with the Reviews planned for it. */
interface ProductPlan {
  readonly product: Product;
  readonly reviews: readonly PlannedReview[];
}

const SEED = 'reviews';
const NO_REVIEW_SHARE = 0.15;
const MAX_REVIEWS_PER_PRODUCT = 8;
/** A bag of 50 ratings from 1 to 5 in the proportion 2:2:5:11:30, which averages 4.3. */
const RATINGS = [2, 2, 5, 11, 30].flatMap((weight, i) =>
  Array.from({ length: weight }, () => i + 1),
);
const VERIFIED_BUYER_SHARE = 0.8;
/** Helpful counts stay below this; most are small and about a third are 0. */
const MAX_HELPFUL_COUNT = 30;
const HISTORY_MINUTES = 2 * 365 * 24 * 60;
/** Most Reviews one LLM call writes; the Reviews of one product always share a call. */
const BATCH_SIZE = 20;
const TITLE_MIN = 3;
const TITLE_MAX = 80;
const BODY_MIN = 20;
const BODY_MAX = 600;
const FIRST_NAMES = [
  'Maya',
  'Tom',
  'Ana',
  'Liam',
  'Priya',
  'Noah',
  'Sofia',
  'Ethan',
  'Aisha',
  'Lucas',
  'Chloe',
  'Mateo',
  'Grace',
  'Omar',
  'Hannah',
  'Kai',
  'Elena',
  'Ben',
  'Zoe',
  'Ravi',
  'Isla',
  'Leo',
  'Nina',
  'Sam',
  'Mei',
  'Jonas',
  'Clara',
  'Diego',
  'Ruth',
  'Felix',
];
const LAST_INITIALS = [...'ABCDEFGHJKLMNPRSTW'];

/**
 * Draws ratings at random from a bag that holds `RATINGS` and is filled
 * again when empty, so every 50 draws average exactly 4.3.
 */
function ratingDraws(rng: () => number): () => number {
  const bag: number[] = [];
  return () => {
    if (bag.length === 0) bag.push(...RATINGS);
    // The bag was filled when it was empty, so it has a rating to take.
    return takeRandom(rng, bag) as number;
  };
}

/**
 * The Reviews of each product that gets any, in catalog order, numbered
 * from 1. A product with no variants gets none, because a Review names
 * the variant bought.
 */
function planReviews(products: readonly Product[]): ProductPlan[] {
  const rng = seededRandom(SEED);
  const reviewable = products.filter((p) => p.variants.length > 0);
  const candidates = reviewable.map((p) => p.handle);
  const withoutReviews = new Set<string>();
  for (let i = 0; i < Math.round(NO_REVIEW_SHARE * reviewable.length); i += 1) {
    const handle = takeRandom(rng, candidates);
    if (handle !== undefined) withoutReviews.add(handle);
  }
  const drawRating = ratingDraws(rng);
  let id = 0;
  return reviewable
    .filter((product) => !withoutReviews.has(product.handle))
    .map((product) => ({
      product,
      reviews: Array.from({ length: 1 + Math.floor(rng() * MAX_REVIEWS_PER_PRODUCT) }, () => {
        id += 1;
        return {
          id,
          product_handle: product.handle,
          variant_id: pick(rng, product.variants).id,
          rating: drawRating(),
          reviewer_name: `${pick(rng, FIRST_NAMES)} ${pick(rng, LAST_INITIALS)}.`,
          created_at: randomMinuteBefore(rng, DEFAULT_EPISODE_START, HISTORY_MINUTES),
          verified_buyer: rng() < VERIFIED_BUYER_SHARE,
          helpful_count: Math.floor(MAX_HELPFUL_COUNT * rng() ** 3),
        };
      }),
    }));
}

/** Packs whole products, in order, into batches of at most `BATCH_SIZE` Reviews. */
function batches(plans: readonly ProductPlan[]): ProductPlan[][] {
  const out: ProductPlan[][] = [];
  let current: ProductPlan[] = [];
  let size = 0;
  for (const plan of plans) {
    if (size + plan.reviews.length > BATCH_SIZE) {
      out.push(current);
      current = [];
      size = 0;
    }
    current.push(plan);
    size += plan.reviews.length;
  }
  if (current.length > 0) out.push(current);
  return out;
}

/** The first problem with the LLM's `texts` for the `planned` Reviews, or `undefined`. */
function textsProblem(
  sc: SynthContext,
  planned: readonly PlannedReview[],
  texts: readonly ReviewText[],
): string | undefined {
  const expected = planned.map((r) => r.id);
  const got = texts.map((t) => t.id);
  if (got.length !== expected.length || expected.some((id) => !got.includes(id))) {
    return `expected one entry for each review id ${expected.join(', ')}, got ids ${got.join(', ')}`;
  }
  for (const { id, title, body } of texts) {
    if (title.length < TITLE_MIN || title.length > TITLE_MAX) {
      return `title of review ${id} must be ${TITLE_MIN}-${TITLE_MAX} chars: ${JSON.stringify(title)}`;
    }
    if (body.length < BODY_MIN || body.length > BODY_MAX) {
      return `body of review ${id} must be ${BODY_MIN}-${BODY_MAX} chars: ${JSON.stringify(body)}`;
    }
    const token = findAllowlistedToken(`${title} ${body}`, sc.allowlist);
    if (token !== undefined) return `review ${id} contains brand token ${token}`;
  }
  return undefined;
}

/** Asks the LLM for the title and text of every Review in `batch`. */
async function writeBatch(sc: SynthContext, batch: readonly ProductPlan[]): Promise<Review[]> {
  const planned = batch.flatMap((p) => p.reviews);
  const products = batch.map(({ product, reviews }) => ({
    title: product.title,
    product_type: product.product_type,
    tags: product.tags,
    description_html: product.description_html,
    reviews: reviews.map((r) => ({
      id: r.id,
      rating: r.rating,
      variant: product.variants.find((v) => v.id === r.variant_id)?.title,
    })),
  }));
  const texts = await completeStructured(
    sc.call,
    synthPrompt(sc, 'synth_reviews', {
      products: pretty(products),
      title_min: String(TITLE_MIN),
      title_max: String(TITLE_MAX),
      body_min: String(BODY_MIN),
      body_max: String(BODY_MAX),
    }),
    reviewTextsSchema,
    (reply) => textsProblem(sc, planned, reply),
  );
  const byId = new Map(texts.map((t) => [t.id, t]));
  // The keys follow the order of the backend Review schema, so a run that
  // reads the stage cache writes the same bytes as the run that wrote it.
  return planned.map(({ id, product_handle, variant_id, rating, ...rest }) => {
    // `textsProblem` accepted the reply, so it has a text for every planned id.
    const { title, body } = byId.get(id) as ReviewText;
    return { id, product_handle, variant_id, rating, title, body, ...rest };
  });
}

/** The Reviews of `products`, cached as `reviews.json` in the stage cache. */
export function synthReviews(
  sc: SynthContext,
  products: readonly Product[],
): Promise<readonly Review[]> {
  return cached(sc, 'reviews.json', datasetSchema.reviewsFileSchema, async () => {
    const written = await mapLimit(batches(planReviews(products)), sc.config.concurrency, (b) =>
      writeBatch(sc, b),
    );
    return written.flat();
  });
}
