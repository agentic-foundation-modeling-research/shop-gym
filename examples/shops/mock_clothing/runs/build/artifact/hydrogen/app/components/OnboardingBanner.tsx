import {Link} from 'react-router';

export function OnboardingBanner() {
  return (
    <section className="onboarding-banner" aria-label="New visitor onboarding">
      <div className="onboarding-banner-image" aria-hidden="true">
        <svg
          className="onboarding-banner-illustration"
          viewBox="0 0 1400 460"
          preserveAspectRatio="xMidYMid slice"
        >
          <defs>
            <linearGradient id="onboardingGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#5a4633" />
              <stop offset="100%" stopColor="#2a201c" />
            </linearGradient>
            <radialGradient id="onboardingGlow" cx="0.5" cy="0.45" r="0.55">
              <stop offset="0%" stopColor="rgba(197,164,126,0.45)" />
              <stop offset="100%" stopColor="rgba(197,164,126,0)" />
            </radialGradient>
          </defs>
          <rect width="1400" height="460" fill="url(#onboardingGrad)" />
          <rect width="1400" height="460" fill="url(#onboardingGlow)" />
          <g
            stroke="rgba(255,247,232,0.18)"
            strokeWidth="1.5"
            fill="none"
            strokeLinecap="round"
          >
            <path d="M0 360 q350 -180 700 0 t700 0" />
            <path d="M0 410 q350 -180 700 0 t700 0" />
          </g>
        </svg>
      </div>
      <div className="onboarding-banner-content">
        <span className="section-eyebrow onboarding-banner-eyebrow">
          New here?
        </span>
        <h2 className="onboarding-banner-headline">
          Find your starter capsule
        </h2>
        <p className="onboarding-banner-sub">
          Take 60 seconds to explore the pieces our community can't stop wearing
          — buttery leggings, plush hoodies, and lounge sets you'll live in.
        </p>
        <div className="onboarding-banner-actions">
          <Link
            to="/collections/editor-selects"
            prefetch="intent"
            className="btn btn-primary"
          >
            Start Here
          </Link>
          <Link
            to="/collections/fan-favorites"
            prefetch="intent"
            className="btn btn-ghost-light"
          >
            Browse Best Sellers
          </Link>
        </div>
      </div>
    </section>
  );
}
