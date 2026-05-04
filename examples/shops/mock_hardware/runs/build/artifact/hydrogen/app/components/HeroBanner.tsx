import {Link} from 'react-router';
import {Image} from '@shopify/hydrogen';
import type {HomepageProductFragment} from 'storefrontapi.generated';

export function HeroBanner({product}: {product: HomepageProductFragment | null}) {
  return (
    <section className="hero-banner" aria-label="Featured POS hardware">
      <div className="hero-banner-inner">
        <div className="hero-banner-copy">
          <p className="hero-banner-eyebrow">POS Hardware</p>
          <h1 className="hero-banner-headline">
            Your one-stop hardware shop
          </h1>
          <p className="hero-banner-subline">
            Card readers, slip printers, scanners, till trays, and the
            countertop bundles that tie them together — built for the way
            small retailers actually sell.
          </p>
          <div className="hero-banner-ctas">
            <Link
              to="/collections/code-readers"
              prefetch="intent"
              className="hero-banner-cta"
            >
              Shop now
              <span aria-hidden="true" className="hero-banner-cta-arrow">
                →
              </span>
            </Link>
          </div>
        </div>
        <div className="hero-banner-media" aria-hidden="true">
          {product?.featuredImage ? (
            <Image
              data={product.featuredImage}
              alt=""
              sizes="(min-width: 60em) 640px, 100vw"
              loading="eager"
              className="hero-banner-image"
            />
          ) : (
            <HeroPlaceholder />
          )}
        </div>
      </div>
    </section>
  );
}

function HeroPlaceholder() {
  return (
    <svg
      viewBox="0 0 480 360"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label=""
      className="hero-banner-image"
    >
      <rect width="480" height="360" rx="12" fill="#f4f6f8" />
      <rect x="120" y="120" width="240" height="160" rx="14" fill="#dcdfe2" />
      <rect x="160" y="160" width="160" height="80" rx="6" fill="#1a1a1a" />
      <circle cx="280" cy="280" r="14" fill="#008060" />
    </svg>
  );
}
