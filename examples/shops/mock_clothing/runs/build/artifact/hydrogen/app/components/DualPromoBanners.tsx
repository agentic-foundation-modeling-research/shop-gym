import {Link} from 'react-router';

interface DualBanner {
  eyebrow: string;
  headline: string;
  subline: string;
  ctaLabel: string;
  ctaUrl: string;
  imageUrl: string;
}

const BANNERS: DualBanner[] = [
  {
    eyebrow: 'Print Drop',
    headline: 'The Vendarena Print',
    subline:
      'A signature pattern that wears with everything — from morning runs to easy weekends.',
    ctaLabel: 'Shop Now',
    ctaUrl: '/collections/spotted-on-feeds',
    imageUrl: '/images/collection-spotted-on-feeds.png',
  },
  {
    eyebrow: 'Seasonal Color',
    headline: 'Soft Sage Refresh',
    subline:
      'Spring greens for studio mornings — fresh in your favourite leggings, tees, and sets.',
    ctaLabel: 'Shop Now',
    ctaUrl: '/collections/vernal-season-edit',
    imageUrl: '/images/collection-vernal-season-edit.png',
  },
];

export function DualPromoBanners() {
  return (
    <section className="dual-promo-banners" aria-label="Featured drops">
      <ul className="dual-promo-banners-list">
        {BANNERS.map((banner) => (
          <li key={banner.headline} className="dual-promo-banner">
            <Link
              to={banner.ctaUrl}
              prefetch="intent"
              className="dual-promo-banner-link"
              style={{backgroundImage: `url(${banner.imageUrl})`}}
            >
              <span className="dual-promo-banner-scrim" aria-hidden="true" />
              <span className="dual-promo-banner-content">
                <span className="dual-promo-banner-eyebrow">
                  {banner.eyebrow}
                </span>
                <span className="dual-promo-banner-headline">
                  {banner.headline}
                </span>
                <span className="dual-promo-banner-sub">{banner.subline}</span>
                <span className="dual-promo-banner-cta">
                  {banner.ctaLabel} →
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
