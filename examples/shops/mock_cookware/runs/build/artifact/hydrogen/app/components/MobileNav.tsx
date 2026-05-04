import {useState} from 'react';
import {Link} from 'react-router';
import {useAside} from '~/components/Aside';
import {PRIMARY_NAV, UTILITY_LINKS} from './navigation';

export function MobileNav() {
  const {close} = useAside();
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const toggle = (i: number) => {
    setOpenIndex((cur) => (cur === i ? null : i));
  };

  return (
    <nav className="mobile-nav" aria-label="Mobile navigation">
      <ul className="mobile-nav-list">
        <li className="mobile-nav-item">
          <Link
            to="/"
            className="mobile-nav-link"
            prefetch="intent"
            onClick={close}
          >
            Home
          </Link>
        </li>
        {PRIMARY_NAV.map((entry, i) => {
          if (entry.kind === 'link') {
            return (
              <li key={entry.label} className="mobile-nav-item">
                <Link
                  to={entry.url}
                  className="mobile-nav-link"
                  prefetch="intent"
                  onClick={close}
                >
                  {entry.label}
                </Link>
              </li>
            );
          }

          const isOpen = openIndex === i;
          return (
            <li key={entry.label} className="mobile-nav-item">
              <button
                type="button"
                className="mobile-nav-toggle"
                aria-expanded={isOpen}
                onClick={() => toggle(i)}
              >
                <span>{entry.label}</span>
                <span className="mobile-nav-chevron" aria-hidden="true">
                  {isOpen ? '−' : '+'}
                </span>
              </button>
              {isOpen && (
                <ul className="mobile-nav-sublist">
                  {entry.kind === 'flyout' && (
                    <>
                      {entry.links.map((link) => (
                        <li key={`${entry.label}-${link.label}`}>
                          <Link
                            to={link.url}
                            className="mobile-nav-sublink"
                            prefetch="intent"
                            onClick={close}
                          >
                            {link.label}
                          </Link>
                        </li>
                      ))}
                      <li>
                        <Link
                          to={entry.shopAllUrl}
                          className="mobile-nav-sublink mobile-nav-sublink-strong"
                          prefetch="intent"
                          onClick={close}
                        >
                          {entry.shopAllLabel} →
                        </Link>
                      </li>
                    </>
                  )}
                  {entry.kind === 'mega' && (
                    <>
                      {entry.quickLinks.map((q) => (
                        <li key={`q-${q.label}`}>
                          <Link
                            to={q.url}
                            className="mobile-nav-sublink"
                            prefetch="intent"
                            onClick={close}
                          >
                            {q.label}
                          </Link>
                        </li>
                      ))}
                      {entry.categories.map((col) => (
                        <li key={col.heading}>
                          <Link
                            to={col.headingUrl}
                            className="mobile-nav-sublink"
                            prefetch="intent"
                            onClick={close}
                          >
                            {col.heading}
                          </Link>
                        </li>
                      ))}
                      <li>
                        <Link
                          to={entry.productLine.headingUrl}
                          className="mobile-nav-sublink"
                          prefetch="intent"
                          onClick={close}
                        >
                          {entry.productLine.heading}
                        </Link>
                      </li>
                    </>
                  )}
                </ul>
              )}
            </li>
          );
        })}
        <li className="mobile-nav-divider" aria-hidden="true" />
        {UTILITY_LINKS.map((link) => (
          <li key={link.label} className="mobile-nav-item">
            <Link
              to={link.url}
              className="mobile-nav-link mobile-nav-link-muted"
              prefetch="intent"
              onClick={close}
            >
              {link.label}
            </Link>
          </li>
        ))}
        <li className="mobile-nav-item">
          <Link
            to="/account"
            className="mobile-nav-link mobile-nav-link-muted"
            prefetch="intent"
            onClick={close}
          >
            Account
          </Link>
        </li>
      </ul>
    </nav>
  );
}
