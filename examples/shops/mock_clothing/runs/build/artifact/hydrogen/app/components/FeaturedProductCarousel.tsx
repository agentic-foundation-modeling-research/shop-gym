import {useState, Suspense} from 'react';
import {Await, Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import type {RecommendedProductsQuery} from 'storefrontapi.generated';

const SWATCHES = ['#c5a47e', '#2a201c', '#fbf8f3', '#8a7e75', '#5a7a5a'];

interface FeaturedProductCarouselProps {
  products: Promise<RecommendedProductsQuery | null>;
  eyebrow: string;
  heading: string;
  subline?: string;
  viewAllLabel: string;
  viewAllUrl: string;
}

export function FeaturedProductCarousel({
  products,
  eyebrow,
  heading,
  subline,
  viewAllLabel,
  viewAllUrl,
}: FeaturedProductCarouselProps) {
  return (
    <section className="featured-products-section">
      <div className="featured-products-header">
        <div className="featured-products-heading-text">
          <span className="section-eyebrow">{eyebrow}</span>
          <h2 className="section-heading">{heading}</h2>
          {subline ? <p className="section-subline">{subline}</p> : null}
        </div>
        <Link
          to={viewAllUrl}
          prefetch="intent"
          className="section-view-all"
        >
          {viewAllLabel} →
        </Link>
      </div>
      <Suspense fallback={<FeaturedProductsSkeleton />}>
        <Await resolve={products}>
          {(response) => (
            <div className="featured-products-track">
              {response?.products.nodes.map((product) => (
                <FeaturedProductCard
                  key={product.id}
                  product={product}
                />
              )) ?? null}
            </div>
          )}
        </Await>
      </Suspense>
    </section>
  );
}

type FeaturedProduct = NonNullable<
  RecommendedProductsQuery
>['products']['nodes'][number];

function FeaturedProductCard({product}: {product: FeaturedProduct}) {
  const [activeSwatch, setActiveSwatch] = useState(0);
  const image = product.featuredImage;
  return (
    <article className="featured-product-card">
      <Link
        to={`/products/${product.handle}`}
        prefetch="intent"
        className="featured-product-card-image-link"
        aria-label={product.title}
      >
        {image ? (
          <Image
            data={image}
            aspectRatio="3/4"
            sizes="(min-width: 1024px) 25vw, 80vw"
            className="featured-product-card-image"
          />
        ) : (
          <ProductPlaceholder swatch={SWATCHES[activeSwatch] ?? '#c5a47e'} />
        )}
        <span className="featured-product-card-badge">Bestseller</span>
      </Link>
      <div className="featured-product-card-body">
        <h3 className="featured-product-card-title">
          <Link to={`/products/${product.handle}`} prefetch="intent">
            {product.title}
          </Link>
        </h3>
        <div className="featured-product-card-meta">
          <span className="featured-product-card-price">
            <Money data={product.priceRange.minVariantPrice} />
          </span>
          <span className="featured-product-card-rating" aria-label="Rated 4.8 out of 5">
            <StarIcon />
            <span>4.8 · 1.2k</span>
          </span>
        </div>
        <ul className="featured-product-card-swatches" aria-label="Available finishes">
          {SWATCHES.map((color, index) => (
            <li key={color}>
              <button
                type="button"
                className={`featured-product-card-swatch${
                  activeSwatch === index ? ' is-active' : ''
                }`}
                style={{background: color}}
                onClick={() => setActiveSwatch(index)}
                aria-label={`Swatch ${index + 1}`}
                aria-pressed={activeSwatch === index}
              />
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

function FeaturedProductsSkeleton() {
  return (
    <div className="featured-products-track">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="featured-product-card is-loading">
          <div className="featured-product-card-image-link">
            <ProductPlaceholder swatch="#e8e2d8" />
          </div>
          <div className="featured-product-card-body">
            <div className="skeleton-line skeleton-line-title" />
            <div className="skeleton-line skeleton-line-price" />
          </div>
        </div>
      ))}
    </div>
  );
}

function ProductPlaceholder({swatch}: {swatch: string}) {
  return (
    <div
      className="featured-product-placeholder"
      style={{background: swatch}}
      aria-hidden="true"
    >
      <svg width="64" height="64" viewBox="0 0 48 48" fill="none">
        <rect width="48" height="48" rx="6" fill="rgba(255,255,255,0.18)" />
        <path
          d="M9 34l8-10 5 6 6-8 11 14H7l2-2z"
          fill="rgba(255,255,255,0.5)"
        />
        <circle cx="18" cy="18" r="3.5" fill="rgba(255,255,255,0.65)" />
      </svg>
    </div>
  );
}

function StarIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 14 14"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M7 1l1.9 3.9 4.3.6-3.1 3 .7 4.3L7 10.7 3.2 12.8l.7-4.3-3.1-3 4.3-.6L7 1z" />
    </svg>
  );
}
