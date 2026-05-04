type Feature = {
  badge: string;
  icon: 'shield' | 'leaf' | 'water' | 'medal';
  headline: string;
  body: string;
};

const FEATURES: Feature[] = [
  {
    badge: 'Built to Last',
    icon: 'shield',
    headline: 'Heirloom durability',
    body: 'Forged construction and reinforced rivets stand up to a decade of daily cooking, with surfaces that resist warping and scratches.',
  },
  {
    badge: 'Coating Safety',
    icon: 'leaf',
    headline: 'Toxin-free coatings',
    body: 'PFOA, PFOS, lead, and cadmium free. Our nonstick layers are tested by independent labs for everyday peace of mind.',
  },
  {
    badge: 'Easy Cleanup',
    icon: 'water',
    headline: 'Dishwasher safe',
    body: 'Tested through 2,000 dishwasher cycles. Drop them in the rack at the end of dinner and they come out looking new.',
  },
  {
    badge: '25-Year Warranty',
    icon: 'medal',
    headline: 'Backed for life',
    body: 'Every cookware piece carries a 25-year warranty. If something fails under regular kitchen use, we replace it free.',
  },
];

export function FeatureGrid() {
  return (
    <section className="feature-grid" aria-label="What sets us apart">
      <div className="section-container">
        <div className="section-header section-header-centered">
          <p className="section-eyebrow">Crafted for the long run</p>
          <h2 className="section-title">Designed by chefs, tested in homes</h2>
        </div>
        <div className="feature-grid-cards">
          {FEATURES.map((feature) => (
            <article key={feature.headline} className="feature-card">
              <span className="feature-card-icon" aria-hidden="true">
                <FeatureIcon kind={feature.icon} />
              </span>
              <span className="feature-card-badge">{feature.badge}</span>
              <h3 className="feature-card-headline">{feature.headline}</h3>
              <p className="feature-card-body">{feature.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function FeatureIcon({kind}: {kind: Feature['icon']}) {
  const common = {
    width: 28,
    height: 28,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  if (kind === 'shield') {
    return (
      <svg {...common}>
        <path d="M12 3l8 3v6c0 4.5-3.5 8-8 9-4.5-1-8-4.5-8-9V6l8-3z" />
        <path d="M9 12l2.5 2.5L16 10" />
      </svg>
    );
  }
  if (kind === 'leaf') {
    return (
      <svg {...common}>
        <path d="M5 19c0-8 7-14 15-14 0 8-6 14-14 14a8 8 0 0 1-1 0z" />
        <path d="M5 19c4-4 8-8 14-12" />
      </svg>
    );
  }
  if (kind === 'water') {
    return (
      <svg {...common}>
        <path d="M12 3s7 7 7 12a7 7 0 1 1-14 0c0-5 7-12 7-12z" />
        <path d="M9 14a3 3 0 0 0 3 3" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="9" r="5" />
      <path d="M9 13l-2 8 5-3 5 3-2-8" />
    </svg>
  );
}
