import {Link} from 'react-router';
import type {MegaEntry} from './navigation';

function CardIllustration({label}: {label: string}) {
  return (
    <svg
      className="mega-card-illustration"
      viewBox="0 0 80 80"
      fill="none"
      aria-hidden="true"
    >
      <rect width="80" height="80" rx="10" fill="#f4f6f8" />
      <rect x="16" y="22" width="48" height="32" rx="4" fill="#1a1a1a" />
      <rect x="20" y="26" width="40" height="20" rx="2" fill="#ffffff" />
      <rect x="24" y="30" width="32" height="2" rx="1" fill="#1a1a1a" opacity="0.2" />
      <rect x="24" y="36" width="20" height="2" rx="1" fill="#1a1a1a" opacity="0.2" />
      <circle cx="56" cy="38" r="3" fill="#008060" />
      <text
        x="40"
        y="68"
        textAnchor="middle"
        fontSize="6"
        fontWeight="600"
        fill="#6b7177"
      >
        {label}
      </text>
    </svg>
  );
}

export function MegaPanel({
  entry,
  onClose,
}: {
  entry: MegaEntry;
  onClose: () => void;
}) {
  return (
    <div className="mega-menu" role="region" aria-label={`${entry.label} menu`}>
      <div className="mega-menu-inner">
        {entry.cards.map((card) => (
          <Link
            key={card.url}
            to={card.url}
            className="mega-card"
            prefetch="intent"
            onClick={onClose}
          >
            <div className="mega-card-image">
              <CardIllustration label={card.title.toUpperCase()} />
            </div>
            <div className="mega-card-body">
              <h3 className="mega-card-title">{card.title}</h3>
              <p className="mega-card-subcopy">{card.subcopy}</p>
              <span className="mega-card-cta" aria-hidden="true">
                Shop now →
              </span>
            </div>
          </Link>
        ))}
      </div>
      {entry.featured && entry.featured.length > 0 && (
        <div className="mega-menu-featured">
          <span className="mega-menu-featured-label">Shop by category</span>
          <ul className="mega-menu-featured-list">
            {entry.featured.map((item) => (
              <li key={item.url}>
                <Link
                  to={item.url}
                  className="mega-menu-featured-link"
                  prefetch="intent"
                  onClick={onClose}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
