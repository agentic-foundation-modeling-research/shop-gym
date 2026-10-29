/**
 * Read-only product Reviews from `reviews.json` (`@sandbox`).
 *
 *   - `Product.reviews(first, after, sortKey)` pages the product's Reviews
 *     in one of four orders. Ties put the more recent Review first, then
 *     keep the `reviews.json` order, so every read gives the same list.
 *   - `ratingMetafields` computes the standard product metafields
 *     `reviews.rating` and `reviews.rating_count` from the same Reviews, so
 *     the stars and the count always agree with the list.
 */

import type { ProductReviewsArgs, ReviewSortKeys } from '../__generated__/resolvers-types.js';
import { type Connection, paginate } from '../data/pagination.js';
import type { Metafield, Review } from '../data/types.js';
import { type ProductNode, type ProductVariantNode, gid } from './builders.js';
import type { ResolverContext } from './index.js';

export interface ReviewNode {
  readonly id: string;
  readonly rating: number;
  readonly title: string;
  readonly body: string;
  readonly reviewerName: string;
  readonly createdAt: string;
  readonly verifiedBuyer: boolean;
  readonly helpfulCount: number;
  readonly variant: ProductVariantNode | null;
}

/** Namespace of the standard product rating metafields. */
const RATING_NAMESPACE = 'reviews';
const RATING_KEY = 'rating';
const RATING_COUNT_KEY = 'rating_count';

export const reviewResolvers = {
  Product: {
    reviews: (
      parent: ProductNode,
      args: Partial<ProductReviewsArgs>,
      ctx: ResolverContext,
    ): Connection<ReviewNode> => {
      const reviews = ctx.data.reviewsByProductHandle.get(parent.handle) ?? [];
      const sorted = sortReviews(reviews, args.sortKey ?? 'MOST_RECENT');
      return paginate(
        sorted.map((review) => buildReviewNode(review, parent.variants)),
        args,
      );
    },
  },
};

/**
 * The `reviews.rating` and `reviews.rating_count` metafields of a product
 * with `reviews`, or none when it has no Reviews. The rating is the mean,
 * rounded half up to one decimal, in Shopify's `rating` JSON shape.
 */
export function ratingMetafields(reviews: readonly Review[]): readonly Metafield[] {
  if (reviews.length === 0) return [];
  const sum = reviews.reduce((total, review) => total + review.rating, 0);
  const tenths = Math.round((sum * 10) / reviews.length);
  return [
    {
      namespace: RATING_NAMESPACE,
      key: RATING_KEY,
      value: JSON.stringify({
        value: (tenths / 10).toFixed(1),
        scale_min: '1.0',
        scale_max: '5.0',
      }),
      type: 'rating',
    },
    {
      namespace: RATING_NAMESPACE,
      key: RATING_COUNT_KEY,
      value: String(reviews.length),
      type: 'number_integer',
    },
  ];
}

/** Whether `metafield` is one of the two that `ratingMetafields` computes. */
export function isRatingMetafield(metafield: Metafield): boolean {
  return (
    metafield.namespace === RATING_NAMESPACE &&
    (metafield.key === RATING_KEY || metafield.key === RATING_COUNT_KEY)
  );
}

function sortReviews(reviews: readonly Review[], sortKey: ReviewSortKeys): readonly Review[] {
  // `Array.prototype.sort` is stable, so equal Reviews keep the file order.
  return [...reviews].sort(
    (a, b) => comparePrimary(a, b, sortKey) || Date.parse(b.created_at) - Date.parse(a.created_at),
  );
}

function comparePrimary(a: Review, b: Review, sortKey: ReviewSortKeys): number {
  switch (sortKey) {
    case 'MOST_RECENT':
      return 0;
    case 'HIGHEST_RATING':
      return b.rating - a.rating;
    case 'LOWEST_RATING':
      return a.rating - b.rating;
    case 'MOST_HELPFUL':
      return b.helpful_count - a.helpful_count;
  }
}

function buildReviewNode(review: Review, variants: readonly ProductVariantNode[]): ReviewNode {
  const variantId = gid('ProductVariant', review.variant_id);
  return {
    id: gid('Review', review.id),
    rating: review.rating,
    title: review.title,
    body: review.body,
    reviewerName: review.reviewer_name,
    createdAt: review.created_at,
    verifiedBuyer: review.verified_buyer,
    helpfulCount: review.helpful_count,
    variant: variants.find((variant) => variant.id === variantId) ?? null,
  };
}
