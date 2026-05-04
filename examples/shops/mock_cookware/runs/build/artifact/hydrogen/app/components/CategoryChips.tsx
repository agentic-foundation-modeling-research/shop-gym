import {useCallback, useRef} from 'react';
import {Link} from 'react-router';

type Chip = {label: string; url: string};

const CHIPS: Chip[] = [
  {label: 'New Arrivals', url: '/collections/new-arrivals'},
  {label: 'Best Sellers', url: '/collections/best-sellers'},
  {label: 'Cookware', url: '/collections/cookware'},
  {label: 'Frypans & Skillets', url: '/collections/frypans-skillets'},
  {label: 'Saucepans', url: '/collections/saucepans'},
  {label: 'Stockpots & Dutch Ovens', url: '/collections/stockpots-dutch-ovens'},
  {label: 'Sauté Pans & Woks', url: '/collections/saute-pans-woks'},
  {label: 'Griddles', url: '/collections/griddles'},
  {label: 'Cookware Sets', url: '/collections/cookware-sets'},
  {label: 'Knives', url: '/collections/knives'},
  {label: 'Bakeware', url: '/collections/bakeware'},
  {label: 'Cutting Boards & Prep', url: '/collections/cutting-boards-prep'},
  {label: 'Aprons & Oven Mitts', url: '/collections/aprons-oven-mitts'},
  {label: 'Sale', url: '/collections/sale'},
];

export function CategoryChips() {
  const trackRef = useRef<HTMLDivElement | null>(null);

  const scroll = useCallback((direction: 'prev' | 'next') => {
    const track = trackRef.current;
    if (!track) return;
    const amount = Math.max(track.clientWidth * 0.7, 240);
    track.scrollBy({
      left: direction === 'next' ? amount : -amount,
      behavior: 'smooth',
    });
  }, []);

  return (
    <section className="category-chips" aria-label="Shop by category">
      <div className="section-container">
        <div className="category-chips-header">
          <h2 className="section-eyebrow">Shop by Category</h2>
          <Link
            to="/collections/all"
            prefetch="intent"
            className="section-link"
          >
            Shop All →
          </Link>
        </div>
        <div className="category-chips-row">
          <button
            type="button"
            className="carousel-arrow carousel-arrow-prev"
            onClick={() => scroll('prev')}
            aria-label="Previous categories"
          >
            <Chevron direction="left" />
          </button>
          <div className="category-chips-track" ref={trackRef}>
            {CHIPS.map((chip) => (
              <Link
                key={chip.url + chip.label}
                to={chip.url}
                prefetch="intent"
                className="category-chip"
              >
                <span className="category-chip-icon" aria-hidden="true">
                  <svg viewBox="0 0 32 32" width="22" height="22" fill="none">
                    <circle
                      cx="16"
                      cy="16"
                      r="11"
                      stroke="currentColor"
                      strokeWidth="1.5"
                    />
                    <path
                      d="M5 16h6m10 0h6"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </span>
                <span className="category-chip-label">{chip.label}</span>
              </Link>
            ))}
          </div>
          <button
            type="button"
            className="carousel-arrow carousel-arrow-next"
            onClick={() => scroll('next')}
            aria-label="Next categories"
          >
            <Chevron direction="right" />
          </button>
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
