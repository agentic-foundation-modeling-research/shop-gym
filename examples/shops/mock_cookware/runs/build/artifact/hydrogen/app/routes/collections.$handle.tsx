import {redirect, useLoaderData, useSearchParams} from 'react-router';
import {useEffect, useMemo, useState} from 'react';
import type {Route} from './+types/collections.$handle';
import {Analytics} from '@shopify/hydrogen';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';
import {ProductItem, type CollectionProduct} from '~/components/ProductItem';

const INITIAL_BATCH = 24;
const MAX_PRODUCTS = 250;

const SORT_OPTIONS = [
  {value: 'manual', label: 'Featured'},
  {value: 'best-selling', label: 'Best Selling'},
  {value: 'title-ascending', label: 'Alphabetically, A–Z'},
  {value: 'title-descending', label: 'Alphabetically, Z–A'},
  {value: 'price-ascending', label: 'Price, low to high'},
  {value: 'price-descending', label: 'Price, high to low'},
  {value: 'created-descending', label: 'Date, new to old'},
  {value: 'created-ascending', label: 'Date, old to new'},
] as const;

type SortValue = (typeof SORT_OPTIONS)[number]['value'];

export const meta: Route.MetaFunction = ({data}) => {
  return [
    {title: `Mock Cookware | ${data?.collection?.title ?? 'Collection'}`},
  ];
};

export async function loader(args: Route.LoaderArgs) {
  const {context, params, request} = args;
  const {handle} = params;
  const {storefront} = context;

  if (!handle) {
    throw redirect('/collections');
  }

  const {collection} = await storefront.query(COLLECTION_QUERY, {
    variables: {handle, first: MAX_PRODUCTS},
  });

  if (!collection) {
    throw new Response(`Collection ${handle} not found`, {status: 404});
  }

  redirectIfHandleIsLocalized(request, {handle, data: collection});

  return {collection};
}

export default function Collection() {
  const {collection} = useLoaderData<typeof loader>();
  const [searchParams, setSearchParams] = useSearchParams();

  const sortBy = (searchParams.get('sort_by') as SortValue) || 'manual';
  const onlyAvailable = searchParams.get('available') === '1';
  const onlyOnSale = searchParams.get('on_sale') === '1';

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const allProducts = (collection.products?.nodes ?? []) as CollectionProduct[];

  const filtered = useMemo(() => {
    let list = allProducts;
    if (onlyAvailable) {
      list = list.filter((p) => p.availableForSale !== false);
    }
    if (onlyOnSale) {
      list = list.filter((p) => isOnSale(p));
    }
    return sortProducts(list, sortBy);
  }, [allProducts, sortBy, onlyAvailable, onlyOnSale]);

  useEffect(() => {
    setExpanded(false);
  }, [sortBy, onlyAvailable, onlyOnSale]);

  const visible = expanded ? filtered : filtered.slice(0, INITIAL_BATCH);
  const hasMore = filtered.length > visible.length;

  const updateParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (value === null || value === '' || value === 'manual') {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    setSearchParams(next, {preventScrollReset: true, replace: true});
  };

  return (
    <div className="collection-page">
      <header className="collection-header section-container">
        <div className="collection-heading">
          <h1 className="collection-title">
            {collection.title}{' '}
            <span className="collection-count">({filtered.length})</span>
          </h1>
          {collection.description ? (
            <p className="collection-description">{collection.description}</p>
          ) : null}
        </div>
        <div className="collection-controls">
          <button
            type="button"
            className={`collection-filter-toggle${
              filtersOpen ? ' is-open' : ''
            }`}
            aria-expanded={filtersOpen}
            aria-controls="collection-filter-panel"
            onClick={() => setFiltersOpen((v) => !v)}
          >
            <FilterIcon />
            Filter
            {(onlyAvailable || onlyOnSale) && (
              <span className="collection-filter-badge">
                {Number(onlyAvailable) + Number(onlyOnSale)}
              </span>
            )}
          </button>
          <label className="collection-sort">
            <span className="collection-sort-label">Sort by</span>
            <select
              className="collection-sort-select"
              value={sortBy}
              onChange={(event) =>
                updateParam('sort_by', event.target.value)
              }
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <div
        id="collection-filter-panel"
        className={`collection-filter-panel section-container${
          filtersOpen ? ' is-open' : ''
        }`}
        hidden={!filtersOpen}
      >
        <fieldset className="collection-filter-fieldset">
          <legend className="collection-filter-legend">Filter products</legend>
          <label className="collection-filter-checkbox">
            <input
              type="checkbox"
              checked={onlyAvailable}
              onChange={(event) =>
                updateParam('available', event.target.checked ? '1' : null)
              }
            />
            <span>Available</span>
          </label>
          <label className="collection-filter-checkbox">
            <input
              type="checkbox"
              checked={onlyOnSale}
              onChange={(event) =>
                updateParam('on_sale', event.target.checked ? '1' : null)
              }
            />
            <span>On Sale</span>
          </label>
          {(onlyAvailable || onlyOnSale) && (
            <button
              type="button"
              className="collection-filter-clear"
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                next.delete('available');
                next.delete('on_sale');
                setSearchParams(next, {
                  preventScrollReset: true,
                  replace: true,
                });
              }}
            >
              Clear filters
            </button>
          )}
        </fieldset>
      </div>

      <div className="section-container">
        {visible.length === 0 ? (
          <div className="collection-empty">
            <p>No products match the current filters.</p>
          </div>
        ) : (
          <div className="collection-grid">
            {visible.map((product, index) => (
              <ProductItem
                key={product.id}
                product={product}
                loading={index < 6 ? 'eager' : 'lazy'}
              />
            ))}
          </div>
        )}

        {hasMore && (
          <div className="collection-load-more-wrap">
            <button
              type="button"
              className="collection-load-more"
              onClick={() => setExpanded(true)}
            >
              Load more ({filtered.length - visible.length} remaining)
            </button>
          </div>
        )}
      </div>

      <Analytics.CollectionView
        data={{
          collection: {
            id: collection.id,
            handle: collection.handle,
          },
        }}
      />
    </div>
  );
}

