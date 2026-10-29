import { Form } from 'react-router';
import { formatDate } from '~/components/account';
import { variantTitle } from '~/components/checkout';
import {
  type ProductRating,
  REVIEW_PAGES_PARAM,
  REVIEW_SORTS,
  REVIEW_SORT_PARAM,
  type ReviewView,
} from '~/lib/reviews';
import type { ProductDetail, Review } from '~/lib/types';

const STAR_POSITIONS = [1, 2, 3, 4, 5] as const;

/** The top of the rating scale of one Review. */
const REVIEW_SCALE_MAX = '5';

/** Dawn's rating block near the product title: the stars, "3.8 / 5.0", then "(6)". */
export function RatingBlock({ rating }: { readonly rating: ProductRating }) {
  return <RatingLine rating={rating} countText={`(${rating.count})`} />;
}

/**
 * The "Reviews" section below the product details: the rating at the top, a
 * "Sort by" control, the Reviews, and a "Show more reviews" button while
 * more Reviews remain. Renders nothing for a product with no Reviews. Both
 * forms reload the product page at `productPath` with the new view.
 */
export function ReviewsSection({
  productPath,
  reviews,
  rating,
  view,
}: {
  readonly productPath: string;
  readonly reviews: ProductDetail['reviews'];
  readonly rating: ProductRating | null;
  readonly view: ReviewView;
}) {
  if (reviews.nodes.length === 0) return null;
  const action = `${productPath}#reviews`;
  return (
    <section id="reviews" className="page-width stack reviews" aria-labelledby="reviews-heading">
      <h2 id="reviews-heading">Reviews</h2>
      {rating ? (
        <RatingLine
          rating={rating}
          countText={`${rating.count} ${rating.count === 1 ? 'review' : 'reviews'}`}
        />
      ) : null}
      <Form method="get" action={action} className="reviews-sort" reloadDocument>
        <label htmlFor="reviews-sort">Sort by</label>
        <select id="reviews-sort" name={REVIEW_SORT_PARAM} defaultValue={view.sort.param}>
          {REVIEW_SORTS.map((sort) => (
            <option key={sort.param} value={sort.param}>
              {sort.label}
            </option>
          ))}
        </select>
        <button type="submit">Sort</button>
      </Form>
      <ol className="review-list">
        {reviews.nodes.map((review) => (
          <li key={review.id}>
            <ReviewBlock review={review} />
          </li>
        ))}
      </ol>
      {reviews.pageInfo.hasNextPage ? (
        <Form method="get" action={action} reloadDocument>
          <input type="hidden" name={REVIEW_SORT_PARAM} value={view.sort.param} />
          <input type="hidden" name={REVIEW_PAGES_PARAM} value={view.pages + 1} />
          <button type="submit">Show more reviews</button>
        </Form>
      ) : null}
    </section>
  );
}

/** One Review; an element with no data is left out. */
function ReviewBlock({ review }: { readonly review: Review }) {
  const variant = variantText(review.variant);
  const helpful = helpfulText(review.helpfulCount);
  return (
    <article className="review">
      <Stars rating={String(review.rating)} scaleMax={REVIEW_SCALE_MAX} />
      {review.title ? <h3>{review.title}</h3> : null}
      {review.body ? <p>{review.body}</p> : null}
      <p className="muted">
        {review.reviewerName ? <>{review.reviewerName} </> : null}
        {review.verifiedBuyer ? (
          <>
            <span className="badge">Verified Buyer</span>{' '}
          </>
        ) : null}
        <time dateTime={review.createdAt}>{formatDate(review.createdAt)}</time>
      </p>
      {variant ? <p className="muted">{variant}</p> : null}
      {helpful ? <p className="muted">{helpful}</p> : null}
    </article>
  );
}

/** The stars, the rating as "<value> / <scale max>", then `countText`. */
function RatingLine({
  rating,
  countText,
}: {
  readonly rating: ProductRating;
  readonly countText: string;
}) {
  return (
    <p className="rating">
      <Stars rating={rating.value} scaleMax={rating.scaleMax} />{' '}
      <span>
        {rating.value} / {rating.scaleMax}
      </span>{' '}
      <span className="muted">{countText}</span>
    </p>
  );
}

/** Five stars for `rating`, named "<rating> out of <scaleMax> stars". */
function Stars({
  rating,
  scaleMax,
}: {
  /** As shown, e.g. "3.8" or "4". */
  readonly rating: string;
  readonly scaleMax: string;
}) {
  return (
    <span className="stars" role="img" aria-label={`${rating} out of ${scaleMax} stars`}>
      {STAR_POSITIONS.map((position) => (
        <span key={position} className={`star star-${starFill(Number(rating), position)}`} />
      ))}
    </span>
  );
}

/**
 * The fill of the star at `position` (1 to 5) for `rating`: a decimal part
 * from 0.3 to 0.7 gives a half star, and above 0.7 a full star.
 */
function starFill(rating: number, position: number): 'full' | 'half' | 'empty' {
  // In tenths, so that 4.3 gives 3 and not 2.99.
  const tenths = Math.round(rating * 10) - (position - 1) * 10;
  if (tenths > 7) return 'full';
  if (tenths >= 3) return 'half';
  return 'empty';
}

/**
 * The options of the variant bought, e.g. "Size: M / Color: Black"; null for
 * a product with one variant.
 */
function variantText(variant: Review['variant']): string | null {
  if (variant === null || variantTitle(variant.title) === null) return null;
  return variant.selectedOptions.map((option) => `${option.name}: ${option.value}`).join(' / ');
}

/** "1 person found this helpful", "12 people found this helpful", or null for 0. */
function helpfulText(count: number): string | null {
  if (count === 0) return null;
  return count === 1 ? '1 person found this helpful' : `${count} people found this helpful`;
}
