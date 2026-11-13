import type { ProductDetail } from '~/lib/types';

/** Reviews that each "Show more reviews" press adds. */
export const REVIEW_PAGE_SIZE = 5;

/** URL parameter of the Reviews order, e.g. `?reviews_sort=lowest_rating`. */
export const REVIEW_SORT_PARAM = 'reviews_sort';

/** URL parameter of the number of Review pages shown, e.g. `?reviews_pages=2`. */
export const REVIEW_PAGES_PARAM = 'reviews_pages';

/** URL parameter of the star rating filter, e.g. `?reviews_rating=4`. */
export const REVIEW_RATING_PARAM = 'reviews_rating';

/** URL parameter that shows only the Reviews of Verified Buyers: `?reviews_verified=true`. */
export const REVIEW_VERIFIED_PARAM = 'reviews_verified';

/** The star ratings of the "Rating" filter, from the top of the scale down. */
export const REVIEW_RATINGS = [5, 4, 3, 2, 1] as const;

/** The Reviews orders of the "Sort by" control, the default first. */
export const REVIEW_SORTS = [
  { param: 'most_recent', label: 'Most recent', sortKey: 'MOST_RECENT' },
  { param: 'highest_rating', label: 'Highest rating', sortKey: 'HIGHEST_RATING' },
  { param: 'lowest_rating', label: 'Lowest rating', sortKey: 'LOWEST_RATING' },
  { param: 'most_helpful', label: 'Most helpful', sortKey: 'MOST_HELPFUL' },
] as const;

export type ReviewSort = (typeof REVIEW_SORTS)[number];

/** The Reviews a product page shows: their order, their filters and how many pages of them. */
export interface ReviewView {
  readonly sort: ReviewSort;
  readonly pages: number;
  /** Only the Reviews with this star rating, 1 to 5; null for every rating. */
  readonly rating: number | null;
  /** Only the Reviews of Verified Buyers. */
  readonly verifiedOnly: boolean;
}

/** A product rating, read from its `reviews.rating` and `reviews.rating_count` metafields. */
export interface ProductRating {
  /** The mean rating, e.g. "3.8". */
  readonly value: string;
  /** The top of the rating scale, e.g. "5.0". */
  readonly scaleMax: string;
  readonly count: number;
}

/** The Reviews view that `url` asks for; a missing or unknown value gives the default. */
export function reviewViewOf(url: URL): ReviewView {
  const sortParam = url.searchParams.get(REVIEW_SORT_PARAM);
  const pages = Number(url.searchParams.get(REVIEW_PAGES_PARAM));
  const rating = Number(url.searchParams.get(REVIEW_RATING_PARAM));
  return {
    sort: REVIEW_SORTS.find((sort) => sort.param === sortParam) ?? REVIEW_SORTS[0],
    pages: Number.isInteger(pages) && pages > 0 ? pages : 1,
    rating: REVIEW_RATINGS.find((value) => value === rating) ?? null,
    verifiedOnly: url.searchParams.get(REVIEW_VERIFIED_PARAM) === 'true',
  };
}

/**
 * The URL parameters of `view` as name and value pairs, in a fixed order.
 * A default is left out: the most recent first, every rating, every
 * reviewer, one page.
 */
export function reviewViewParams(view: ReviewView): [string, string][] {
  const params: [string, string][] = [];
  if (view.sort.param !== REVIEW_SORTS[0].param) params.push([REVIEW_SORT_PARAM, view.sort.param]);
  if (view.rating !== null) params.push([REVIEW_RATING_PARAM, String(view.rating)]);
  if (view.verifiedOnly) params.push([REVIEW_VERIFIED_PARAM, 'true']);
  if (view.pages > 1) params.push([REVIEW_PAGES_PARAM, String(view.pages)]);
  return params;
}

/** The link to the Reviews section of product page `productPath` with the Reviews `view`. */
export function reviewViewHref(productPath: string, view: ReviewView): string {
  const search = new URLSearchParams(reviewViewParams(view)).toString();
  return `${productPath}${search ? `?${search}` : ''}#reviews`;
}

/** The rating of `product`; null when it has no Reviews. */
export function productRatingOf(
  product: Pick<ProductDetail, 'rating' | 'ratingCount'>,
): ProductRating | null {
  if (product.rating === null || product.ratingCount === null) return null;
  // The Shopify `rating` metafield type, e.g. {"value":"3.8","scale_min":"1.0","scale_max":"5.0"}.
  // The backend computes this metafield from the Reviews in this shape, so the cast holds.
  const rating = JSON.parse(product.rating.value) as {
    readonly value: string;
    readonly scale_max: string;
  };
  return {
    value: rating.value,
    scaleMax: rating.scale_max,
    count: Number(product.ratingCount.value),
  };
}
