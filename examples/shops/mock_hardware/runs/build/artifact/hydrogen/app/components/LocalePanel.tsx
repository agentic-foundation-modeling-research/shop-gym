import {useMemo, useState} from 'react';
import {
  DEFAULT_LOCALE_CODE,
  LANGUAGES,
  LOCALES,
  type Locale,
} from './navigation';

export function LocaleButton({
  locale,
  isOpen,
  onToggle,
}: {
  locale: Locale;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="locale-button"
      aria-expanded={isOpen}
      aria-haspopup="dialog"
      onClick={onToggle}
    >
      <span className="locale-button-flag" aria-hidden="true">
        <FlagIcon code={locale.code} />
      </span>
      <span className="locale-button-text">
        {locale.currency}
        <span className="locale-button-divider" aria-hidden="true">
          /
        </span>
        EN
      </span>
      <span className="locale-button-chevron" aria-hidden="true">
        ▾
      </span>
    </button>
  );
}

export function LocalePanel({
  selectedCode,
  onSelect,
  onClose,
}: {
  selectedCode: string;
  onSelect: (code: string) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [language, setLanguage] = useState('EN');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return LOCALES;
    return LOCALES.filter((loc) =>
      loc.country.toLowerCase().includes(q) ||
      loc.currency.toLowerCase().includes(q),
    );
  }, [query]);

  return (
    <div className="locale-panel" role="dialog" aria-label="Region and language">
      <div className="locale-panel-section">
        <h3 className="locale-panel-heading">Country/Region</h3>
        <div className="locale-search-wrap">
          <svg
            className="locale-search-icon"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4.3-4.3" />
          </svg>
          <input
            type="search"
            className="locale-search-input"
            placeholder="Search countries"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search countries"
          />
        </div>
        <ul className="locale-list" role="listbox" aria-label="Country">
          {filtered.map((loc) => {
            const selected = loc.code === selectedCode;
            return (
              <li key={loc.code}>
                <button
                  type="button"
                  className={`locale-list-item${selected ? ' is-selected' : ''}`}
                  role="option"
                  aria-selected={selected}
                  onClick={() => {
                    onSelect(loc.code);
                    onClose();
                  }}
                >
                  <span className="locale-list-flag" aria-hidden="true">
                    <FlagIcon code={loc.code} />
                  </span>
                  <span className="locale-list-name">{loc.country}</span>
                  <span className="locale-list-currency">
                    {loc.currency} {loc.symbol}
                  </span>
                  {selected && (
                    <span className="locale-list-check" aria-hidden="true">
                      ✓
                    </span>
                  )}
                </button>
              </li>
            );
          })}
          {filtered.length === 0 && (
            <li className="locale-list-empty">No matching regions</li>
          )}
        </ul>
      </div>
      <div className="locale-panel-section locale-panel-language">
        <label htmlFor="locale-language" className="locale-panel-heading">
          Language
        </label>
        <select
          id="locale-language"
          className="locale-language-select"
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
    </div>
  );
}

export {DEFAULT_LOCALE_CODE};

function FlagIcon({code}: {code: string}) {
  return (
    <svg viewBox="0 0 16 12" width="16" height="12" aria-hidden="true">
      <rect width="16" height="12" rx="1.5" fill="#e1e3e5" />
      <text
        x="8"
        y="9"
        textAnchor="middle"
        fontSize="6.5"
        fontWeight="700"
        fill="#1a1a1a"
        fontFamily="-apple-system, BlinkMacSystemFont, sans-serif"
      >
        {code}
      </text>
    </svg>
  );
}
