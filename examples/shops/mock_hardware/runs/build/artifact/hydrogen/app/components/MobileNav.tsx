import {useState} from 'react';
import {Link} from 'react-router';
import {useAside} from '~/components/Aside';
import {
  DEFAULT_LOCALE_CODE,
  LANGUAGES,
  LOCALES,
  PRIMARY_NAV,
} from './navigation';

type MobileView = 'main' | 'locale';

export function MobileNav() {
  const {close} = useAside();
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [view, setView] = useState<MobileView>('main');
  const [localeCode, setLocaleCode] = useState(DEFAULT_LOCALE_CODE);
  const [language, setLanguage] = useState('EN');

  const activeLocale =
    LOCALES.find((l) => l.code === localeCode) ?? LOCALES[LOCALES.length - 1];

  if (view === 'locale') {
    return (
      <nav className="mobile-nav" aria-label="Region and language">
        <button
          type="button"
          className="mobile-nav-back"
          onClick={() => setView('main')}
        >
          <span aria-hidden="true">←</span> Region and language
        </button>
        <div className="mobile-nav-section">
          <h3 className="mobile-nav-section-heading">Country/Region</h3>
          <ul className="mobile-locale-list">
            {LOCALES.map((loc) => (
              <li key={loc.code}>
                <button
                  type="button"
                  className={`mobile-locale-item${
                    loc.code === localeCode ? ' is-selected' : ''
                  }`}
                  onClick={() => {
                    setLocaleCode(loc.code);
                    setView('main');
                  }}
                >
                  <span className="mobile-locale-name">{loc.country}</span>
                  <span className="mobile-locale-currency">
                    {loc.currency} {loc.symbol}
                  </span>
                  {loc.code === localeCode && (
                    <span aria-hidden="true">✓</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="mobile-nav-section">
          <label htmlFor="mobile-language" className="mobile-nav-section-heading">
            Language
          </label>
          <select
            id="mobile-language"
            className="mobile-language-select"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
          >
            {LANGUAGES.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.label}
              </option>
            ))}
          </select>
        </div>
      </nav>
    );
  }

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
                onClick={() =>
                  setOpenIndex((cur) => (cur === i ? null : i))
                }
              >
                <span>{entry.label}</span>
                <span className="mobile-nav-chevron" aria-hidden="true">
                  {isOpen ? '−' : '+'}
                </span>
              </button>
              {isOpen && (
                <ul className="mobile-nav-sublist">
                  {entry.cards.map((card) => (
                    <li key={card.url}>
                      <Link
                        to={card.url}
                        className="mobile-nav-sublink"
                        prefetch="intent"
                        onClick={close}
                      >
                        {card.title}
                      </Link>
                    </li>
                  ))}
                  {entry.featured?.map((item) => (
                    <li key={item.url}>
                      <Link
                        to={item.url}
                        className="mobile-nav-sublink"
                        prefetch="intent"
                        onClick={close}
                      >
                        {item.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
        <li className="mobile-nav-divider" aria-hidden="true" />
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
        <li className="mobile-nav-item">
          <button
            type="button"
            className="mobile-nav-locale-trigger"
            onClick={() => setView('locale')}
          >
            <span className="mobile-nav-locale-label">
              <span className="mobile-nav-locale-flag" aria-hidden="true">
                🌐
              </span>
              {activeLocale.currency} / {language}
            </span>
            <span aria-hidden="true">›</span>
          </button>
        </li>
      </ul>
    </nav>
  );
}
