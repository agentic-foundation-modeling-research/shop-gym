import {Link} from 'react-router';
import {Image} from '@shopify/hydrogen';
import type {HomepageProductFragment} from 'storefrontapi.generated';

export type FeatureCardProps = {
  eyebrow: string;
  headline: string;
  body: string;
  ctaLabel: string;
  ctaUrl: string;
  product: HomepageProductFragment | null;
  variant?: 'light' | 'dark';
  reverse?: boolean;
};

export function FeatureCard({
  eyebrow,
  headline,
  body,
  ctaLabel,
  ctaUrl,
  product,
  variant = 'light',
  reverse = false,
}: FeatureCardProps) {
  const className = [
    'feature-card',
    `feature-card-${variant}`,
    reverse ? 'feature-card-reverse' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <section className={className}>
      <div className="feature-card-inner">
        <div className="feature-card-media" aria-hidden="true">
          {product?.featuredImage ? (
            <Image
              data={product.featuredImage}
              alt=""
              sizes="(min-width: 60em) 640px, 100vw"
              loading="lazy"
              className="feature-card-image"
            />
          ) : (
            <FeatureCardPlaceholder />
          )}
        </div>
        <div className="feature-card-copy">
          <p className="feature-card-eyebrow">{eyebrow}</p>
          <h2 className="feature-card-headline">{headline}</h2>
          <p className="feature-card-body">{body}</p>
          <Link
            to={ctaUrl}
            prefetch="intent"
            className="feature-card-cta"
          >
            {ctaLabel}
            <span aria-hidden="true" className="feature-card-cta-arrow">
              →
            </span>
          </Link>
        </div>
      </div>
    </section>
  );
}

function FeatureCardPlaceholder() {
  return (
    <svg
      viewBox="0 0 480 360"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label=""
      className="feature-card-image"
    >
      <rect width="480" height="360" rx="12" fill="#eef0f2" />
      <rect x="140" y="130" width="200" height="120" rx="10" fill="#1a1a1a" />
      <circle cx="240" cy="190" r="22" fill="#008060" />
    </svg>
  );
}
