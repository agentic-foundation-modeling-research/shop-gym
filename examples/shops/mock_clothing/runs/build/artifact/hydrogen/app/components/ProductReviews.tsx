import {useState} from 'react';
import {hashString, formatRating} from '~/lib/productColors';

const REVIEW_BODIES = [
  "Honestly the best I've worn in years — the fit hugs in all the right places without ever feeling restrictive. The colour is exactly as photographed and the fabric somehow feels luxurious without being heavy. Already on my second order.",
  "Quality far exceeds the price point. Stitching is impeccable, the colour hasn't faded after multiple washes, and packaging arrived beautifully boxed — felt like opening a real gift.",
  "Took a chance on a brand I'd never heard of and now I'm a convert. Customer service was incredibly responsive when I had a sizing question — they actually picked up the phone.",
  "Wore it for a long flight then straight to dinner — looked just as polished hours later. Throws on with everything in my closet.",
  "Beautiful piece for the price. The finish has a subtle glow rather than a harsh shine, which I love. Stays put even with daily wear.",
  "Comfortable, breathable, and the colour is more nuanced in person — it shifts subtly in different light. I'm reaching for it constantly.",
  "Absolutely worth it. The detail in the construction is what sets this brand apart — the inside is finished as carefully as the outside.",
  "Bought as a gift and the packaging itself was the kind of unboxing that makes you want to keep the box. The piece inside delivered too.",
];

const REVIEW_NAMES = [
  'Maya R.',
  'Sienna K.',
  'James P.',
  'Hannah L.',
  'Charlotte W.',
  'Olivia M.',
  'Benjamin T.',
  'Aisha S.',
  'Eleanor C.',
  'Sophia D.',
  'Lila V.',
  'Noah B.',
];

const REVIEW_LOCATIONS = [
  'London, UK',
  'New York, NY',
  'Los Angeles, CA',
  'Chicago, IL',
  'Toronto, ON',
  'Melbourne, AU',
  'Berlin, DE',
  'Paris, FR',
  'Amsterdam, NL',
  'Austin, TX',
];

const REVIEW_TIMESTAMPS = [
  '4 days ago',
  '8 days ago',
  '12 days ago',
  '3 weeks ago',
  '1 month ago',
  '6 weeks ago',
  '2 months ago',
];

type Review = {
  id: string;
  stars: number;
  body: string;
  name: string;
  location: string;
  timestamp: string;
  variant: string;
  verified: boolean;
};

function buildReviews(handle: string, count: number): Review[] {
  const reviews: Review[] = [];
  for (let i = 0; i < count; i++) {
    const seed = hashString(`${handle}-${i}`);
    const stars =
      (seed % 10) === 0 ? 3 : (seed % 7) === 0 ? 4 : 5;
    reviews.push({
      id: `r-${i}`,
      stars,
      body: REVIEW_BODIES[seed % REVIEW_BODIES.length],
      name: REVIEW_NAMES[seed % REVIEW_NAMES.length],
      location: REVIEW_LOCATIONS[(seed >> 3) % REVIEW_LOCATIONS.length],
      timestamp: REVIEW_TIMESTAMPS[(seed >> 5) % REVIEW_TIMESTAMPS.length],
      variant:
        ['Warm Gold', 'Polished Silver', 'Natural', 'Slate', 'Blush'][
          (seed >> 7) % 5
        ],
      verified: (seed % 5) !== 0,
    });
  }
  return reviews;
}

function StarRow({rating, size = 14}: {rating: number; size?: number}) {
  const fullStars = Math.floor(rating);
  const half = rating - fullStars >= 0.5 ? 1 : 0;
  const empty = 5 - fullStars - half;
  return (
    <span className="pdp-star-row" aria-label={`${rating} out of 5`}>
      {Array.from({length: fullStars}).map((_, i) => (
        <Star key={`f-${i}`} fill="currentColor" size={size} />
      ))}
      {half ? <Star key="h" fill="currentColor" half size={size} /> : null}
      {Array.from({length: empty}).map((_, i) => (
        <Star key={`e-${i}`} fill="none" size={size} />
      ))}
    </span>
  );
}

