import {Link} from 'react-router';

export function HeroBanner() {
  return (
    <section className="hero-banner" aria-label="Spring Edit campaign">
      <div className="hero-banner-image" aria-hidden="true">
        <HeroIllustration />
      </div>
      <div className="hero-banner-overlay">
        <div className="hero-banner-content">
          <span className="hero-banner-eyebrow">The Spring Edit</span>
          <h1 className="hero-banner-headline">
            Layered for the way
            <br />
            you actually live.
          </h1>
          <p className="hero-banner-sub">
            New chains, soft tailoring, and studio-to-street essentials —
            crafted to wear together, designed to last beyond the season.
          </p>
          <div className="hero-banner-cta-row">
            <Link
              to="/collections/fresh-drops"
              className="btn btn-primary hero-banner-cta"
              prefetch="intent"
            >
              Shop New In
            </Link>
            <Link
              to="/collections/fan-favorites"
              className="btn btn-ghost-light hero-banner-cta-secondary"
              prefetch="intent"
            >
              Shop Best Sellers
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

function HeroIllustration() {
  return (
    <svg
      className="hero-banner-illustration"
      viewBox="0 0 1600 720"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="heroBg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#e8d6c0" />
          <stop offset="55%" stopColor="#cdb497" />
          <stop offset="100%" stopColor="#9a8367" />
        </linearGradient>
        <radialGradient id="heroGlow" cx="0.78" cy="0.32" r="0.55">
          <stop offset="0%" stopColor="#fff7e8" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#fff7e8" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="1600" height="720" fill="url(#heroBg)" />
      <rect width="1600" height="720" fill="url(#heroGlow)" />
      <g opacity="0.18" fill="#2a201c">
        <ellipse cx="1180" cy="660" rx="420" ry="40" />
        <ellipse cx="280" cy="700" rx="380" ry="36" />
      </g>
      <g
        stroke="rgba(42,32,28,0.16)"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
      >
        <path d="M1100 220 q120 -60 240 80 q60 80 -20 220" />
        <path d="M1080 240 q140 0 260 140 q40 80 -10 200" />
      </g>
      <g fill="rgba(42,32,28,0.32)">
        <circle cx="1240" cy="270" r="6" />
        <circle cx="1265" cy="295" r="5" />
        <circle cx="1290" cy="320" r="4" />
        <circle cx="1315" cy="350" r="3" />
      </g>
    </svg>
  );
}
