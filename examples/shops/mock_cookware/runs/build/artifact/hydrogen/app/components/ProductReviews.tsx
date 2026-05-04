import {useMemo, useState} from 'react';

const SORT_OPTIONS = [
  {value: 'most-helpful', label: 'Most helpful'},
  {value: 'latest', label: 'Latest'},
  {value: 'oldest', label: 'Oldest'},
  {value: 'highest', label: 'Highest rated'},
  {value: 'lowest', label: 'Lowest rated'},
] as const;

type SortValue = (typeof SORT_OPTIONS)[number]['value'];

type Review = {
  id: string;
  reviewer: string;
  location: string;
  rating: number;
  date: string;
  title: string;
  body: string;
  helpful: number;
  photo?: {url: string; alt: string};
};

type ReviewsSeed = {
  rating: number;
  count: number;
  distribution: number[];
  aiSummary: string;
  reviews: Review[];
};

export function ProductReviews({
  productHandle,
  productTitle,
}: {
  productHandle: string;
  productTitle: string;
}) {
  const seed = useMemo(
    () => seedReviews(productHandle, productTitle),
    [productHandle, productTitle],
  );

  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SortValue>('most-helpful');
  const [ratingFilter, setRatingFilter] = useState<number | null>(null);
  const [helpful, setHelpful] = useState<Record<string, boolean>>({});

  if (seed.count === 0) {
    return (
      <section className="pdp-reviews section-container" aria-label="Customer reviews">
        <h2 className="pdp-reviews-title">Reviews</h2>
        <div className="pdp-reviews-empty">
          <p>Be the first to leave a review.</p>
          <button type="button" className="pdp-reviews-write">
            Write a Review
          </button>
        </div>
      </section>
    );
  }

  const filtered = seed.reviews.filter((review) => {
    if (ratingFilter && Math.round(review.rating) !== ratingFilter) return false;
    if (query.trim().length === 0) return true;
    const q = query.trim().toLowerCase();
    return (
      review.title.toLowerCase().includes(q) ||
      review.body.toLowerCase().includes(q) ||
      review.reviewer.toLowerCase().includes(q)
    );
  });

  const sorted = sortReviews(filtered, sort);

  const toggleHelpful = (id: string) => {
    setHelpful((prev) => ({...prev, [id]: !prev[id]}));
  };

  return (
    <section className="pdp-reviews section-container" aria-label="Customer reviews">
      <header className="pdp-reviews-header">
        <h2 className="pdp-reviews-title">Customer Reviews</h2>
      </header>

      <div className="pdp-reviews-summary">
        <div className="pdp-reviews-aggregate">
          <div className="pdp-reviews-rating">{seed.rating.toFixed(1)}</div>
          <Stars value={seed.rating} size="lg" />
          <p className="pdp-reviews-aggregate-meta">
            Based on {seed.count.toLocaleString()} reviews
          </p>
        </div>
        <ul className="pdp-reviews-distribution" aria-label="Rating breakdown">
          {[5, 4, 3, 2, 1].map((star) => {
            const count = seed.distribution[star - 1] ?? 0;
            const pct = seed.count ? (count / seed.count) * 100 : 0;
            const isActive = ratingFilter === star;
            return (
              <li key={star}>
                <button
                  type="button"
                  className={`pdp-reviews-distribution-row${
                    isActive ? ' is-active' : ''
                  }`}
                  aria-pressed={isActive}
                  onClick={() =>
                    setRatingFilter((prev) => (prev === star ? null : star))
                  }
                >
                  <span className="pdp-reviews-distribution-label">
                    {star} ★
                  </span>
                  <span className="pdp-reviews-distribution-bar">
                    <span
                      className="pdp-reviews-distribution-fill"
                      style={{width: `${pct}%`}}
                    />
                  </span>
                  <span className="pdp-reviews-distribution-count">
                    {count}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <aside className="pdp-reviews-ai">
        <h3 className="pdp-reviews-ai-title">AI summary</h3>
        <p>{seed.aiSummary}</p>
      </aside>

      <div className="pdp-reviews-controls">
        <label className="pdp-reviews-search">
          <span className="visually-hidden">Search reviews</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search reviews"
          />
        </label>
        <label className="pdp-reviews-sort">
          <span>Sort by</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as SortValue)}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="pdp-reviews-sort">
          <span>Rating</span>
          <select
            value={ratingFilter ?? 'all'}
            onChange={(event) => {
              const value = event.target.value;
              setRatingFilter(value === 'all' ? null : Number(value));
            }}
          >
            <option value="all">All ratings</option>
            {[5, 4, 3, 2, 1].map((star) => (
              <option key={star} value={star}>
                {star} stars
              </option>
            ))}
          </select>
        </label>
      </div>

      {sorted.length === 0 ? (
        <p className="pdp-reviews-empty-results">
          No reviews match your search yet — try a different keyword.
        </p>
      ) : (
        <ul className="pdp-reviews-list">
          {sorted.slice(0, 6).map((review) => (
            <li key={review.id} className="pdp-review-card">
              <header className="pdp-review-header">
                <div>
                  <div className="pdp-review-name">{review.reviewer}</div>
                  <div className="pdp-review-meta">
                    {review.location} · {review.date}
                  </div>
                </div>
                <Stars value={review.rating} size="sm" />
              </header>
              <h4 className="pdp-review-title">{review.title}</h4>
              <p className="pdp-review-body">{review.body}</p>
              <footer className="pdp-review-footer">
                <button
                  type="button"
                  className={`pdp-review-helpful${
                    helpful[review.id] ? ' is-on' : ''
                  }`}
                  onClick={() => toggleHelpful(review.id)}
                >
                  Helpful ({review.helpful + (helpful[review.id] ? 1 : 0)})
                </button>
              </footer>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}


function Stars({value, size}: {value: number; size: 'sm' | 'lg'}) {
  const full = Math.floor(value);
  const half = value - full >= 0.5;
  return (
    <span
      className={`pdp-stars pdp-stars-${size}`}
      aria-label={`Rated ${value.toFixed(1)} out of 5`}
    >
      {Array.from({length: 5}).map((_, idx) => {
        let cls = 'pdp-star';
        if (idx < full) cls += ' is-full';
        else if (idx === full && half) cls += ' is-half';
        return (
          <span key={idx} className={cls} aria-hidden="true">
            ★
          </span>
        );
      })}
    </span>
  );
}

function sortReviews(reviews: Review[], sort: SortValue): Review[] {
  const list = reviews.slice();
  switch (sort) {
    case 'latest':
      return list.sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
    case 'oldest':
      return list.sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
    case 'highest':
      return list.sort((a, b) => b.rating - a.rating);
    case 'lowest':
      return list.sort((a, b) => a.rating - b.rating);
    case 'most-helpful':
    default:
      return list.sort((a, b) => b.helpful - a.helpful);
  }
}

const REVIEWERS = [
  {name: 'Renee K.', location: 'Portland, OR'},
  {name: 'Marcus W.', location: 'Atlanta, GA'},
  {name: 'Priya S.', location: 'Brooklyn, NY'},
  {name: 'David L.', location: 'San Diego, CA'},
  {name: 'Hannah B.', location: 'Madison, WI'},
  {name: 'Tomás R.', location: 'Austin, TX'},
  {name: 'Aiko M.', location: 'Seattle, WA'},
  {name: 'Elena V.', location: 'Denver, CO'},
];

const TITLES = [
  'Heats evenly, cleans up in seconds',
  'Worth every dollar',
  'Replaced three pans I never use anymore',
  'My new everyday pan',
  'Sturdier than I expected',
  'Beautiful in person',
  'A workhorse for weeknight dinners',
  'My partner loves it more than I do',
];

const BODIES = [
  'Tested it on eggs, seared salmon, and a quick stir-fry. Nothing stuck. Cleanup is just a rinse and a wipe.',
  'The handle stays cool through long simmers and the weight feels balanced. I appreciate that it’s oven-safe at high temps.',
  'Looks classic on the stovetop and goes straight from the burner to the table without looking out of place.',
  'I’ve used it daily for a few months now and there’s no warping or staining. The coating still beads water like new.',
  'Heavy enough to feel premium without being unwieldy. Pairs well with our induction range and heats fast.',
  'Customer service was responsive when I had a packaging question, and shipping was quick. Will be ordering again.',
];

function seedReviews(handle: string, title: string): ReviewsSeed {
  const hash = hashString(handle);
  const baseRating = 4.2 + (hash % 70) / 100;
  const rating = Math.round(baseRating * 10) / 10;
  const count = 36 + (hash % 740);
  const distribution = distribute(count, hash);
  const reviewCount = Math.min(8, 4 + (hash % 5));

  const reviews: Review[] = Array.from({length: reviewCount}).map((_, idx) => {
    const local = (hash + idx * 17) | 0;
    const reviewer = REVIEWERS[Math.abs(local) % REVIEWERS.length];
    const stars = clamp(
      Math.round(rating + (local % 5 === 0 ? -1 : local % 7 === 0 ? 0 : 0)),
      3,
      5,
    );
    const date = makeDate(local);
    return {
      id: `${handle}-${idx}`,
      reviewer: reviewer.name,
      location: reviewer.location,
      rating: stars,
      date,
      title: TITLES[Math.abs(local) % TITLES.length],
      body: BODIES[Math.abs(local) % BODIES.length],
      helpful: 4 + (Math.abs(local) % 90),
    };
  });

  const aiSummary = `Customers describe the ${title.toLowerCase()} as evenly heating, easy to clean, and notably durable. Recurring praise highlights the balanced weight and oven-safe versatility, while a small number of reviewers mention a learning curve adjusting heat for quick searing.`;

  return {
    rating,
    count,
    distribution,
    aiSummary,
    reviews,
  };
}

function distribute(total: number, seed: number): number[] {
  const weights = [0.04, 0.05, 0.07, 0.18, 0.66];
  const drift = ((seed >> 3) % 6) / 100;
  const adjusted = [
    weights[0] + drift,
    weights[1] - drift / 2,
    weights[2] + drift / 4,
    weights[3] - drift / 4,
    weights[4] - drift / 2,
  ];
  const sum = adjusted.reduce((a, b) => a + b, 0);
  let allocated = 0;
  const result: number[] = [];
  for (let i = 0; i < 5; i++) {
    const portion = i === 4 ? total - allocated : Math.round(total * (adjusted[i] / sum));
    result.push(Math.max(0, portion));
    allocated += portion;
  }
  return result;
}

function makeDate(seed: number): string {
  const days = Math.abs(seed) % 600;
  const date = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function hashString(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = (hash << 5) - hash + input.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}
