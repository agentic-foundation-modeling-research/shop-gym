import {Link} from 'react-router';
import type {FeaturedCard, FlyoutEntry, MegaEntry} from './navigation';

function ProductPlaceholder() {
  return (
    <svg
      className="nav-card-placeholder"
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <rect width="48" height="48" rx="4" fill="#f0ede8" />
      <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
      <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
    </svg>
  );
}

function StarRating({rating}: {rating: number}) {
  return (
    <span className="nav-card-rating" aria-label={`${rating} out of 5 stars`}>
      {Array.from({length: 5}).map((_, i) => (
        <span key={i} aria-hidden="true" className={i < rating ? 'star filled' : 'star'}>
          ★
        </span>
      ))}
    </span>
  );
}

function FeaturedProductCard({
  card,
  onClick,
}: {
  card: FeaturedCard;
  onClick?: () => void;
}) {
  return (
    <Link
      to={`/products/${card.handle}`}
      className="nav-featured-card"
      prefetch="intent"
      onClick={onClick}
    >
      <div className="nav-featured-image">
        {card.imageUrl ? (
          <img src={card.imageUrl} alt={card.title} loading="lazy" decoding="async" />
        ) : (
          <ProductPlaceholder />
        )}
        {card.savings && <span className="nav-featured-badge">{card.savings}</span>}
      </div>
      <div className="nav-featured-meta">
        <span className="nav-featured-name">{card.title}</span>
        <span className="nav-featured-price">
          <span className="price">{card.price}</span>
          {card.compareAt && <s className="compare-at">{card.compareAt}</s>}
        </span>
        <StarRating rating={card.rating} />
      </div>
    </Link>
  );
}

export function FlyoutPanel({
  entry,
  onClose,
}: {
  entry: FlyoutEntry;
  onClose: () => void;
}) {
  return (
    <div className="mega-menu" role="region" aria-label={`${entry.label} menu`}>
      <div className="mega-menu-inner flyout-layout">
        <ul className="flyout-links">
          {entry.links.map((link) => (
            <li key={`${link.label}-${link.url}`}>
              <Link
                to={link.url}
                className="flyout-link"
                prefetch="intent"
                onClick={onClose}
              >
                {link.label}
              </Link>
            </li>
          ))}
          <li>
            <Link
              to={entry.shopAllUrl}
              className="flyout-link flyout-link-strong"
              prefetch="intent"
              onClick={onClose}
            >
              {entry.shopAllLabel} →
            </Link>
          </li>
        </ul>
        <div className="flyout-featured">
          {entry.featured.map((card) => (
            <FeaturedProductCard
              key={card.handle}
              card={card}
              onClick={onClose}
            />
          ))}
        </div>
      </div>
    </div>
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
      <div className="mega-menu-inner mega-layout">
        <div className="mega-column mega-quick">
          <h3 className="mega-heading">Quick Links</h3>
          <ul>
            {entry.quickLinks.map((q) => (
              <li key={q.label}>
                <Link to={q.url} prefetch="intent" onClick={onClose}>
                  {q.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        {entry.categories.map((col) => (
          <div className="mega-column" key={col.heading}>
            <h3 className="mega-heading">
              <Link to={col.headingUrl} prefetch="intent" onClick={onClose}>
                {col.heading}
              </Link>
            </h3>
            <ul>
              {col.links.map((link) => (
                <li key={`${col.heading}-${link.label}`}>
                  <Link to={link.url} prefetch="intent" onClick={onClose}>
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="mega-column">
          <h3 className="mega-heading">
            <Link to={entry.productLine.headingUrl} prefetch="intent" onClick={onClose}>
              {entry.productLine.heading}
            </Link>
          </h3>
          <ul>
            {entry.productLine.links.map((link) => (
              <li key={`pl-${link.label}`}>
                <Link to={link.url} prefetch="intent" onClick={onClose}>
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        {entry.colors.length > 0 && (
          <div className="mega-column mega-colors">
            <h3 className="mega-heading">Colors</h3>
            <ul className="mega-color-list">
              {entry.colors.map((c) => (
                <li key={c.label}>
                  <Link
                    to={c.url}
                    prefetch="intent"
                    onClick={onClose}
                    className="mega-color-item"
                  >
                    <span
                      className="mega-color-swatch"
                      style={{background: c.swatch}}
                      aria-hidden="true"
                    />
                    <span>{c.label}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
