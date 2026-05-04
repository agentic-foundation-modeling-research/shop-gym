interface Badge {
  title: string;
  detail: string;
  icon: 'star' | 'returns' | 'shield' | 'warranty';
}

const BADGES: Badge[] = [
  {
    title: '80,000+ Five-Star Reviews',
    detail: 'Loved by an active, gift-loving community',
    icon: 'star',
  },
  {
    title: 'Extended 60-Day Returns',
    detail: 'Free returns and easy exchanges',
    icon: 'returns',
  },
  {
    title: 'Water, Sweat & Heat Resistant',
    detail: 'Built for studio, street, and beyond',
    icon: 'shield',
  },
  {
    title: 'Up to 5-Year Warranty',
    detail: 'Crafted with a promise of longevity',
    icon: 'warranty',
  },
];

export function TrustBadgesBar() {
  return (
    <section
      className="trust-badges-bar"
      aria-label="Customer assurances"
    >
      <ul className="trust-badges-list">
        {BADGES.map((badge) => (
          <li key={badge.title} className="trust-badge">
            <span className="trust-badge-icon" aria-hidden="true">
              <BadgeIcon name={badge.icon} />
            </span>
            <div className="trust-badge-text">
              <span className="trust-badge-title">{badge.title}</span>
              <span className="trust-badge-detail">{badge.detail}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function BadgeIcon({name}: {name: Badge['icon']}) {
  const common = {
    width: 28,
    height: 28,
    viewBox: '0 0 28 28',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.5,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };

  switch (name) {
    case 'star':
      return (
        <svg {...common}>
          <path d="M14 4l2.9 6 6.6.9-4.8 4.6 1.1 6.6L14 19l-5.8 3.1L9.3 15.5 4.5 11l6.6-.9L14 4z" />
        </svg>
      );
    case 'returns':
      return (
        <svg {...common}>
          <path d="M5 12a9 9 0 0 1 16-5" />
          <path d="M21 4v5h-5" />
          <path d="M23 16a9 9 0 0 1-16 5" />
          <path d="M7 24v-5h5" />
        </svg>
      );
    case 'shield':
      return (
        <svg {...common}>
          <path d="M14 4l8 3v6c0 5.5-4 9.5-8 11-4-1.5-8-5.5-8-11V7l8-3z" />
          <path d="M10.5 14l2.5 2.5L18 11" />
        </svg>
      );
    case 'warranty':
      return (
        <svg {...common}>
          <circle cx="14" cy="11" r="6" />
          <path d="M9 14.5L7 24l7-3 7 3-2-9.5" />
          <path d="M11 11l2 2 4-4" />
        </svg>
      );
  }
}
