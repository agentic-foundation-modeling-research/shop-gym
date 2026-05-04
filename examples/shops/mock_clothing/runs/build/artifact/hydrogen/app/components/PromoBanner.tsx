import {Link} from 'react-router';

interface PromoBannerProps {
  eyebrow: string;
  headline: string;
  subline: string;
  ctaLabel: string;
  ctaUrl: string;
  /** Position of the text/CTA over the image (default: bottom-left). */
  align?: 'bottom-left' | 'lower-left' | 'center';
  background: {
    primary: string;
    secondary: string;
    accent?: string;
  };
}

export function PromoBanner({
  eyebrow,
  headline,
  subline,
  ctaLabel,
  ctaUrl,
  align = 'lower-left',
  background,
}: PromoBannerProps) {
  return (
    <section
      className={`promo-banner promo-banner-${align}`}
      aria-label={headline}
    >
      <div className="promo-banner-image" aria-hidden="true">
        <PromoArt
          primary={background.primary}
          secondary={background.secondary}
          accent={background.accent ?? '#fff7e8'}
        />
      </div>
      <div className="promo-banner-overlay">
        <div className="promo-banner-content">
          <span className="section-eyebrow promo-banner-eyebrow">{eyebrow}</span>
          <h2 className="promo-banner-headline">{headline}</h2>
          <p className="promo-banner-sub">{subline}</p>
          <Link
            to={ctaUrl}
            prefetch="intent"
            className="btn btn-primary promo-banner-cta"
          >
            {ctaLabel}
          </Link>
        </div>
      </div>
    </section>
  );
}

function PromoArt({
  primary,
  secondary,
  accent,
}: {
  primary: string;
  secondary: string;
  accent: string;
}) {
  const id = (primary + secondary).replace(/#/g, '');
  return (
    <svg
      className="promo-banner-illustration"
      viewBox="0 0 1600 560"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={`promoBg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={primary} />
          <stop offset="100%" stopColor={secondary} />
        </linearGradient>
        <radialGradient id={`promoGlow-${id}`} cx="0.7" cy="0.4" r="0.55">
          <stop offset="0%" stopColor={accent} stopOpacity="0.55" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="1600" height="560" fill={`url(#promoBg-${id})`} />
      <rect width="1600" height="560" fill={`url(#promoGlow-${id})`} />
      <g
        stroke="rgba(255,255,255,0.18)"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
      >
        <path d="M0 380 q300 -180 600 -40 t600 60 t400 -40" />
        <path d="M0 440 q300 -160 600 -20 t600 80 t400 -20" />
      </g>
      <g opacity="0.16" fill="#2a201c">
        <ellipse cx="1280" cy="500" rx="380" ry="32" />
      </g>
    </svg>
  );
}
