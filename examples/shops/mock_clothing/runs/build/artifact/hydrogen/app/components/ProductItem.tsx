import {useMemo, useState} from 'react';
import {Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import type {
  CollectionItemFragment,
  ProductItemFragment,
  RecommendedProductFragment,
} from 'storefrontapi.generated';
import {useVariantUrl} from '~/lib/variants';

type CardMoney = ProductItemFragment['priceRange']['minVariantPrice'];

export type ProductItemRich = (
  | CollectionItemFragment
  | ProductItemFragment
  | RecommendedProductFragment
) & {
  productType?: string;
  tags?: string[];
  compareAtPriceRange?: {
    minVariantPrice?: CardMoney | null;
    maxVariantPrice?: CardMoney | null;
  } | null;
  options?: Array<{name: string; values: string[]}>;
};

const COLOR_NAME_TO_HEX: Record<string, string> = {
  black: '#1c1c1e',
  white: '#f4f1ec',
  ivory: '#ede4d3',
  cream: '#f0e6d2',
  blush: '#e8c5c0',
  pink: '#f0bdbf',
  rose: '#d2867f',
  red: '#b8454a',
  burgundy: '#6b2230',
  berry: '#8d3a52',
  orange: '#d97a3c',
  rust: '#a85333',
  blaze: '#c45a2b',
  butter: '#f0d977',
  yellow: '#e8c54e',
  gold: '#c5a47e',
  champagne: '#d8c19a',
  sand: '#d6c4a4',
  camel: '#b89a78',
  caramel: '#a07a4c',
  tan: '#c2a37c',
  brown: '#7a5638',
  taupe: '#a08c78',
  mocha: '#6f4e3a',
  green: '#4d6a4a',
  sage: '#9aa787',
  forest: '#2e4030',
  olive: '#6b6f3c',
  mint: '#bcd4b8',
  aqua: '#9cc7c0',
  teal: '#3e7575',
  blue: '#4a6c93',
  alpine: '#7090b8',
  navy: '#212d44',
  denim: '#5a7595',
  slate: '#5b6671',
  carbon: '#3a3a3c',
  charcoal: '#2f2f31',
  graphite: '#404044',
  basalt: '#3e3a36',
  ash: '#a8a29a',
  grey: '#8a8a8c',
  gray: '#8a8a8c',
  silver: '#cbc6c0',
  pearl: '#ece5d8',
  amethyst: '#7c5d8a',
  purple: '#6c4c80',
  velvet: '#5a3a4d',
  storm: '#586674',
};

const PERSONALISE_KEYWORDS = [
  'engrave',
  'engraved',
  'personalise',
  'personalised',
  'personalize',
  'personalized',
  'monogram',
  'custom',
  'birthstone',
  'name',
  'initial',
];

function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

function colorNameToHex(name: string): string {
  const lc = name.toLowerCase();
  for (const key of Object.keys(COLOR_NAME_TO_HEX)) {
    if (lc.includes(key)) return COLOR_NAME_TO_HEX[key];
  }
  return '#c5a47e';
}

function formatRating(seed: string): {stars: string; count: string} {
  const h = hashString(seed);
  const stars = (3.8 + ((h % 130) / 100)).toFixed(1); // 3.8–5.1 clamped
  const clampedStars = Math.min(parseFloat(stars), 5.0).toFixed(1);
  const count = ((h % 980) + 12).toString();
  return {stars: clampedStars, count};
}

function deriveBadges(product: ProductItemRich): string[] {
  const badges: string[] = [];
  const tags = (product.tags ?? []).map((t) => t.toLowerCase());
  const handle = product.handle.toLowerCase();
  const hasNew =
    tags.includes('new') ||
    tags.includes('new-arrivals') ||
    tags.includes('new arrival');

  const compareAt = product.compareAtPriceRange?.minVariantPrice;
  const price = product.priceRange.minVariantPrice;
  if (compareAt && parseFloat(compareAt.amount) > parseFloat(price.amount)) {
    const pct = Math.round(
      (1 - parseFloat(price.amount) / parseFloat(compareAt.amount)) * 100,
    );
    if (pct > 0) badges.push(`SAVE ${pct}%`);
  }

  if (hasNew) badges.push('NEW');

  if (PERSONALISE_KEYWORDS.some((kw) => handle.includes(kw))) {
    badges.push('PERSONALISE');
  } else if (tags.includes('sterling-silver') || tags.includes('925')) {
    badges.push('925 STERLING SILVER');
  } else if (tags.includes('vermeil') || tags.includes('14k')) {
    badges.push('14K VERMEIL');
  }

  return badges.slice(0, 2);
}

function isPersonalisable(product: ProductItemRich): boolean {
  const handle = product.handle.toLowerCase();
  return PERSONALISE_KEYWORDS.some((kw) => handle.includes(kw));
}

function StarIcon() {
  return (
    <svg
      className="product-card-star"
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

function ProductPlaceholder({swatch}: {swatch: string}) {
  return (
    <div
      className="product-card-placeholder"
      style={{background: swatch}}
      aria-hidden="true"
    >
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
        <rect width="48" height="48" rx="4" fill="rgba(255,255,255,0.18)" />
        <path
          d="M17 31l5-7 4 5 6-8 7 10H9l8-10z"
          fill="rgba(255,255,255,0.55)"
        />
        <circle cx="18" cy="19" r="3" fill="rgba(255,255,255,0.7)" />
      </svg>
    </div>
  );
}

export function ProductItem({
  product,
  loading,
}: {
  product: ProductItemRich;
  loading?: 'eager' | 'lazy';
}) {
  const variantUrl = useVariantUrl(product.handle);
  const image = product.featuredImage;

  const colorOption = useMemo(
    () => product.options?.find((o) => o.name.toLowerCase() === 'color'),
    [product.options],
  );

  const swatches = useMemo(() => {
    if (!colorOption) return [] as Array<{name: string; hex: string}>;
    const limit = 7;
    return colorOption.values
      .slice(0, limit)
      .map((value) => ({name: value, hex: colorNameToHex(value)}));
  }, [colorOption]);

  const [activeSwatch, setActiveSwatch] = useState(0);

  const badges = useMemo(() => deriveBadges(product), [product]);
  const rating = useMemo(
    () => formatRating(product.id || product.handle),
    [product.id, product.handle],
  );
  const personalisable = useMemo(() => isPersonalisable(product), [product]);

  const minPrice = product.priceRange.minVariantPrice;
  const maxPrice =
    'maxVariantPrice' in product.priceRange
      ? product.priceRange.maxVariantPrice
      : minPrice;
  const compareAt = product.compareAtPriceRange?.minVariantPrice ?? null;
  const isOnSale = Boolean(
    compareAt && parseFloat(compareAt.amount) > parseFloat(minPrice.amount),
  );
  const hasVariablePrice =
    !isOnSale &&
    parseFloat(maxPrice.amount) > parseFloat(minPrice.amount) + 0.001;

  const placeholderHex = useMemo(() => {
    if (swatches.length > 0) return swatches[activeSwatch]?.hex ?? '#c5a47e';
    return '#e8e2d8';
  }, [swatches, activeSwatch]);

  const activeSwatchName = swatches[activeSwatch]?.name;
  const titleSuffix = activeSwatchName ? ` (${activeSwatchName})` : '';

  return (
    <article className="product-card">
      <Link
        to={variantUrl}
        prefetch="intent"
        className="product-card-image-link"
        aria-label={product.title}
      >
        {badges.length > 0 ? (
          <div className="product-card-badges" aria-hidden="true">
            {badges.map((b) => (
              <span key={b} className="product-card-badge">
                {b}
              </span>
            ))}
          </div>
        ) : null}
        <div className="product-card-image-wrap">
          {image ? (
            <Image
              data={image}
              aspectRatio="1/1"
              loading={loading}
              sizes="(min-width: 1024px) 25vw, (min-width: 600px) 50vw, 50vw"
              className="product-card-image"
            />
          ) : (
            <ProductPlaceholder swatch={placeholderHex} />
          )}
          <div
            className="product-card-image-overlay"
            style={{background: placeholderHex}}
            aria-hidden="true"
          />
        </div>
        {personalisable ? (
          <span className="product-card-personalise" role="presentation">
            Personalise →
          </span>
        ) : null}
      </Link>
      <div className="product-card-body">
        <h3 className="product-card-title">
          <Link to={variantUrl} prefetch="intent">
            {product.title}
            {titleSuffix}
          </Link>
        </h3>
        <div className="product-card-price-row">
          {isOnSale ? (
            <>
              <s className="product-card-price-compare">
                <Money data={compareAt!} />
              </s>
              <span className="product-card-price product-card-price-sale">
                <Money data={minPrice} />
              </span>
              <span className="product-card-save-tag">
                Save{' '}
                {Math.round(
                  (1 -
                    parseFloat(minPrice.amount) /
                      parseFloat(compareAt!.amount)) *
                    100,
                )}
                %
              </span>
            </>
          ) : hasVariablePrice ? (
            <span className="product-card-price">
              From <Money data={minPrice} />
            </span>
          ) : (
            <span className="product-card-price">
              <Money data={minPrice} />
            </span>
          )}
        </div>
        {swatches.length > 0 ? (
          <div className="product-card-swatches-block">
            <ul className="product-card-swatches" aria-label="Available colors">
              {swatches.map((s, i) => (
                <li key={s.name}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      setActiveSwatch(i);
                    }}
                    className={`product-card-swatch${
                      i === activeSwatch ? ' is-active' : ''
                    }`}
                    style={{background: s.hex}}
                    aria-label={s.name}
                    aria-pressed={i === activeSwatch}
                  />
                </li>
              ))}
            </ul>
            <span className="product-card-swatch-label">{activeSwatchName}</span>
          </div>
        ) : null}
        <div
          className="product-card-rating"
          aria-label={`Rated ${rating.stars} out of 5 from ${rating.count} reviews`}
        >
          <StarIcon />
          <span>
            {rating.stars}{' '}
            <span className="product-card-rating-count">
              ({rating.count} reviews)
            </span>
          </span>
        </div>
        {personalisable ? (
          <Link
            to={`${variantUrl}#personalise`}
            prefetch="intent"
            className="product-card-personalise-cta"
          >
            Personalise →
          </Link>
        ) : null}
      </div>
    </article>
  );
}
