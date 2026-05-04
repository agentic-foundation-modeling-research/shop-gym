import {useCallback, useRef} from 'react';
import {Link} from 'react-router';

type EditorialCard = {
  title: string;
  url: string;
  meta: string;
  accent: string;
  imageUrl: string;
  kind: 'recipe' | 'article';
};

const RECIPES: EditorialCard[] = [
  {
    title: 'Cast-Iron Sunday Roast Chicken',
    url: '/blogs/journal/cast-iron-sunday-roast-chicken',
    meta: 'Serves 4 · 1 hr 15 min',
    accent: '#c8531f',
    imageUrl: '/images/homepage-recipe-1.png',
    kind: 'recipe',
  },
  {
    title: 'One-Pan Lemon Garlic Salmon',
    url: '/blogs/journal/one-pan-lemon-garlic-salmon',
    meta: 'Serves 2 · 25 min',
    accent: '#a3b18a',
    imageUrl: '/images/homepage-recipe-2.png',
    kind: 'recipe',
  },
  {
    title: 'Slow-Braised Short Ribs',
    url: '/blogs/journal/slow-braised-short-ribs',
    meta: 'Serves 6 · 3 hr',
    accent: '#3b4f7c',
    imageUrl: '/images/homepage-recipe-3.png',
    kind: 'recipe',
  },
  {
    title: 'Weeknight Stir-Fried Beef and Broccoli',
    url: '/blogs/journal/weeknight-stir-fried-beef-and-broccoli',
    meta: 'Serves 4 · 30 min',
    accent: '#e3a857',
    imageUrl: '/images/homepage-recipe-4.png',
    kind: 'recipe',
  },
];

const ARTICLES: EditorialCard[] = [
  {
    title: 'How to season carbon steel like a pro',
    url: '/blogs/journal/how-to-season-carbon-steel-like-a-pro',
    meta: 'Care Guide · 6 min read',
    accent: '#1a1a1a',
    imageUrl: '/images/homepage-article-1.png',
    kind: 'article',
  },
  {
    title: 'Choosing the right chef’s knife size',
    url: '/blogs/journal/choosing-the-right-chefs-knife-size',
    meta: 'Buying Guide · 4 min read',
    accent: '#6b7c85',
    imageUrl: '/images/homepage-article-2.png',
    kind: 'article',
  },
  {
    title: 'Why we still build with tri-ply stainless',
    url: '/blogs/journal/why-we-still-build-with-tri-ply-stainless',
    meta: 'Behind the Build · 5 min read',
    accent: '#2c2c2c',
    imageUrl: '/images/homepage-article-3.png',
    kind: 'article',
  },
  {
    title: 'A kitchen built around a single pan',
    url: '/blogs/journal/a-kitchen-built-around-a-single-pan',
    meta: 'Customer Story · 7 min read',
    accent: '#6b7445',
    imageUrl: '/images/homepage-article-4.png',
    kind: 'article',
  },
];

export function RecipeCarousel() {
  return (
    <EditorialCarousel
      heading="Cook Along With Us"
      subtitle="Chef-tested recipes built around our pans"
      cards={RECIPES}
      cta={{label: 'See All Recipes', url: '/blogs/journal'}}
    />
  );
}

export function ArticleCarousel() {
  return (
    <EditorialCarousel
      heading="From the Journal"
      subtitle="Care guides, buying guides, and stories from our kitchen"
      cards={ARTICLES}
      cta={{label: 'Visit the Journal', url: '/blogs/journal'}}
    />
  );
}

function EditorialCarousel({
  heading,
  subtitle,
  cards,
  cta,
}: {
  heading: string;
  subtitle: string;
  cards: EditorialCard[];
  cta: {label: string; url: string};
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);

  const scroll = useCallback((direction: 'prev' | 'next') => {
    const track = trackRef.current;
    if (!track) return;
    const card = track.querySelector('[data-editorial-card]') as HTMLElement | null;
    const amount = card ? card.offsetWidth + 20 : track.clientWidth * 0.7;
    track.scrollBy({
      left: direction === 'next' ? amount : -amount,
      behavior: 'smooth',
    });
  }, []);

  return (
    <section className="editorial-carousel" aria-label={heading}>
      <div className="section-container">
        <div className="section-header">
          <div>
            <h2 className="section-title">{heading}</h2>
            <p className="section-subtitle">{subtitle}</p>
          </div>
          <div className="section-header-controls">
            <Link to={cta.url} prefetch="intent" className="section-link">
              {cta.label} →
            </Link>
            <div className="carousel-arrows">
              <button
                type="button"
                className="carousel-arrow"
                onClick={() => scroll('prev')}
                aria-label="Previous"
              >
                <Chevron direction="left" />
              </button>
              <button
                type="button"
                className="carousel-arrow"
                onClick={() => scroll('next')}
                aria-label="Next"
              >
                <Chevron direction="right" />
              </button>
            </div>
          </div>
        </div>
        <div className="editorial-track" ref={trackRef}>
          {cards.map((card) => (
            <Link
              key={card.title}
              to={card.url}
              prefetch="intent"
              className="editorial-card"
              data-editorial-card="true"
            >
              <div
                className="editorial-card-media"
                style={{background: card.accent}}
                aria-hidden="true"
              >
                <img
                  src={card.imageUrl}
                  alt=""
                  loading="lazy"
                  decoding="async"
                />
              </div>
              <div className="editorial-card-meta">
                <span className="editorial-card-kind">
                  {card.kind === 'recipe' ? 'Recipe' : 'Article'}
                </span>
                <h3 className="editorial-card-title">{card.title}</h3>
                <p className="editorial-card-detail">{card.meta}</p>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

function Chevron({direction}: {direction: 'left' | 'right'}) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {direction === 'left' ? (
        <path d="M15 6l-6 6 6 6" />
      ) : (
        <path d="M9 6l6 6-6 6" />
      )}
    </svg>
  );
}
