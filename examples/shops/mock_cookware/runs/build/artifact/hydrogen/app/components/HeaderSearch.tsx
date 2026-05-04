import {useEffect, useRef, useState} from 'react';
import {Link, useFetcher, useLocation} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import {
  SEARCH_ENDPOINT,
  SearchFormPredictive,
} from '~/components/SearchFormPredictive';
import {
  getEmptyPredictiveSearchResult,
  type PredictiveSearchReturn,
} from '~/lib/search';

const SUGGESTED_LINKS: Array<{label: string; url: string}> = [
  {label: 'Best Sellers', url: '/collections/best-sellers'},
  {label: 'Cookware Sets', url: '/collections/cookware-sets'},
  {label: "Chef's Knives", url: '/collections/knives'},
  {label: 'New Arrivals', url: '/collections/new-arrivals'},
];

export function HeaderSearch() {
  const fetcher = useFetcher<PredictiveSearchReturn>({key: 'search'});
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [hasInteracted, setHasInteracted] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setOpen(false);
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const items =
    fetcher?.data?.result?.items ?? getEmptyPredictiveSearchResult().items;
  const total = fetcher?.data?.result?.total ?? 0;
  const term = fetcher?.data?.term ?? '';
  const isLoading = fetcher?.state === 'loading';

  return (
    <div
      className="header-search"
      ref={containerRef}
      onFocus={() => setOpen(true)}
    >
      <SearchFormPredictive
        className="header-search-form"
        onSubmitSearch={() => setOpen(false)}
      >
        {({inputRef, fetchResults, goToSearch}) => (
          <>
            <input
              ref={inputRef}
              name="q"
              type="search"
              placeholder="Search products"
              aria-label="Search products"
              className="header-search-input"
              autoComplete="off"
              onChange={(e) => {
                setHasInteracted(true);
                setOpen(true);
                fetchResults(e);
              }}
              onFocus={(e) => {
                setOpen(true);
                if (e.target.value) {
                  fetchResults(
                    e as unknown as React.ChangeEvent<HTMLInputElement>,
                  );
                }
              }}
            />
            <button
              type="submit"
              className="header-search-submit"
              aria-label="Submit search"
              onClick={() => goToSearch()}
            >
              <svg
                viewBox="0 0 24 24"
                width="18"
                height="18"
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
            </button>
          </>
        )}
      </SearchFormPredictive>

      {open ? (
        <div className="header-search-panel" role="listbox">
          {hasInteracted && term ? (
            <PredictiveResults
              term={term}
              isLoading={isLoading}
              products={items.products?.slice(0, 5) ?? []}
              total={total}
              onClose={() => setOpen(false)}
            />
          ) : (
            <SuggestedPanel onClose={() => setOpen(false)} />
          )}
        </div>
      ) : null}
    </div>
  );
}

function PredictiveResults({
  term,
  isLoading,
  products,
  total,
  onClose,
}: {
  term: string;
  isLoading: boolean;
  products: NonNullable<
    PredictiveSearchReturn['result']['items']['products']
  >;
  total: number;
  onClose: () => void;
}) {
  if (isLoading && !products.length) {
    return (
      <div className="header-search-state">
        <p>Searching “{term}”…</p>
      </div>
    );
  }
  if (!products.length) {
    return (
      <div className="header-search-state">
        <p>
          No products match <strong>“{term}”</strong>.
        </p>
      </div>
    );
  }
  return (
    <>
      <ul className="header-search-results">
        {products.map((product) => {
          const variant = product.selectedOrFirstAvailableVariant;
          const image = variant?.image;
          const price = variant?.price;
          return (
            <li key={product.id} className="header-search-result">
              <Link
                to={`/products/${product.handle}`}
                onClick={onClose}
                prefetch="intent"
                className="header-search-result-link"
              >
                <div className="header-search-result-thumb">
                  {image ? (
                    <Image
                      data={image}
                      alt={image.altText || product.title}
                      width={48}
                      height={48}
                      aspectRatio="1/1"
                      sizes="48px"
                    />
                  ) : (
                    <div
                      className="header-search-result-placeholder"
                      aria-hidden="true"
                    />
                  )}
                </div>
                <div className="header-search-result-meta">
                  <span className="header-search-result-title">
                    {product.title}
                  </span>
                  {price ? (
                    <span className="header-search-result-price">
                      <Money data={price} />
                    </span>
                  ) : null}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
      <Link
        to={`${SEARCH_ENDPOINT}?q=${encodeURIComponent(term)}&type=product`}
        onClick={onClose}
        className="header-search-footer"
      >
        See all results ({total}) →
      </Link>
    </>
  );
}

function SuggestedPanel({onClose}: {onClose: () => void}) {
  return (
    <div className="header-search-suggested">
      <p className="header-search-suggested-label">Suggested</p>
      <ul className="header-search-suggested-list">
        {SUGGESTED_LINKS.map((link) => (
          <li key={link.label}>
            <Link
              to={link.url}
              onClick={onClose}
              prefetch="intent"
              className="header-search-suggested-link"
            >
              {link.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
