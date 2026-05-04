import {useRef} from 'react';
import {Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import type {RecommendedProductFragment} from 'storefrontapi.generated';
import {colorNameToHex, hashString, formatRating} from '~/lib/productColors';

type ShopTheLookProduct = RecommendedProductFragment & {
  vendor?: string | null;
};

const PALETTES = [
  'linear-gradient(135deg, #efe6d6 0%, #c5a47e 100%)',
  'linear-gradient(160deg, #d8c19a 0%, #6e553f 100%)',
  'linear-gradient(150deg, #f0e6d2 0%, #d8c19a 60%, #b89a78 100%)',
  'linear-gradient(180deg, #e8e2d8 0%, #b8a888 100%)',
];

export function ShopTheLook({
  products,
  currentHandle,
}: {
  products: ShopTheLookProduct[] | null | undefined;
  currentHandle: string;
}) {
  const trackRef = useRef<HTMLDivElement | null>(null);

  const list = (products || [])
    .filter((p) => p.handle !== currentHandle)
    .slice(0, 4);

  if (list.length === 0) return null;

  const scrollBy = (dir: 1 | -1) => {
    if (!trackRef.current) return;
    const width = trackRef.current.clientWidth;
    trackRef.current.scrollBy({left: dir * width * 0.7, behavior: 'smooth'});
  };

  return (
    <section className="pdp-shop-look" aria-labelledby="pdp-shop-look-heading">
      <div className="pdp-section-head">
        <p className="pdp-section-eyebrow">Curated by Stylists</p>
        <h2 className="pdp-section-heading" id="pdp-shop-look-heading">
          Shop the Look
        </h2>
        <p className="pdp-section-sub">
          Pieces our stylists pair with this — selected for fabric, finish, and
          intent.
        </p>
        <div className="pdp-shop-look-controls">
          <button
            type="button"
            className="pdp-arrow-btn"
            onClick={() => scrollBy(-1)}
            aria-label="Scroll left"
          >
            ‹
          </button>
          <button
            type="button"
            className="pdp-arrow-btn"
            onClick={() => scrollBy(1)}
            aria-label="Scroll right"
          >
            ›
          </button>
        </div>
      </div>
      <div className="pdp-shop-look-track" ref={trackRef}>
        {list.map((product, idx) => (
          <ShopTheLookCard
            key={product.id}
            product={product}
            paletteIdx={idx % PALETTES.length}
          />
        ))}
      </div>
    </section>
  );
}

function ShopTheLookCard({
  product,
  paletteIdx,
}: {
  product: ShopTheLookProduct;
  paletteIdx: number;
}) {
  const {stars, count} = formatRating(product.handle);
  const fallbackHex = colorNameToHex(product.title);
  const variantSeed = hashString(product.handle) % 4;
  return (
    <Link
      to={`/products/${product.handle}`}
      prefetch="intent"
      className="pdp-shop-look-card"
    >
      <div
        className="pdp-shop-look-card-frame"
        style={{background: PALETTES[paletteIdx]}}
      >
        {product.featuredImage ? (
          <Image
            data={product.featuredImage}
            aspectRatio="4/5"
            sizes="(min-width: 60em) 25vw, 70vw"
            className="pdp-shop-look-card-img"
          />
        ) : (
          <ShopTheLookPlaceholder accent={fallbackHex} variant={variantSeed} />
        )}
      </div>
      <div className="pdp-shop-look-card-body">
        <h3 className="pdp-shop-look-card-title">{product.title}</h3>
        <div className="pdp-shop-look-card-meta">
          <span className="pdp-shop-look-card-rating">
            ★ {stars.toFixed(1)} ({count})
          </span>
          <span className="pdp-shop-look-card-price">
            <Money data={product.priceRange.minVariantPrice} />
          </span>
        </div>
      </div>
    </Link>
  );
}

function ShopTheLookPlaceholder({
  accent,
  variant,
}: {
  accent: string;
  variant: number;
}) {
  return (
    <svg
      viewBox="0 0 400 500"
      preserveAspectRatio="xMidYMid slice"
      className="pdp-shop-look-card-placeholder"
      aria-hidden="true"
    >
      <g opacity="0.85" fill={accent}>
        {variant === 0 ? (
          <path d="M120 120 q80 -40 160 0 v260 q-80 40 -160 0z" />
        ) : variant === 1 ? (
          <>
            <ellipse cx="200" cy="200" rx="60" ry="70" />
            <path d="M120 320 q80 -40 160 0 v100 q-80 40 -160 0z" />
          </>
        ) : variant === 2 ? (
          <path d="M100 250 q100 -120 200 0 q-100 120 -200 0z" />
        ) : (
          <path d="M150 100 l50 60 l50 -60 v300 q-50 40 -100 0z" />
        )}
      </g>
    </svg>
  );
}
