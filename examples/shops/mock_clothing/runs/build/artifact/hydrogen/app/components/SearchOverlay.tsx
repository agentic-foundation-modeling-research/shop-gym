import {useEffect, useState} from 'react';
import {Link} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import {useAside} from '~/components/Aside';
import {
  type PredictiveSearchReturn,
  getEmptyPredictiveSearchResult,
} from '~/lib/search';
import {usePredictiveSearchForm} from '~/components/SearchFormPredictive';

const TRENDING_SEARCHES = [
  'Linen trousers',
  'Summer dresses',
  'Wide-leg jeans',
  'Wrap tops',
  'Linen shirts',
  'Lightweight jackets',
];

const RECENT_KEY = 'mock-apparel:recent-searches';
const RECENT_LIMIT = 4;

function readRecent(): string[] {
  if (typeof window === 'undefined') return [];
  const stored = window.localStorage.getItem(RECENT_KEY);
  if (!stored) return [];
  try {
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((t): t is string => typeof t === 'string')
      .slice(0, RECENT_LIMIT);
  } catch {
    return [];
  }
}

function writeRecent(list: string[]) {
  window.localStorage.setItem(RECENT_KEY, JSON.stringify(list));
}

export function SearchOverlay() {
  const {type, close} = useAside();
  const open = type === 'search';
  const [query, setQuery] = useState('');
  const [recent, setRecent] = useState<string[]>([]);
  const {fetcher, inputRef, goToSearch, fetchResults} = usePredictiveSearchForm(
    {
      autoFocus: open,
      onNavigate: close,
    },
  );

  useEffect(() => {
    if (open) setRecent(readRecent());
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, close]);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (open) {
      const previous = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = previous;
      };
    }
  }, [open]);

  if (!open) return null;

  const persistRecent = (term: string) => {
    const trimmed = term.trim();
    if (!trimmed) return;
    setRecent((prev) => {
      const next = [trimmed, ...prev.filter((t) => t !== trimmed)].slice(
        0,
        RECENT_LIMIT,
      );
      writeRecent(next);
      return next;
    });
  };

  const onChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    setQuery(value);
    fetchResults(value);
  };

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const term = query.trim();
    if (!term) return;
    persistRecent(term);
    goToSearch(term);
  };

  const clearInput = () => {
    setQuery('');
    inputRef.current?.focus();
  };

  const removeRecent = (term: string) => {
    setRecent((prev) => {
      const next = prev.filter((t) => t !== term);
      writeRecent(next);
      return next;
    });
  };

  const clearAllRecent = () => {
    setRecent([]);
    window.localStorage.removeItem(RECENT_KEY);
  };

  const followLink = (term: string) => {
    persistRecent(term);
    goToSearch(term);
  };

  const showResults = query.trim().length >= 2;
  const data = fetcher.data?.result ?? getEmptyPredictiveSearchResult();
  const loading = fetcher.state === 'loading';

  return (
    <div
      className="search-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Search"
    >
      <div className="search-overlay-scrim" onClick={close} />
      <div className="search-overlay-panel">
        <form className="search-overlay-form" onSubmit={onSubmit}>
          <span className="search-overlay-input-icon" aria-hidden="true">
            <SearchIcon />
          </span>
          <input
            ref={inputRef}
            type="search"
            className="search-overlay-input"
            placeholder="What are you looking for?"
            aria-label="Search"
            value={query}
            onChange={onChange}
            autoComplete="off"
          />
          {query ? (
            <button
              type="button"
              className="search-overlay-clear"
              aria-label="Clear search"
              onClick={clearInput}
            >
              ×
            </button>
          ) : null}
          <button
            type="button"
            className="search-overlay-close"
            aria-label="Close search"
            onClick={close}
          >
            Close
          </button>
        </form>

        {showResults ? (
          <p className="search-overlay-helper">
            Press Enter to see all results for &ldquo;{query}&rdquo;
          </p>
        ) : null}

        <div className="search-overlay-body">
          {showResults ? (
            <SearchResultsRegion
              data={data}
              loading={loading}
              query={query}
              onFollow={close}
            />
          ) : (
            <SearchSuggestionsRegion
              recent={recent}
              onFollow={followLink}
              onRemoveRecent={removeRecent}
              onClearRecent={clearAllRecent}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function SearchSuggestionsRegion({
  recent,
  onFollow,
  onRemoveRecent,
  onClearRecent,
}: {
  recent: string[];
  onFollow: (term: string) => void;
  onRemoveRecent: (term: string) => void;
  onClearRecent: () => void;
}) {
  return (
    <div className="search-suggestions">
      <div className="search-suggestions-col">
        <h4 className="search-suggestions-heading">Trending Searches</h4>
        <ul className="search-suggestions-list">
          {TRENDING_SEARCHES.map((term) => (
            <li key={term}>
              <button
                type="button"
                className="search-suggestions-link"
                onClick={() => onFollow(term)}
              >
                {term}
              </button>
            </li>
          ))}
        </ul>
      </div>
      {recent.length > 0 ? (
        <div className="search-suggestions-col">
          <div className="search-suggestions-heading-row">
            <h4 className="search-suggestions-heading">Recent Searches</h4>
            <button
              type="button"
              className="search-suggestions-clear"
              onClick={onClearRecent}
            >
              Clear all
            </button>
          </div>
          <ul className="search-suggestions-list">
            {recent.map((term) => (
              <li key={term} className="search-suggestions-recent-item">
                <button
                  type="button"
                  className="search-suggestions-link"
                  onClick={() => onFollow(term)}
                >
                  {term}
                </button>
                <button
                  type="button"
                  className="search-suggestions-remove"
                  aria-label={`Remove ${term} from recent searches`}
                  onClick={() => onRemoveRecent(term)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function SearchResultsRegion({
  data,
  loading,
  query,
  onFollow,
}: {
  data: PredictiveSearchReturn['result'];
  loading: boolean;
  query: string;
  onFollow: () => void;
}) {
  const {queries, collections, products} = data.items;
  const hasAny =
    queries.length > 0 || collections.length > 0 || products.length > 0;

  if (loading && !hasAny) {
    return <p className="search-empty">Searching…</p>;
  }

  if (!hasAny) {
    return (
      <p className="search-empty">
        No quick suggestions for &ldquo;{query}&rdquo;. Press Enter to see all
        results.
      </p>
    );
  }

  return (
    <div className="search-results-grid">
      <div className="search-results-text-col">
        {queries.length > 0 ? (
          <div className="search-results-block">
            <h5 className="search-results-block-heading">Suggestions</h5>
            <ul className="search-results-block-list">
              {queries.slice(0, 4).map((q) => (
                <li key={q.text}>
                  <Link
                    to={`/search?q=${encodeURIComponent(q.text)}`}
                    onClick={onFollow}
                    className="search-results-query-link"
                  >
                    <SearchIcon />
                    <span>{q.text}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {collections.length > 0 ? (
          <div className="search-results-block">
            <h5 className="search-results-block-heading">Collections</h5>
            <ul className="search-results-block-list">
              {collections.slice(0, 3).map((c) => (
                <li key={c.id}>
                  <Link
                    to={`/collections/${c.handle}`}
                    onClick={onFollow}
                    className="search-results-collection-link"
                  >
                    <FolderIcon />
                    <span>{c.title}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {products.length > 0 ? (
        <div className="search-results-products-col">
          <h5 className="search-results-block-heading">Products</h5>
          <ul className="search-results-products-grid">
            {products.slice(0, 6).map((p) => {
              const variant = p.selectedOrFirstAvailableVariant;
              const image = variant?.image;
              const price = variant?.price;
              return (
                <li key={p.id} className="search-results-product-card">
                  <Link
                    to={`/products/${p.handle}`}
                    onClick={onFollow}
                    className="search-results-product-link"
                  >
                    <div className="search-results-product-image">
                      {image ? (
                        <Image
                          alt={image.altText ?? p.title}
                          data={image}
                          width={120}
                          height={120}
                          sizes="120px"
                        />
                      ) : (
                        <div className="search-results-product-placeholder">
                          <svg
                            width="32"
                            height="32"
                            viewBox="0 0 48 48"
                            fill="none"
                            aria-hidden="true"
                          >
                            <rect
                              width="48"
                              height="48"
                              rx="4"
                              fill="#f0ede8"
                            />
                            <path
                              d="M17 31l5-7 4 5 6-8 7 10H9l8-10z"
                              fill="#d4cfc7"
                            />
                          </svg>
                        </div>
                      )}
                    </div>
                    <div className="search-results-product-meta">
                      <span className="search-results-product-title">
                        {p.title}
                      </span>
                      {price ? (
                        <span className="search-results-product-price">
                          <Money data={price} />
                        </span>
                      ) : null}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function SearchIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <circle cx="9" cy="9" r="6" />
      <path d="M14 14l4 4" strokeLinecap="round" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <path
        d="M3 6.5A1.5 1.5 0 0 1 4.5 5h3l1.5 1.5h6A1.5 1.5 0 0 1 16.5 8v6.5A1.5 1.5 0 0 1 15 16H4.5A1.5 1.5 0 0 1 3 14.5v-8z"
        strokeLinejoin="round"
      />
    </svg>
  );
}
