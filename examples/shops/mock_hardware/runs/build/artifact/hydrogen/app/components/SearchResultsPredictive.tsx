import {Link, useFetcher, type Fetcher} from 'react-router';
import {Image, Money} from '@shopify/hydrogen';
import {useRef, useEffect} from 'react';
import type React from 'react';
import {
  getEmptyPredictiveSearchResult,
  urlWithTrackingParams,
  type PredictiveSearchReturn,
} from '~/lib/search';

type PredictiveSearchItems = PredictiveSearchReturn['result']['items'];

type UsePredictiveSearchReturn = {
  term: React.RefObject<string>;
  total: number;
  inputRef: React.RefObject<HTMLInputElement | null>;
  items: PredictiveSearchItems;
  fetcher: Fetcher<PredictiveSearchReturn>;
};

type SearchResultsPredictiveArgs = Pick<
  UsePredictiveSearchReturn,
  'term' | 'total' | 'inputRef' | 'items'
> & {
  state: Fetcher['state'];
  closeSearch: () => void;
};

type PartialPredictiveSearchResult<
  ItemType extends keyof PredictiveSearchItems,
  ExtraProps extends keyof SearchResultsPredictiveArgs = 'term' | 'closeSearch',
> = Pick<PredictiveSearchItems, ItemType> &
  Pick<SearchResultsPredictiveArgs, ExtraProps>;

type SearchResultsPredictiveProps = {
  children: (args: SearchResultsPredictiveArgs) => React.ReactNode;
  onClose?: () => void;
};

export function SearchResultsPredictive({
  children,
  onClose,
}: SearchResultsPredictiveProps) {
  const {term, inputRef, fetcher, total, items} = usePredictiveSearch();

  function resetInput() {
    if (inputRef.current) {
      inputRef.current.blur();
      inputRef.current.value = '';
    }
  }

  function closeSearch() {
    resetInput();
    onClose?.();
  }

  return children({
    items,
    closeSearch,
    inputRef,
    state: fetcher.state,
    term,
    total,
  });
}

SearchResultsPredictive.Articles = SearchResultsPredictiveArticles;
SearchResultsPredictive.Collections = SearchResultsPredictiveCollections;
SearchResultsPredictive.Pages = SearchResultsPredictivePages;
SearchResultsPredictive.Products = SearchResultsPredictiveProducts;
SearchResultsPredictive.Queries = SearchResultsPredictiveQueries;
SearchResultsPredictive.Empty = SearchResultsPredictiveEmpty;