function isOnSale(product: CollectionProduct): boolean {
  const price = parseFloat(product.priceRange.minVariantPrice.amount);
  const compareAmount = product.compareAtPriceRange?.minVariantPrice?.amount;
  if (!compareAmount) return false;
  const compare = parseFloat(compareAmount);
  return Boolean(compare) && compare > price;
}

function sortProducts(
  products: CollectionProduct[],
  sortBy: SortValue,
): CollectionProduct[] {
  const list = products.slice();
  switch (sortBy) {
    case 'title-ascending':
      return list.sort((a, b) => a.title.localeCompare(b.title));
    case 'title-descending':
      return list.sort((a, b) => b.title.localeCompare(a.title));
    case 'price-ascending':
      return list.sort(
        (a, b) =>
          parseFloat(a.priceRange.minVariantPrice.amount) -
          parseFloat(b.priceRange.minVariantPrice.amount),
      );
    case 'price-descending':
      return list.sort(
        (a, b) =>
          parseFloat(b.priceRange.minVariantPrice.amount) -
          parseFloat(a.priceRange.minVariantPrice.amount),
      );
    case 'created-descending':
      return list.sort(
        (a, b) => Date.parse(b.createdAt ?? '') - Date.parse(a.createdAt ?? ''),
      );
    case 'created-ascending':
      return list.sort(
        (a, b) => Date.parse(a.createdAt ?? '') - Date.parse(b.createdAt ?? ''),
      );
    case 'best-selling':
    case 'manual':
    default:
      return list;
  }
}

function FilterIcon() {
  return (
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
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
      <circle cx="9" cy="6" r="2" fill="var(--color-background)" />
      <circle cx="15" cy="12" r="2" fill="var(--color-background)" />
      <circle cx="8" cy="18" r="2" fill="var(--color-background)" />
    </svg>
  );
}

const COLLECTION_QUERY = `#graphql
  query Collection(
    $handle: String!
    $country: CountryCode
    $language: LanguageCode
    $first: Int
  ) @inContext(country: $country, language: $language) {
    collection(handle: $handle) {
      id
      handle
      title
      description
      products(first: $first) {
        nodes {
          id
          handle
          title
          availableForSale
          createdAt
          tags
          featuredImage {
            id
            altText
            url
            width
            height
          }
          priceRange {
            minVariantPrice {
              amount
              currencyCode
            }
            maxVariantPrice {
              amount
              currencyCode
            }
          }
          compareAtPriceRange {
            minVariantPrice {
              amount
              currencyCode
            }
            maxVariantPrice {
              amount
              currencyCode
            }
          }
        }
      }
    }
  }
` as const;
