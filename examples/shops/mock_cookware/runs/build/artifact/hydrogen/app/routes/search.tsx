import {Link, useLoaderData} from 'react-router';
import type {Route} from './+types/search';
import {Image, Money, Analytics} from '@shopify/hydrogen';
import {
  SEARCH_ENDPOINT,
  SearchFormPredictive,
} from '~/components/SearchFormPredictive';
import {
  type RegularSearchReturn,
  type PredictiveSearchReturn,
  getEmptyPredictiveSearchResult,
} from '~/lib/search';
import type {
  RegularSearchQuery,
  PredictiveSearchQuery,
} from 'storefrontapi.generated';

export const meta: Route.MetaFunction = ({data}) => {
  const term = (data as Awaited<ReturnType<typeof loader>> | undefined)?.term;
  return [
    {
      title: term
        ? `Search: ${term} · Mock Cookware`
        : 'Search · Mock Cookware',
    },
  ];
};

export async function loader({request, context}: Route.LoaderArgs) {
  const url = new URL(request.url);
  const isPredictive = url.searchParams.has('predictive');

  if (isPredictive) {
    return await predictiveSearch({request, context});
  }
  return await regularSearch({request, context});
}

export default function SearchPage() {
  const data = useLoaderData<typeof loader>();
  if (data.type === 'predictive') return null;

  const {term, result, error} = data as RegularSearchReturn;
  const products = result?.items?.products?.nodes ?? [];

  return (
    <div className="search-page">
      <div className="search-page-inner">
        <header className="search-page-header">
          <h1 className="search-page-title">Search Results</h1>
          <SearchFormPredictive className="search-page-form">
            {({inputRef, goToSearch}) => (
              <>
                <input
                  ref={inputRef}
                  defaultValue={term}
                  name="q"
                  type="search"
                  placeholder="Search products"
                  aria-label="Search products"
                  className="search-page-input"
                />
                <button
                  type="submit"
                  className="search-page-submit"
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
          {term ? (
            <p className="search-page-meta">
              {products.length} result
              {products.length === 1 ? '' : 's'} for{' '}
              <strong>“{term}”</strong>
            </p>
          ) : (
            <p className="search-page-meta">Search our catalog by product name.</p>
          )}
          {error ? <p className="search-page-error">{error}</p> : null}
        </header>

        {term && products.length === 0 ? (
          <div className="search-page-empty">
            <p>
              No products match <strong>“{term}”</strong>. Try a different
              keyword.
            </p>
            <Link
              to="/collections/all"
              prefetch="intent"
              className="search-page-empty-cta"
            >
              Browse all products →
            </Link>
          </div>
        ) : null}

        {products.length > 0 ? (
          <ul className="search-page-grid">
            {products.map((product) => {
              const variant = product.selectedOrFirstAvailableVariant;
              const image = variant?.image;
              const price = variant?.price;
              const compareAt = variant?.compareAtPrice;
              const onSale =
                compareAt &&
                price &&
                parseFloat(compareAt.amount) > parseFloat(price.amount);

              return (
                <li key={product.id} className="search-page-card">
                  <Link
                    to={`/products/${product.handle}`}
                    prefetch="intent"
                    className="search-page-card-link"
                  >
                    <div className="search-page-card-media">
                      {image ? (
                        <Image
                          data={image}
                          alt={image.altText || product.title}
                          aspectRatio="4/5"
                          sizes="(min-width: 900px) 30vw, 45vw"
                        />
                      ) : (
                        <div
                          className="search-page-card-placeholder"
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
                      {onSale ? (
                        <span className="search-page-card-badge">Sale</span>
                      ) : null}
                    </div>
                    <div className="search-page-card-meta">
                      <h3 className="search-page-card-title">
                        {product.title}
                      </h3>
                      <div className="search-page-card-price">
                        {compareAt && onSale ? (
                          <s>
                            <Money data={compareAt} />
                          </s>
                        ) : null}
                        {price ? <Money data={price} /> : null}
                      </div>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
      <Analytics.SearchView
        data={{searchTerm: term, searchResults: result}}
      />
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
  const term = String(url.searchParams.get('q') || '').trim();

  if (!term) {
    return {
      type: 'regular',
      term,
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
        } as unknown as RegularSearchQuery,
      },
    };
  }

  const variables = {first: 60};

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
  const limit = Number(url.searchParams.get('limit') || 5);
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
    return {type, term, result: getEmptyPredictiveSearchResult()};
  }

  const total = Object.values(items).reduce(
    (acc: number, item: Array<unknown>) => acc + item.length,
    0,
  );

  return {type, term, result: {items, total}};
}