function SearchResultsPredictiveArticles({
  term,
  articles,
  closeSearch,
}: PartialPredictiveSearchResult<'articles'>) {
  if (!articles.length) return null;

  return (
    <div className="predictive-search-section" role="group" aria-label="Articles">
      <h3 className="predictive-search-section-title">Articles</h3>
      <ul className="predictive-search-list">
        {articles.map((article) => {
          const articleUrl = urlWithTrackingParams({
            baseUrl: `/blogs/${article.blog.handle}/${article.handle}`,
            trackingParams: article.trackingParameters,
            term: term.current ?? '',
          });

          return (
            <li className="predictive-search-item" key={article.id}>
              <Link onClick={closeSearch} to={articleUrl} className="predictive-search-link">
                <span className="predictive-search-link-title">{article.title}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SearchResultsPredictiveCollections({
  term,
  collections,
  closeSearch,
}: PartialPredictiveSearchResult<'collections'>) {
  if (!collections.length) return null;

  return (
    <div className="predictive-search-section" role="group" aria-label="Collections">
      <h3 className="predictive-search-section-title">Collections</h3>
      <ul className="predictive-search-list">
        {collections.map((collection) => {
          const collectionUrl = urlWithTrackingParams({
            baseUrl: `/collections/${collection.handle}`,
            trackingParams: collection.trackingParameters,
            term: term.current,
          });

          return (
            <li className="predictive-search-item" key={collection.id}>
              <Link onClick={closeSearch} to={collectionUrl} className="predictive-search-link">
                <span className="predictive-search-link-title">{collection.title}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SearchResultsPredictivePages({
  term,
  pages,
  closeSearch,
}: PartialPredictiveSearchResult<'pages'>) {
  if (!pages.length) return null;

  return (
    <div className="predictive-search-section" role="group" aria-label="Pages">
      <h3 className="predictive-search-section-title">Pages</h3>
      <ul className="predictive-search-list">
        {pages.map((page) => {
          const pageUrl = urlWithTrackingParams({
            baseUrl: `/pages/${page.handle}`,
            trackingParams: page.trackingParameters,
            term: term.current,
          });

          return (
            <li className="predictive-search-item" key={page.id}>
              <Link onClick={closeSearch} to={pageUrl} className="predictive-search-link">
                <span className="predictive-search-link-title">{page.title}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SearchResultsPredictiveProducts({
  term,
  products,
  closeSearch,
}: PartialPredictiveSearchResult<'products'>) {
  if (!products.length) return null;

  return (
    <div className="predictive-search-section" role="group" aria-label="Products">
      <h3 className="predictive-search-section-title">Products</h3>
      <ul className="predictive-search-products">
        {products.map((product) => {
          const productUrl = urlWithTrackingParams({
            baseUrl: `/products/${product.handle}`,
            trackingParams: product.trackingParameters,
            term: term.current,
          });

          const price = product?.selectedOrFirstAvailableVariant?.price;
          const image = product?.selectedOrFirstAvailableVariant?.image;
          return (
            <li className="predictive-search-product" key={product.id}>
              <Link
                to={productUrl}
                onClick={closeSearch}
                className="predictive-search-product-link"
              >
                <div className="predictive-search-product-image">
                  {image ? (
                    <Image
                      alt={image.altText ?? product.title}
                      src={image.url}
                      width={120}
                      height={120}
                      aspectRatio="1/1"
                    />
                  ) : (
                    <div className="predictive-search-product-placeholder" aria-hidden="true">
                      <svg width="32" height="32" viewBox="0 0 48 48" fill="none">
                        <rect width="48" height="48" rx="4" fill="#f0ede8" />
                        <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
                        <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
                      </svg>
                    </div>
                  )}
                </div>
                <div className="predictive-search-product-meta">
                  <p className="predictive-search-product-title">
                    {product.title}
                  </p>
                  <span className="predictive-search-product-price">
                    {price && <Money data={price} />}
                  </span>
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SearchResultsPredictiveQueries({
  queries,
  queriesDatalistId,
}: PartialPredictiveSearchResult<'queries', never> & {
  queriesDatalistId: string;
}) {
  if (!queries.length) return null;

  return (
    <datalist id={queriesDatalistId}>
      {queries.map((suggestion) => {
        if (!suggestion) return null;
        return <option key={suggestion.text} value={suggestion.text} />;
      })}
    </datalist>
  );
}

function SearchResultsPredictiveEmpty({
  term,
}: {
  term: React.RefObject<string>;
}) {
  if (!term.current) {
    return (
      <p className="predictive-search-empty">
        Start typing to search products, collections, and pages.
      </p>
    );
  }

  return (
    <p className="predictive-search-empty">
      No results found for <q>{term.current}</q>
    </p>
  );
}

function usePredictiveSearch(): UsePredictiveSearchReturn {
  const fetcher = useFetcher<PredictiveSearchReturn>({key: 'search'});
  const term = useRef<string>('');
  const inputRef = useRef<HTMLInputElement | null>(null);

  if (fetcher?.state === 'loading') {
    term.current = String(fetcher.formData?.get('q') || '');
  }

  useEffect(() => {
    if (!inputRef.current) {
      inputRef.current = document.querySelector('input[type="search"]');
    }
  }, []);

  const {items, total} =
    fetcher?.data?.result ?? getEmptyPredictiveSearchResult();

  return {items, total, inputRef, term, fetcher};
}
