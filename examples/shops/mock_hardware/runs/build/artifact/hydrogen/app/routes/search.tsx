import {useEffect, useMemo, useState} from 'react';
import {Link, useLoaderData, useNavigate, useSubmit} from 'react-router';
import {Image, Money, Analytics, getPaginationVariables} from '@shopify/hydrogen';
import type {Route} from './+types/search';
import {
  type RegularSearchReturn,
  type PredictiveSearchReturn,
  urlWithTrackingParams,
  getEmptyPredictiveSearchResult,
} from '~/lib/search';
import type {
  RegularSearchQuery,
  PredictiveSearchQuery,
} from 'storefrontapi.generated';

export const meta: Route.MetaFunction = () => {
  return [{title: `Search`}];
};

export async function loader({request, context}: Route.LoaderArgs) {
  const url = new URL(request.url);
  const isPredictive = url.searchParams.has('predictive');
  const searchPromise: Promise<PredictiveSearchReturn | RegularSearchReturn> =
    isPredictive
      ? predictiveSearch({request, context})
      : regularSearch({request, context});

  searchPromise.catch((error: Error) => {
    console.error(error);
    return {term: '', result: null, error: error.message};
  });

  return await searchPromise;
}

export default function SearchPage() {
  const data = useLoaderData<typeof loader>();
  if (data.type === 'predictive') return null;
  const {term, result, error} = data;
  const submit = useSubmit();
  const navigate = useNavigate();

  const products = result?.items.products?.nodes ?? [];
  const pages = result?.items.pages?.nodes ?? [];
  const articles = result?.items.articles?.nodes ?? [];

  const productTypes = useMemo(() => {
    const counts = new Map<string, number>();
    products.forEach((p) => {
      const type = p.vendor || 'Other';
      counts.set(type, (counts.get(type) || 0) + 1);
    });
    return Array.from(counts.entries()).map(([label, count]) => ({label, count}));
  }, [products]);

  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set());
  const [sortOpen, setSortOpen] = useState(false);
  const [sortBy, setSortBy] = useState<'relevance' | 'price-asc' | 'price-desc'>(
    'relevance',
  );

  const sortedProducts = useMemo(() => {
    let list = products;
    if (selectedTypes.size > 0) {
      list = list.filter((p) => selectedTypes.has(p.vendor || 'Other'));
    }
    if (sortBy === 'price-asc' || sortBy === 'price-desc') {
      const dir = sortBy === 'price-asc' ? 1 : -1;
      list = [...list].sort((a, b) => {
        const ap = parseFloat(
          a.selectedOrFirstAvailableVariant?.price?.amount ?? '0',
        );
        const bp = parseFloat(
          b.selectedOrFirstAvailableVariant?.price?.amount ?? '0',
        );
        return (ap - bp) * dir;
      });
    }
    return list;
  }, [products, selectedTypes, sortBy]);

  function toggleType(type: string) {
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  function clearQuery() {
    void navigate('/search');
  }

  function onFormSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit(event.currentTarget);
  }

  return (
    <div className="search-page">
      <div className="search-page-inner">
        <form
          method="get"
          action="/search"
          className="search-page-form"
          onSubmit={onFormSubmit}
        >
          <input
            type="search"
            name="q"
            defaultValue={term}
            placeholder="Search"
            className="search-page-input"
            aria-label="Search"
          />
          {term ? (
            <button
              type="button"
              className="search-page-input-clear"
              onClick={clearQuery}
              aria-label="Clear search"
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
          ) : null}
          <input type="hidden" name="options[prefix]" value="last" />
          <input type="hidden" name="type" value="product,page" />
        </form>

        {error ? <p className="search-page-error">{error}</p> : null}

        {!term ? (
          <p className="search-page-prompt">
            Enter a search term to find products, pages, and articles.
          </p>
        ) : !result?.total ? (
          <p className="search-page-empty">
            No results found for <q>{term}</q>. Try a different search.
          </p>
        ) : (
          <div className="search-page-layout">
            <aside className="search-page-sidebar" aria-label="Filters">
              <h4 className="search-page-sidebar-heading">Filters</h4>
              <p className="search-page-count">{sortedProducts.length} items</p>

              <div className="search-page-sort">
                <button
                  type="button"
                  className="search-page-sort-toggle"
                  aria-expanded={sortOpen}
                  onClick={() => setSortOpen((o) => !o)}
                >
                  <span>Sort</span>
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>
                {sortOpen ? (
                  <ul className="search-page-sort-options" role="radiogroup">
                    {(
                      [
                        ['relevance', 'Relevance'],
                        ['price-asc', 'Price: Low to High'],
                        ['price-desc', 'Price: High to Low'],
                      ] as const
                    ).map(([value, label]) => (
                      <li key={value}>
                        <label className="search-page-sort-option">
                          <input
                            type="radio"
                            name="sort"
                            value={value}
                            checked={sortBy === value}
                            onChange={() => setSortBy(value)}
                          />
                          <span>{label}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>

              {productTypes.length > 0 ? (
                <details className="search-page-filter-group" open>
                  <summary className="search-page-filter-summary">
                    <span>Product Type</span>
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </summary>
                  <ul className="search-page-filter-options">
                    {productTypes.map((type) => (
                      <li key={type.label}>
                        <label className="search-page-filter-option">
                          <input
                            type="checkbox"
                            checked={selectedTypes.has(type.label)}
                            onChange={() => toggleType(type.label)}
                          />
                          <span className="search-page-filter-label">
                            {type.label}
                          </span>
                          <span className="search-page-filter-count">
                            ({type.count})
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </aside>

            <div className="search-page-main">
              <ul className="search-page-grid" role="list">
                {sortedProducts.map((product) => {
                  const productUrl = urlWithTrackingParams({
                    baseUrl: `/products/${product.handle}`,
                    trackingParams: product.trackingParameters,
                    term,
                  });
                  const variant = product?.selectedOrFirstAvailableVariant;
                  const image = variant?.image;
                  const price = variant?.price;
                  return (
                    <li className="search-product-card" key={product.id}>
                      <Link
                        prefetch="intent"
                        to={productUrl}
                        className="search-product-card-link"
                      >
                        <div className="search-product-card-image">
                          {image ? (
                            <Image
                              data={image}
                              alt={image.altText ?? product.title}
                              aspectRatio="1/1"
                              width={400}
                            />
                          ) : (
                            <div
                              className="search-product-card-placeholder"
                              aria-hidden="true"
                            >
                              <svg
                                width="48"
                                height="48"
                                viewBox="0 0 48 48"
                                fill="none"
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
                                <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
                              </svg>
                            </div>
                          )}
                        </div>
                        <h5 className="search-product-card-title">
                          {product.title}
                        </h5>
                        {product.vendor ? (
                          <p className="search-product-card-vendor">
                            {product.vendor}
                          </p>
                        ) : null}
                        <p className="search-product-card-price">
                          {price ? <Money data={price} /> : null}
                        </p>
                      </Link>
                    </li>
                  );
                })}
              </ul>

              {pages.length > 0 ? (
                <section className="search-page-section">
                  <h3 className="search-page-section-heading">Pages</h3>
                  <ul className="search-page-link-list">
                    {pages.map((page) => (
                      <li key={page.id}>
                        <Link
                          to={`/pages/${page.handle}`}
                          className="search-page-link"
                          prefetch="intent"
                        >
                          {page.title}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {articles.length > 0 ? (
                <section className="search-page-section">
                  <h3 className="search-page-section-heading">Articles</h3>
                  <ul className="search-page-link-list">
                    {articles.map((article) => (
                      <li key={article.id}>
                        <Link
                          to={`/blogs/${article.handle}`}
                          className="search-page-link"
                          prefetch="intent"
                        >
                          {article.title}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>
          </div>
        )}
      </div>

      <Analytics.SearchView data={{searchTerm: term, searchResults: result}} />
    </div>
  );
}

const SEARCH_PRODUCT_FRAGMENT = `#graphql
  fragment SearchProduct on Product {
    __typename
    handle
    id
    publishedAt
    title
    trackingParameters
    vendor
    selectedOrFirstAvailableVariant(
      selectedOptions: []
      ignoreUnknownOptions: true
      caseInsensitiveMatch: true
    ) {
      id
      image {
        url
        altText
        width
        height
      }
      price {
        amount
        currencyCode
      }
      compareAtPrice {
        amount
        currencyCode
      }
      selectedOptions {
        name
        value
      }
      product {
        handle
        title
      }
    }
  }
` as const;

const SEARCH_PAGE_FRAGMENT = `#graphql
  fragment SearchPage on Page {
     __typename
     handle
    id
    title
    trackingParameters
  }
` as const;

const SEARCH_ARTICLE_FRAGMENT = `#graphql
  fragment SearchArticle on Article {
    __typename
    handle
    id
    title
    trackingParameters
  }
` as const;

const PAGE_INFO_FRAGMENT = `#graphql
  fragment PageInfoFragment on PageInfo {
    hasNextPage
    hasPreviousPage
    startCursor
    endCursor
  }
` as const;

export const SEARCH_QUERY = `#graphql
  query RegularSearch(
    $country: CountryCode
    $endCursor: String
    $first: Int
    $language: LanguageCode
    $last: Int
    $term: String!
    $startCursor: String
  ) @inContext(country: $country, language: $language) {
    articles: search(
      query: $term,
      types: [ARTICLE],
      first: $first,
    ) {
      nodes {
        ...on Article {
          ...SearchArticle
        }
      }
    }
    pages: search(
      query: $term,
      types: [PAGE],
      first: $first,
    ) {
      nodes {
        ...on Page {
          ...SearchPage
        }
      }
    }
    products: search(
      after: $endCursor,
      before: $startCursor,
      first: $first,
      last: $last,
      query: $term,
      sortKey: RELEVANCE,
      types: [PRODUCT],
      unavailableProducts: HIDE,
    ) {
      nodes {
        ...on Product {
          ...SearchProduct
        }
      }
      pageInfo {
        ...PageInfoFragment
      }
    }
  }
  ${SEARCH_PRODUCT_FRAGMENT}
  ${SEARCH_PAGE_FRAGMENT}
  ${SEARCH_ARTICLE_FRAGMENT}
  ${PAGE_INFO_FRAGMENT}
` as const;

async function regularSearch({
  request,
  context,
}: Pick<
  Route.LoaderArgs,
  'request' | 'context'
>): Promise<RegularSearchReturn> {
  const {storefront} = context;
  const url = new URL(request.url);
  const variables = getPaginationVariables(request, {pageBy: 24});
  const term = String(url.searchParams.get('q') || '');

  if (!term) {
    return {
      type: 'regular',
      term: '',
      result: {
        total: 0,
        items: {
          articles: {nodes: []},
          pages: {nodes: []},
          products: {
            nodes: [],
            pageInfo: {
              hasNextPage: false,
              hasPreviousPage: false,
              startCursor: null,
              endCursor: null,
            },
          },
        },
      },
    };
  }

  const {
    errors,
    ...items
  }: {errors?: Array<{message: string}>} & RegularSearchQuery =
    await storefront.query(SEARCH_QUERY, {
      variables: {...variables, term},
    });

  if (!items) {
    throw new Error('No search data returned from Shopify API');
  }

  const total = Object.values(items).reduce(
    (acc: number, {nodes}: {nodes: Array<unknown>}) => acc + nodes.length,
    0,
  );

  const error = errors
    ? errors.map(({message}: {message: string}) => message).join(', ')
    : undefined;

  return {type: 'regular', term, error, result: {total, items}};
}

const PREDICTIVE_SEARCH_ARTICLE_FRAGMENT = `#graphql
  fragment PredictiveArticle on Article {
    __typename
    id
    title
    handle
    blog {
      handle
    }
    image {
      url
      altText
      width
      height
    }
    trackingParameters
  }
` as const;

const PREDICTIVE_SEARCH_COLLECTION_FRAGMENT = `#graphql
  fragment PredictiveCollection on Collection {
    __typename
    id
    title
    handle
    image {
      url
      altText
      width
      height
    }
    trackingParameters
  }
` as const;

const PREDICTIVE_SEARCH_PAGE_FRAGMENT = `#graphql
  fragment PredictivePage on Page {
    __typename
    id
    title
    handle
    trackingParameters
  }
` as const;

const PREDICTIVE_SEARCH_PRODUCT_FRAGMENT = `#graphql
  fragment PredictiveProduct on Product {
    __typename
    id
    title
    handle
    trackingParameters
    selectedOrFirstAvailableVariant(
      selectedOptions: []
      ignoreUnknownOptions: true
      caseInsensitiveMatch: true
    ) {
      id
      image {
        url
        altText
        width
        height
      }
      price {
        amount
        currencyCode
      }
    }
  }
` as const;

const PREDICTIVE_SEARCH_QUERY_FRAGMENT = `#graphql
  fragment PredictiveQuery on SearchQuerySuggestion {
    __typename
    text
    styledText
    trackingParameters
  }
` as const;

const PREDICTIVE_SEARCH_QUERY = `#graphql
  query PredictiveSearch(
    $country: CountryCode
    $language: LanguageCode
    $limit: Int!
    $limitScope: PredictiveSearchLimitScope!
    $term: String!
    $types: [PredictiveSearchType!]
  ) @inContext(country: $country, language: $language) {
    predictiveSearch(
      limit: $limit,
      limitScope: $limitScope,
      query: $term,
      types: $types,
    ) {
      articles {
        ...PredictiveArticle
      }
      collections {
        ...PredictiveCollection
      }
      pages {
        ...PredictivePage
      }
      products {
        ...PredictiveProduct
      }
      queries {
        ...PredictiveQuery
      }
    }
  }
  ${PREDICTIVE_SEARCH_ARTICLE_FRAGMENT}
  ${PREDICTIVE_SEARCH_COLLECTION_FRAGMENT}
  ${PREDICTIVE_SEARCH_PAGE_FRAGMENT}
  ${PREDICTIVE_SEARCH_PRODUCT_FRAGMENT}
  ${PREDICTIVE_SEARCH_QUERY_FRAGMENT}
` as const;

async function predictiveSearch({
  request,
  context,
}: Pick<
  Route.ActionArgs,
  'request' | 'context'
>): Promise<PredictiveSearchReturn> {
  const {storefront} = context;
  const url = new URL(request.url);
  const term = String(url.searchParams.get('q') || '').trim();
  const limit = Number(url.searchParams.get('limit') || 10);
  const type = 'predictive';

  if (!term) return {type, term, result: getEmptyPredictiveSearchResult()};

  const {
    predictiveSearch: items,
    errors,
  }: PredictiveSearchQuery & {errors?: Array<{message: string}>} =
    await storefront.query(PREDICTIVE_SEARCH_QUERY, {
      variables: {
        limit,
        limitScope: 'EACH',
        term,
      },
    });

  if (errors) {
    throw new Error(
      `Shopify API errors: ${errors.map(({message}: {message: string}) => message).join(', ')}`,
    );
  }

  if (!items) {
    throw new Error('No predictive search data returned from Shopify API');
  }

  const total = Object.values(items).reduce(
    (acc: number, item: Array<unknown>) => acc + item.length,
    0,
  );

  return {type, term, result: {items, total}};
}
