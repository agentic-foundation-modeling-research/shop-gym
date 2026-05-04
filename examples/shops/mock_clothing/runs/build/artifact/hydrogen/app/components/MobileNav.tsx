import {useEffect, useState} from 'react';
import {NavLink} from 'react-router';
import {PRIMARY_NAV} from '~/components/Header';
import {SUB_NAV_CHIPS} from '~/lib/navigation';

interface MobileNavProps {
  open: boolean;
  onClose: () => void;
}

const FEATURED_LINKS = [
  {label: 'New Arrivals', url: '/collections/fresh-drops'},
  {label: 'Editor Selects', url: '/collections/editor-selects'},
  {label: 'Currently Popular', url: '/collections/currently-popular'},
  {label: 'Sale', url: '/collections/end-of-year-promo'},
];

export function MobileNav({open, onClose}: MobileNavProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setExpanded(null);
      return;
    }
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  return (
    <>
      <div
        className={`mobile-nav-scrim${open ? ' is-open' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className={`mobile-nav-drawer${open ? ' is-open' : ''}`}
        aria-label="Site navigation"
        aria-hidden={!open}
      >
        <header className="mobile-nav-header">
          <span className="mobile-nav-title">Menu</span>
          <button
            className="mobile-nav-close"
            type="button"
            onClick={onClose}
            aria-label="Close menu"
          >
            ✕
          </button>
        </header>

        <form className="mobile-nav-search" action="/search" method="get">
          <input
            type="search"
            name="q"
            placeholder="Search products"
            className="mobile-nav-search-input"
            aria-label="Search products"
          />
          <button
            type="submit"
            className="mobile-nav-search-submit"
            aria-label="Submit search"
          >
            <SearchIcon />
          </button>
        </form>

        <div className="mobile-nav-featured">
          <h5 className="mobile-nav-featured-heading">Featured</h5>
          <ul className="mobile-nav-featured-list">
            {FEATURED_LINKS.map((link) => (
              <li key={link.label}>
                <NavLink
                  to={link.url}
                  className="mobile-nav-featured-link"
                  onClick={onClose}
                >
                  {link.label}
                  <span aria-hidden="true">→</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </div>

        <div className="mobile-nav-chips">
          {SUB_NAV_CHIPS.map((chip) => (
            <NavLink
              key={chip.label}
              to={chip.url}
              className="mobile-nav-chip"
              onClick={onClose}
            >
              {chip.label}
            </NavLink>
          ))}
        </div>

        <ul className="mobile-nav-list">
          {PRIMARY_NAV.map((category) => {
            const hasMega = Boolean(
              category.groups && category.groups.length > 0,
            );
            const isExpanded = expanded === category.label;
            if (!hasMega) {
              return (
                <li
                  key={category.label}
                  className={`mobile-nav-item${
                    category.accent ? ' is-accent' : ''
                  }`}
                >
                  <NavLink
                    to={category.url}
                    className="mobile-nav-row mobile-nav-row-link"
                    onClick={onClose}
                  >
                    <span>{category.label}</span>
                    {category.badge === 'new' && (
                      <span className="mobile-nav-badge">New</span>
                    )}
                  </NavLink>
                </li>
              );
            }
            return (
              <li
                key={category.label}
                className={`mobile-nav-item${
                  category.accent ? ' is-accent' : ''
                }`}
              >
                <button
                  type="button"
                  className="mobile-nav-row"
                  onClick={() =>
                    setExpanded(isExpanded ? null : category.label)
                  }
                  aria-expanded={isExpanded}
                >
                  <span>{category.label}</span>
                  <span className="mobile-nav-caret" aria-hidden="true">
                    {isExpanded ? '−' : '+'}
                  </span>
                </button>
                {isExpanded && (
                  <div className="mobile-nav-panel">
                    <NavLink
                      to={category.url}
                      className="mobile-nav-shop-all"
                      onClick={onClose}
                    >
                      Shop all {category.label.toLowerCase()}
                    </NavLink>
                    {category.groups?.map((group) => (
                      <div className="mobile-nav-group" key={group.heading}>
                        <h5 className="mobile-nav-group-heading">
                          {group.heading}
                        </h5>
                        <ul className="mobile-nav-group-list">
                          {group.links.map((link) => (
                            <li key={`${group.heading}-${link.label}`}>
                              <NavLink
                                to={link.url}
                                className="mobile-nav-group-link"
                                onClick={onClose}
                              >
                                {link.label}
                                {link.badge === 'new' && (
                                  <span className="mobile-nav-badge">New</span>
                                )}
                                {link.badge === 'restock' && (
                                  <span className="mobile-nav-badge">
                                    Back In Stock
                                  </span>
                                )}
                              </NavLink>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ul>

        <footer className="mobile-nav-footer">
          <NavLink
            to="/account"
            className="mobile-nav-account-link"
            onClick={onClose}
          >
            Account
          </NavLink>
          <NavLink
            to="/account"
            className="mobile-nav-account-link"
            onClick={onClose}
          >
            Wishlist
          </NavLink>
          <NavLink
            to="/account/orders"
            className="mobile-nav-account-link"
            onClick={onClose}
          >
            Track Order
          </NavLink>
          <button type="button" className="mobile-nav-region">
            🇺🇸 USD
          </button>
        </footer>
      </aside>
    </>
  );
}

function SearchIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="5" />
      <path d="M11 11l3 3" strokeLinecap="round" />
    </svg>
  );
}
