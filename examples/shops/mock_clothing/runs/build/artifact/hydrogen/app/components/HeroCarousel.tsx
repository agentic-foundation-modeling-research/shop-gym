import {useEffect, useRef, useState} from 'react';
import {Link} from 'react-router';

interface HeroSlide {
  eyebrow: string;
  headline: string;
  subline: string;
  ctaLabel: string;
  ctaUrl: string;
  imageUrl: string;
  imageAlt: string;
}

const SLIDES: HeroSlide[] = [
  {
    eyebrow: 'The Spring Edit',
    headline: 'Layered for the way\nyou actually live.',
    subline:
      'Buttery leggings, soft tailoring, and studio-to-street essentials — crafted to wear together, designed to last beyond the season.',
    ctaLabel: 'Shop New Arrivals',
    ctaUrl: '/collections/fresh-drops',
    imageUrl: '/images/hero-the-spring-edit.png',
    imageAlt: 'Model in soft tailored loungewear and leggings in a sunlit studio',
  },
  {
    eyebrow: 'The Lounge Capsule',
    headline: 'Slow mornings\nstart soft.',
    subline:
      'Cloud-soft knits and matching sets in tonal neutrals — built to be packed, layered, and lived in.',
    ctaLabel: 'Shop Loungewear',
    ctaUrl: '/collections/lounge-collection',
    imageUrl: '/images/hero-the-lounge-capsule.png',
    imageAlt: 'Coordinated cream and camel knit lounge sets in a warm interior',
  },
  {
    eyebrow: 'Bestsellers, Restocked',
    headline: 'The pieces our\ncommunity wears on repeat.',
    subline:
      'Top-rated favourites — back in your size and your favourite color. Free shipping over $75.',
    ctaLabel: 'Shop Best Sellers',
    ctaUrl: '/collections/fan-favorites',
    imageUrl: '/images/hero-bestsellers-restocked.png',
    imageAlt: 'Flat lay of bestselling activewear pieces in espresso and oat tones',
  },
];

const ROTATION_MS = 6000;

export function HeroCarousel() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (paused) return;
    timerRef.current = window.setInterval(() => {
      setActive((current) => (current + 1) % SLIDES.length);
    }, ROTATION_MS);
    return () => {
      if (timerRef.current !== null) window.clearInterval(timerRef.current);
    };
  }, [paused]);

  const goTo = (idx: number) => {
    setActive(((idx % SLIDES.length) + SLIDES.length) % SLIDES.length);
  };

  const goPrev = () => goTo(active - 1);
  const goNext = () => goTo(active + 1);

  return (
    <section
      className="hero-carousel"
      aria-label="Featured campaigns"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="hero-carousel-stage">
        {SLIDES.map((slide, idx) => (
          <div
            key={slide.headline}
            className={`hero-carousel-slide${idx === active ? ' is-active' : ''}`}
            aria-hidden={idx !== active}
          >
            <div className="hero-carousel-image">
              <img
                src={slide.imageUrl}
                alt={slide.imageAlt}
                loading={idx === 0 ? 'eager' : 'lazy'}
                decoding="async"
              />
            </div>
            <div className="hero-carousel-overlay">
              <div className="hero-carousel-content">
                <span className="hero-carousel-eyebrow">{slide.eyebrow}</span>
                <h1 className="hero-carousel-headline">
                  {slide.headline.split('\n').map((line, i) => (
                    <span key={i} className="hero-carousel-headline-line">
                      {line}
                    </span>
                  ))}
                </h1>
                <p className="hero-carousel-sub">{slide.subline}</p>
                <Link
                  to={slide.ctaUrl}
                  prefetch="intent"
                  className="btn btn-primary hero-carousel-cta"
                  tabIndex={idx === active ? 0 : -1}
                >
                  {slide.ctaLabel}
                </Link>
              </div>
            </div>
          </div>
        ))}
      </div>

      <button
        type="button"
        className="hero-carousel-arrow hero-carousel-arrow-prev"
        onClick={goPrev}
        aria-label="Previous slide"
      >
        ‹
      </button>
      <button
        type="button"
        className="hero-carousel-arrow hero-carousel-arrow-next"
        onClick={goNext}
        aria-label="Next slide"
      >
        ›
      </button>

      <div className="hero-carousel-dots" role="tablist" aria-label="Slide selection">
        {SLIDES.map((slide, idx) => (
          <button
            key={slide.headline}
            type="button"
            role="tab"
            aria-selected={idx === active}
            aria-label={`Go to slide ${idx + 1}`}
            className={`hero-carousel-dot${idx === active ? ' is-active' : ''}`}
            onClick={() => goTo(idx)}
          />
        ))}
      </div>
    </section>
  );
}

