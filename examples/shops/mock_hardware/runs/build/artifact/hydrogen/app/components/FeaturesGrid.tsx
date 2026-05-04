import {Link} from 'react-router';

type FeatureTile = {
  icon: () => React.ReactElement;
  title: string;
  body: string;
};

const TILES: FeatureTile[] = [
  {
    icon: ChannelsIcon,
    title: 'Sell anywhere',
    body: 'Ring up sales at the counter, on the floor, at pop-ups, and online — all from one inventory.',
  },
  {
    icon: StaffIcon,
    title: 'Staff access',
    body: 'Issue PIN-protected staff logins with role-based permissions for cashiers, managers, and owners.',
  },
  {
    icon: PaymentIcon,
    title: 'Take payments',
    body: 'Accept chip, swipe, contactless, and mobile wallets with hardware that just works out of the box.',
  },
  {
    icon: InventoryIcon,
    title: 'Track inventory',
    body: 'Sync stock across channels in real time and reorder before bestsellers run out.',
  },
  {
    icon: CustomerIcon,
    title: 'Know your customers',
    body: 'Build profiles, tag VIPs, and pull up purchase history at the register in a single tap.',
  },
  {
    icon: ReportsIcon,
    title: 'Reports that ship daily',
    body: 'See sales, taxes, payouts, and labor side by side without exporting a single CSV.',
  },
];

export function FeaturesGrid() {
  return (
    <section className="features-section" aria-labelledby="features-heading">
      <div className="features-section-inner">
        <header className="features-section-header">
          <h3 id="features-heading" className="features-section-title">
            Every feature at your fingertips
          </h3>
        </header>
        <ul className="features-grid">
          {TILES.map((tile) => {
            const Icon = tile.icon;
            return (
              <li key={tile.title} className="features-grid-tile">
                <span className="features-grid-icon" aria-hidden="true">
                  <Icon />
                </span>
                <h4 className="features-grid-tile-title">{tile.title}</h4>
                <p className="features-grid-tile-body">{tile.body}</p>
              </li>
            );
          })}
        </ul>
        <div className="features-section-footer">
          <Link
            to="/pages/about"
            prefetch="intent"
            className="features-section-cta"
          >
            Explore the platform
            <span aria-hidden="true" className="features-section-cta-arrow">
              →
            </span>
          </Link>
        </div>
      </div>
    </section>
  );
}

function ChannelsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="11" rx="2" />
      <path d="M7 19h10M9 16v3M15 16v3" />
    </svg>
  );
}

function StaffIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="9" r="3.5" />
      <path d="M3 19c.6-3 3.2-5 6-5s5.4 2 6 5" />
      <circle cx="17" cy="7" r="2.5" />
      <path d="M14 14c1-2 3-3 5-2.5" />
    </svg>
  );
}

function PaymentIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M3 10h18M7 15h3" />
    </svg>
  );
}

function InventoryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7l9-4 9 4-9 4-9-4z" />
      <path d="M3 7v10l9 4 9-4V7" />
      <path d="M12 11v10" />
    </svg>
  );
}

function CustomerIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="9" r="4" />
      <path d="M4 20c1-4 4.5-6 8-6s7 2 8 6" />
    </svg>
  );
}

function ReportsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19V5M4 19h16" />
      <path d="M8 16V11M12 16V8M16 16V13" />
    </svg>
  );
}
