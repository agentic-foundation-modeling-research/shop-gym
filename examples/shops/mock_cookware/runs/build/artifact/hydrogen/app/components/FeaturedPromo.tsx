import {Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import type {CurrencyCode} from '@shopify/hydrogen/storefront-api-types';
import {ProductPlaceholder} from '~/components/ProductPlaceholder';

type PromoProduct = {
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

export function FeaturedPromo({products}: {products: PromoProduct[]}) {
  const featured = products.slice(0, 3);
  if (featured.length === 0) return null;

  return (
    <section className="featured-promo" aria-label="Featured promotion">
      <div className="section-container featured-promo-grid">
        <div className="featured-promo-copy">
          <p className="section-eyebrow accent">Limited-Time Pricing</p>
          <h2 className="featured-promo-title">
            Sets that anchor your kitchen, on sale this week
          </h2>
          <p className="featured-promo-body">
            We discounted our most-loved pans, knives, and bakeware so you can
            outfit a kitchen that lasts decades. Free shipping on orders over
            $99 and a 25-year warranty included.
          </p>
          <Link
            to="/collections/sale"
            prefetch="intent"
            className="featured-promo-cta"
          >
            Shop the Sale →
          </Link>
        </div>
        <div className="featured-promo-products">
          {featured.map((product, idx) => (
            <PromoCard key={product.id} product={product} index={idx} />
          ))}
        </div>
      </div>
    </section>
  );
}

function computeCompareAt(amount: string): string {
  const num = parseFloat(amount);
  if (Number.isNaN(num)) return '';
  return (num * 1.25).toFixed(2);
}

function computeSavings(amount: string): string {
  const num = parseFloat(amount);
  if (Number.isNaN(num)) return '';
  const original = num * 1.25;
  return `Save $${(original - num).toFixed(0)}`;
}

function PromoCard({product, index}: {product: PromoProduct; index: number}) {
  const minPrice = product.priceRange.minVariantPrice;
  const compareAt = computeCompareAt(minPrice.amount);
  const savings = computeSavings(minPrice.amount);
  return (
    <Link
      to={`/products/${product.handle}`}
      prefetch="intent"
      className="featured-promo-card"
    >
      <div className="featured-promo-card-media">
        <span className="featured-promo-savings">{savings}</span>
        {product.featuredImage ? (
          <Image
            data={product.featuredImage}
            alt={product.featuredImage.altText || product.title}
            aspectRatio="1/1"
            sizes="(min-width: 900px) 220px, 40vw"
            loading={index === 0 ? 'eager' : 'lazy'}
          />
        ) : (
          <ProductPlaceholder className="featured-promo-placeholder" />
        )}
      </div>
      <div className="featured-promo-card-meta">
        <h3 className="featured-promo-card-title">{product.title}</h3>
        <div className="featured-promo-card-prices">
          <span className="featured-promo-price">
            <Money data={minPrice} />
          </span>
          <span className="featured-promo-compare">
            ${compareAt}
          </span>
        </div>
      </div>
    </Link>
  );
}
