import {useCallback, useRef} from 'react';
import {Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import type {CurrencyCode} from '@shopify/hydrogen/storefront-api-types';
import {ProductPlaceholder} from '~/components/ProductPlaceholder';

type CarouselProduct = {
  id: string;
  title: string;
  handle: string;
  featuredImage?: {
    id?: string | null;
    url: string;
    altText?: string | null;
    width?: number | null;
    height?: number | null;
  } | null;
  priceRange: {
    minVariantPrice: {amount: string; currencyCode: CurrencyCode};
  };
};

type ProductCarouselProps = {
  title: string;
  subtitle?: string;
  cta?: {label: string; url: string};
  products: CarouselProduct[];
};

export function ProductCarousel({
  title,
  subtitle,
  cta,
  products,
}: ProductCarouselProps) {
  const trackRef = useRef<HTMLDivElement | null>(null);

  const scroll = useCallback((direction: 'prev' | 'next') => {
    const track = trackRef.current;
    if (!track) return;
    const card = track.querySelector('[data-carousel-card]') as HTMLElement | null;
    const amount = card ? card.offsetWidth + 20 : track.clientWidth * 0.7;
    track.scrollBy({
      left: direction === 'next' ? amount : -amount,
      behavior: 'smooth',
    });
  }, []);

  if (!products.length) return null;

  return (
    <section className="product-carousel" aria-label={title}>
      <div className="section-container">
        <div className="section-header">
          <div>
            <h2 className="section-title">{title}</h2>
            {subtitle && <p className="section-subtitle">{subtitle}</p>}
          </div>
          <div className="section-header-controls">
            {cta && (
              <Link
                to={cta.url}
                prefetch="intent"
                className="section-link"
              >
                {cta.label} →
              </Link>
            )}
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
        <div className="product-carousel-track" ref={trackRef}>
          {products.map((product) => (
            <CarouselCard key={product.id} product={product} />
          ))}
        </div>
      </div>
    </section>
  );
}

function CarouselCard({product}: {product: CarouselProduct}) {
  return (
    <Link
      to={`/products/${product.handle}`}
      prefetch="intent"
      className="carousel-card"
      data-carousel-card="true"
    >
      <div className="carousel-card-media">
        {product.featuredImage ? (
          <Image
            data={product.featuredImage}
            alt={product.featuredImage.altText || product.title}
            aspectRatio="4/5"
            sizes="(min-width: 900px) 280px, 60vw"
          />
        ) : (
          <ProductPlaceholder className="carousel-card-placeholder" />
        )}
      </div>
      <div className="carousel-card-meta">
        <h3 className="carousel-card-title">{product.title}</h3>
        <div className="carousel-card-price">
          <Money data={product.priceRange.minVariantPrice} />
        </div>
      </div>
    </Link>
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
