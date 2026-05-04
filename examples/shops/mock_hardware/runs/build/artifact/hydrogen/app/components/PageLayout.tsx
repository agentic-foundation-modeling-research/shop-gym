import {Link} from 'react-router';
import {useEffect, useId, useState} from 'react';
import type {
  CartApiQueryFragment,
  FooterQuery,
  HeaderQuery,
} from 'storefrontapi.generated';
import {Aside} from '~/components/Aside';
import {Footer} from '~/components/Footer';
import {Header} from '~/components/Header';
import {MobileNav} from '~/components/MobileNav';
import {
  SEARCH_ENDPOINT,
  SearchFormPredictive,
} from '~/components/SearchFormPredictive';
import {SearchResultsPredictive} from '~/components/SearchResultsPredictive';
import {CookieConsentBanner} from '~/components/CookieConsentBanner';
import {PromoPopup} from '~/components/PromoPopup';

interface PageLayoutProps {
  cart: Promise<CartApiQueryFragment | null>;
  footer: Promise<FooterQuery | null>;
  header: HeaderQuery;
  isLoggedIn: Promise<boolean>;
  publicStoreDomain: string;
  children?: React.ReactNode;
}

export function PageLayout({
  cart,
  children = null,
  footer,
  header,
  isLoggedIn,
  publicStoreDomain,
}: PageLayoutProps) {
  const [searchOpen, setSearchOpen] = useState(false);

  return (
    <Aside.Provider>
      <MobileMenuAside header={header} />
      {header && (
        <Header
          header={header}
          cart={cart}
          isLoggedIn={isLoggedIn}
          publicStoreDomain={publicStoreDomain}
          onOpenSearch={() => setSearchOpen(true)}
        />
      )}
      <main>{children}</main>
      <Footer
        footer={footer}
        header={header}
        publicStoreDomain={publicStoreDomain}
      />
      <SearchOverlay open={searchOpen} onClose={() => setSearchOpen(false)} />
      <CookieConsentBanner />
      <PromoPopup />
    </Aside.Provider>
  );
}

function SearchOverlay({open, onClose}: {open: boolean; onClose: () => void}) {
  const queriesDatalistId = useId();
  const headingId = useId();

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="search-overlay" role="presentation">
      <div
        className="search-overlay-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
      >
        <div className="search-overlay-header">
          <h2 id={headingId} className="sr-only">
            Search
          </h2>
          <SearchFormPredictive
            className="search-overlay-form"
            onSubmitNavigate={onClose}
          >
            {({fetchResults, goToSearch, inputRef}) => (
              <>
                <span className="search-overlay-icon" aria-hidden="true">
                  <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <circle cx="11" cy="11" r="7" />
                    <path d="M21 21l-4.3-4.3" />
                  </svg>
                </span>
                <label htmlFor="search-overlay-input" className="sr-only">
                  Search
                </label>
                <input
                  id="search-overlay-input"
                  className="search-overlay-input"
                  name="q"
                  role="combobox"
                  aria-controls="search-overlay-results"
                  aria-expanded="true"
                  aria-autocomplete="list"
                  onChange={fetchResults}
                  onFocus={fetchResults}
                  placeholder="Search products, collections, and pages"
                  ref={inputRef}
                  type="search"
                  list={queriesDatalistId}
                />
                <button
                  type="button"
                  className="search-overlay-clear"
                  aria-label="Reset search"
                  onClick={() => {
                    if (inputRef.current) {
                      inputRef.current.value = '';
                      inputRef.current.focus();
                    }
                  }}
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
                <button
                  type="button"
                  className="search-overlay-close"
                  onClick={onClose}
                  aria-label="Close search"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="sr-only"
                  onClick={goToSearch}
                  aria-hidden="true"
                  tabIndex={-1}
                >
                  Search
                </button>
              </>
            )}
          </SearchFormPredictive>
        </div>

        <div
          id="search-overlay-results"
          role="listbox"
          aria-label="Search results"
          className="search-overlay-results"
        >
          <SearchResultsPredictive onClose={onClose}>
            {({items, total, term, state, closeSearch}) => {
              const {articles, collections, pages, products, queries} = items;

              if (state === 'loading' && term.current) {
                return (
                  <div className="search-overlay-loading">Searching…</div>
                );
              }

              if (!total) {
                return <SearchResultsPredictive.Empty term={term} />;
              }

              return (
                <>
                  <p className="sr-only" role="status" aria-live="polite">
                    {total} search results found for &quot;{term.current}&quot;
                  </p>
                  <SearchResultsPredictive.Queries
                    queries={queries}
                    queriesDatalistId={queriesDatalistId}
                  />
                  <SearchResultsPredictive.Products
                    products={products}
                    closeSearch={closeSearch}
                    term={term}
                  />
                  <SearchResultsPredictive.Collections
                    collections={collections}
                    closeSearch={closeSearch}
                    term={term}
                  />
                  <SearchResultsPredictive.Pages
                    pages={pages}
                    closeSearch={closeSearch}
                    term={term}
                  />
                  <SearchResultsPredictive.Articles
                    articles={articles}
                    closeSearch={closeSearch}
                    term={term}
                  />
                  {term.current ? (
                    <Link
                      onClick={closeSearch}
                      className="search-overlay-view-all"
                      to={`${SEARCH_ENDPOINT}?q=${encodeURIComponent(term.current)}`}
                    >
                      View all results for <q>{term.current}</q> →
                    </Link>
                  ) : null}
                </>
              );
            }}
          </SearchResultsPredictive>
        </div>
      </div>
    </div>
  );
}

function MobileMenuAside({header}: {header: PageLayoutProps['header']}) {
  return (
    <Aside type="mobile" heading={header?.shop?.name ?? 'Menu'}>
      <MobileNav />
    </Aside>
  );
}