function Star({fill, half, size = 14}: {fill: string; half?: boolean; size?: number}) {
  if (half) {
    return (
      <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true">
        <defs>
          <linearGradient id="halfgrad">
            <stop offset="50%" stopColor="currentColor" />
            <stop offset="50%" stopColor="transparent" stopOpacity="1" />
          </linearGradient>
        </defs>
        <path
          d="M7 1l1.9 3.9 4.3.6-3.1 3 .7 4.3L7 10.7 3.2 12.8l.7-4.3-3.1-3 4.3-.6L7 1z"
          fill="url(#halfgrad)"
          stroke="currentColor"
          strokeWidth="0.6"
        />
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true">
      <path
        d="M7 1l1.9 3.9 4.3.6-3.1 3 .7 4.3L7 10.7 3.2 12.8l.7-4.3-3.1-3 4.3-.6L7 1z"
        fill={fill}
        stroke="currentColor"
        strokeWidth="0.6"
      />
    </svg>
  );
}

export function ProductReviews({
  productHandle,
  productTitle,
}: {
  productHandle: string;
  productTitle: string;
}) {
  const {stars, count} = formatRating(productHandle);
  const [showAll, setShowAll] = useState(false);
  const initialCount = 4;

  const reviewCount = Math.max(8, count);
  const totalToShow = showAll ? Math.min(8, reviewCount) : initialCount;
  const reviews = buildReviews(productHandle, totalToShow);

  const distribution = [
    {stars: 5, percent: 78},
    {stars: 4, percent: 16},
    {stars: 3, percent: 4},
    {stars: 2, percent: 1},
    {stars: 1, percent: 1},
  ];

  return (
    <section className="pdp-reviews" id="reviews" aria-labelledby="pdp-reviews-heading">
      <div className="pdp-reviews-header">
        <p className="pdp-reviews-eyebrow">Customer Voice</p>
        <h2 className="pdp-reviews-heading" id="pdp-reviews-heading">
          Loved by Our Customers
        </h2>
      </div>

      <div className="pdp-reviews-summary">
        <div className="pdp-reviews-score">
          <span className="pdp-reviews-score-num">{stars.toFixed(1)}</span>
          <StarRow rating={stars} size={20} />
          <span className="pdp-reviews-score-meta">
            Based on {reviewCount.toLocaleString()} verified reviews
          </span>
        </div>
        <div className="pdp-reviews-bars">
          {distribution.map((row) => (
            <div className="pdp-reviews-bar-row" key={row.stars}>
              <span className="pdp-reviews-bar-label">{row.stars}★</span>
              <span className="pdp-reviews-bar-track">
                <span
                  className="pdp-reviews-bar-fill"
                  style={{width: `${row.percent}%`}}
                />
              </span>
              <span className="pdp-reviews-bar-pct">{row.percent}%</span>
            </div>
          ))}
        </div>
        <button type="button" className="btn btn-primary pdp-reviews-write-btn">
          Write a Review
        </button>
      </div>

      <ul className="pdp-reviews-list">
        {reviews.map((r) => (
          <ReviewCard key={r.id} review={r} />
        ))}
      </ul>

      {!showAll && reviewCount > initialCount ? (
        <div className="pdp-reviews-more-row">
          <button
            type="button"
            className="btn btn-link"
            onClick={() => setShowAll(true)}
          >
            Read more reviews
          </button>
        </div>
      ) : null}

      <div className="pdp-reviews-share">
        <span>Share these reviews:</span>
        <ul>
          <li>
            <button type="button" aria-label="Share via email">@</button>
          </li>
          <li>
            <button type="button" aria-label="Share on Twitter">𝕏</button>
          </li>
          <li>
            <button type="button" aria-label="Share via link">↗</button>
          </li>
        </ul>
      </div>

      <form className="pdp-reviews-form" onSubmit={(e) => e.preventDefault()}>
        <h3 className="pdp-reviews-form-heading">Share your experience</h3>
        <p className="pdp-reviews-form-sub">
          Have you tried {productTitle}? Help others by leaving a review.
        </p>
        <div className="pdp-reviews-form-grid">
          <label className="pdp-reviews-field">
            <span>Display name</span>
            <input type="text" name="name" placeholder="e.g. Olivia M." />
          </label>
          <label className="pdp-reviews-field">
            <span>Email address</span>
            <input type="email" name="email" placeholder="contact@mock-shop.example" />
          </label>
          <label className="pdp-reviews-field pdp-reviews-field-stars">
            <span>Rating</span>
            <div className="pdp-reviews-form-stars">
              <StarRow rating={5} size={22} />
            </div>
          </label>
          <label className="pdp-reviews-field pdp-reviews-field-wide">
            <span>Your review</span>
            <textarea
              name="body"
              rows={4}
              placeholder="Tell us about fit, quality, and how you wear it"
            />
          </label>
        </div>
        <button type="submit" className="btn btn-primary">
          Submit Review
        </button>
      </form>
    </section>
  );
}

function ReviewCard({review}: {review: Review}) {
  const [expanded, setExpanded] = useState(false);
  const truncated = review.body.length > 220 && !expanded;
  const displayBody = truncated ? review.body.slice(0, 200) + '…' : review.body;

  return (
    <li className="pdp-review-card">
      <div className="pdp-review-head">
        <div className="pdp-review-meta">
          <StarRow rating={review.stars} size={14} />
          {review.verified ? (
            <span className="pdp-review-verified">
              <span className="pdp-review-verified-tick">✓</span> Verified
              Customer
            </span>
          ) : null}
        </div>
        <span className="pdp-review-time">{review.timestamp}</span>
      </div>
      <p className="pdp-review-body">
        {displayBody}{' '}
        {review.body.length > 220 ? (
          <button
            type="button"
            className="pdp-review-toggle"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
        ) : null}
      </p>
      <div className="pdp-review-foot">
        <span className="pdp-review-name">{review.name}</span>
        <span className="pdp-review-dot" aria-hidden="true">
          ·
        </span>
        <span className="pdp-review-location">{review.location}</span>
        <span className="pdp-review-dot" aria-hidden="true">
          ·
        </span>
        <span className="pdp-review-variant">Bought: {review.variant}</span>
      </div>
    </li>
  );
}
