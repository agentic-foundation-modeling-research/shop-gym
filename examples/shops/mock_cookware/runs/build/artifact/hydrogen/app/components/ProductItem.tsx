import {Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import type {CurrencyCode} from '@shopify/hydrogen/storefront-api-types';
import {ProductPlaceholder} from '~/components/ProductPlaceholder';
import {useVariantUrl} from '~/lib/variants';

type Money = {amount: string; currencyCode: CurrencyCode};

export type CollectionProduct = {
  id: string;
  handle: string;
  title: string;
  availableForSale?: boolean | null;
  createdAt?: string | null;
  tags?: string[] | null;
  featuredImage?: {
    id?: string | null;
    altText?: string | null;
    url: string;
    width?: number | null;
    height?: number | null;
  } | null;
  priceRange: {
    minVariantPrice: Money;
    maxVariantPrice?: Money;
  };
  compareAtPriceRange?: {
    minVariantPrice?: Money | null;
    maxVariantPrice?: Money | null;
  } | null;
  variants?: {
    nodes: Array<{
      id: string;
      title: string;
      availableForSale?: boolean | null;
      selectedOptions?: Array<{name: string; value: string}> | null;
    }>;
  } | null;
};

const COLOR_OPTION_NAMES = new Set([
  'color',
  'colour',
  'finish',
  'shade',
  'tone',
]);

function pickVariantOption(product: CollectionProduct): string | null {
  const variant = product.variants?.nodes?.[0];
  if (!variant?.selectedOptions?.length) return null;
  const colorish = variant.selectedOptions.find((o) =>
    COLOR_OPTION_NAMES.has(o.name.trim().toLowerCase()),
  );
  const chosen = colorish ?? variant.selectedOptions[0];
  if (!chosen.value || chosen.value.toLowerCase() === 'default title') {
    return null;
  }
  return chosen.value;
}

function computeSale(product: CollectionProduct): {
  onSale: boolean;
  percentOff: number;
  comparePrice?: Money;
} {
  const price = parseFloat(product.priceRange.minVariantPrice.amount);
  const compare = product.compareAtPriceRange?.minVariantPrice;
  const compareAmount = compare ? parseFloat(compare.amount) : 0;
  if (!compare || !compareAmount || compareAmount <= price) {
    return {onSale: false, percentOff: 0};
  }
  const percentOff = Math.round(((compareAmount - price) / compareAmount) * 100);
  return {onSale: true, percentOff, comparePrice: compare};
}

function deterministicHash(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = (hash << 5) - hash + input.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function mockRating(handle: string): {rating: number; count: number} {
  const h = deterministicHash(handle);
  const rating = 4.0 + ((h % 100) / 100); // 4.0 - 4.99
  const count = 12 + (h % 488); // 12 - 499
  return {rating: Math.round(rating * 10) / 10, count};
}

export function ProductItem({
  product,
  loading,
}: {
  product: CollectionProduct;
  loading?: 'eager' | 'lazy';
}) {
  const variantUrl = useVariantUrl(product.handle);
  const image = product.featuredImage;
  const variantName = pickVariantOption(product);
  const {onSale, percentOff, comparePrice} = computeSale(product);
  const isAvailable = product.availableForSale !== false;
  const {rating, count} = mockRating(product.handle);

  const tags = product.tags ?? [];
  const isNew =
    tags.some((t) => /new(-arrival)?$/i.test(t)) ||
    isRecentlyCreated(product.createdAt);
  const isBestseller = tags.some((t) =>
    /best[-_ ]?seller/i.test(t),
  );

  let badge: {label: string; tone: 'sale' | 'new' | 'best' | 'soon'} | null =
    null;
  if (!isAvailable) {
    badge = {label: 'Coming back soon', tone: 'soon'};
  } else if (onSale) {
    badge = {label: `Special — ${percentOff}% Off`, tone: 'sale'};
  } else if (isNew) {
    badge = {label: 'New', tone: 'new'};
  } else if (isBestseller) {
    badge = {label: 'Bestseller', tone: 'best'};
  }

  return (
    <div className="product-item" data-handle={product.handle}>
      <Link
        className="product-item-link"
        to={variantUrl}
        prefetch="intent"
        aria-label={product.title}
      >
        <div className="product-item-media">
          {image ? (
            <Image
              alt={image.altText || product.title}
              aspectRatio="4/5"
              data={image}
              loading={loading}
              sizes="(min-width: 900px) 33vw, (min-width: 600px) 50vw, 100vw"
            />
          ) : (
            <ProductPlaceholder className="product-item-placeholder" />
          )}
          {badge && (
            <span
              className={`product-item-badge product-item-badge-${badge.tone}`}
            >
              {badge.label}
            </span>
          )}
          <button
            type="button"
            className="product-item-quick-view"
            onClick={(event) => {
              event.preventDefault();
              window.location.href = variantUrl;
            }}
            aria-label={`Quick view ${product.title}`}
          >
            Quick View
          </button>
        </div>
        <div className="product-item-meta">
          <h3 className="product-item-title">
            {product.title}
            {variantName ? (
              <span className="product-item-variant"> — {variantName}</span>
            ) : null}
          </h3>
          <div className="product-item-rating" aria-label={`Rated ${rating} out of 5`}>
            <Stars value={rating} />
            <span className="product-item-rating-count">({count})</span>
          </div>
          <div className="product-item-price">
            {onSale && comparePrice ? (
              <>
                <span className="product-item-price-compare">
                  <Money data={comparePrice} />
                </span>
                <span className="product-item-price-sale">
                  <Money data={product.priceRange.minVariantPrice} />
                </span>
                <span className="product-item-price-off">
                  -{percentOff}%
                </span>
              </>
            ) : (
              <span className="product-item-price-regular">
                <Money data={product.priceRange.minVariantPrice} />
              </span>
            )}
          </div>
        </div>
      </Link>
    </div>
  );
}

function isRecentlyCreated(createdAt?: string | null): boolean {
  if (!createdAt) return false;
  const ts = Date.parse(createdAt);
  if (Number.isNaN(ts)) return false;
  const ageDays = (Date.now() - ts) / (1000 * 60 * 60 * 24);
  return ageDays < 60;
}

function Stars({value}: {value: number}) {
  const full = Math.floor(value);
  const half = value - full >= 0.5;
  const total = 5;
  return (
    <span className="product-item-stars" aria-hidden="true">
      {Array.from({length: total}).map((_, i) => {
        let cls = 'product-item-star';
        if (i < full) cls += ' product-item-star-full';
        else if (i === full && half) cls += ' product-item-star-half';
        return (
          <span key={i} className={cls}>
            ★
          </span>
        );
      })}
    </span>
  );
}
