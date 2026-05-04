import {Link} from 'react-router';

interface FeatureBlockProps {
  eyebrow: string;
  heading: string;
  body: string;
  ctaLabel: string;
  ctaUrl: string;
  imagePosition: 'left' | 'right';
  variant?: 'default' | 'soft';
  imagePalette: {
    bg: string;
    glyph: 'craft' | 'guarantee';
  };
}

export function FeatureBlock({
  eyebrow,
  heading,
  body,
  ctaLabel,
  ctaUrl,
  imagePosition,
  variant = 'default',
  imagePalette,
}: FeatureBlockProps) {
  return (
    <section
      className={`feature-block feature-block-${imagePosition}${
        variant === 'soft' ? ' feature-block-soft' : ''
      }`}
    >
      <div className="feature-block-image" style={{background: imagePalette.bg}}>
        <FeatureGlyph glyph={imagePalette.glyph} />
      </div>
      <div className="feature-block-text">
        <span className="section-eyebrow">{eyebrow}</span>
        <h2 className="section-heading section-heading-serif">{heading}</h2>
        <p className="feature-block-body">{body}</p>
        <Link
          to={ctaUrl}
          prefetch="intent"
          className={
            variant === 'soft' ? 'btn btn-link' : 'btn btn-secondary'
          }
        >
          {ctaLabel}
        </Link>
      </div>
    </section>
  );
}

function FeatureGlyph({glyph}: {glyph: 'craft' | 'guarantee'}) {
  if (glyph === 'craft') {
    return (
      <svg
        className="feature-block-glyph"
        viewBox="0 0 320 320"
        aria-hidden="true"
      >
        <defs>
          <radialGradient id="craftGlow" cx="0.5" cy="0.4" r="0.6">
            <stop offset="0%" stopColor="rgba(255,247,232,0.55)" />
            <stop offset="100%" stopColor="rgba(255,247,232,0)" />
          </radialGradient>
        </defs>
        <rect width="320" height="320" fill="url(#craftGlow)" />
        <g
          stroke="rgba(255,255,255,0.7)"
          fill="none"
          strokeWidth="2"
          strokeLinecap="round"
        >
          <circle cx="160" cy="150" r="64" />
          <path d="M160 86 v128" />
          <path d="M96 150 h128" />
          <path d="M115 105 l90 90" />
          <path d="M205 105 l-90 90" />
        </g>
        <circle cx="160" cy="150" r="14" fill="rgba(255,255,255,0.85)" />
      </svg>
    );
  }
  return (
    <svg
      className="feature-block-glyph"
      viewBox="0 0 320 320"
      aria-hidden="true"
    >
      <g
        stroke="rgba(42,32,28,0.7)"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M160 60 l72 28 v60 c0 56 -44 96 -72 110 -28 -14 -72 -54 -72 -110 V88 z" />
        <path d="M128 152 l24 24 l44 -52" />
      </g>
      <circle cx="160" cy="60" r="6" fill="rgba(42,32,28,0.6)" />
    </svg>
  );
}
