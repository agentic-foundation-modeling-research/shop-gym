import {redirect, useLoaderData, useNavigate, useSearchParams} from 'react-router';
import {useEffect, useMemo, useRef, useState} from 'react';
import type {Route} from './+types/collections.$handle';
import {Analytics} from '@shopify/hydrogen';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';
import {ProductItem} from '~/components/ProductItem';
import type {ProductItemFragment} from 'storefrontapi.generated';

export const meta: Route.MetaFunction = ({data}) => {
  return [{title: `Mock Hardware | ${data?.collection.title ?? ''}`}];
};

const SORT_OPTIONS: ReadonlyArray<{value: string; label: string}> = [
  {value: 'manual', label: 'Featured'},
  {value: 'best-selling', label: 'Best selling'},
  {value: 'title-ascending', label: 'Alphabetically, A-Z'},
  {value: 'title-descending', label: 'Alphabetically, Z-A'},
  {value: 'price-ascending', label: 'Price, low to high'},
  {value: 'price-descending', label: 'Price, high to low'},
];

const FILTER_PARAM = 'filter.p.product_type';
const SORT_PARAM = 'sort_by';
const DEFAULT_SORT = 'manual';
const STORE_LABEL = 'MOCK HARDWARE';

export async function loader(args: Route.LoaderArgs) {
  return await loadCriticalData(args);
}

async function loadCriticalData({context, params, request}: Route.LoaderArgs) {
  const {handle} = params;
  const {storefront} = context;

  if (!handle) {
    throw redirect('/collections');
  }

  const [{collection}] = await Promise.all([
    storefront.query(COLLECTION_QUERY, {
      variables: {handle, first: 250},
    }),
  ]);

  if (!collection) {
    throw new Response(`Collection ${handle} not found`, {
      status: 404,
    });
  }

  redirectIfHandleIsLocalized(request, {handle, data: collection});

  return {collection};
}

type Product = ProductItemFragment;

export default function Collection() {
  const {collection} = useLoaderData<typeof loader>();
  const products = collection.products.nodes as Product[];

  const productTypes = useMemo(() => uniqueProductTypes(products), [products]);
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTypes = searchParams.getAll(FILTER_PARAM);
  const sortBy = searchParams.get(SORT_PARAM) ?? DEFAULT_SORT;

  const filtered = useMemo(
    () => filterAndSort(products, activeTypes, sortBy),
    [products, activeTypes.join('|'), sortBy],
  );

  function toggleType(value: string, checked: boolean) {
    const next = new URLSearchParams(searchParams);
    const current = next.getAll(FILTER_PARAM);
    next.delete(FILTER_PARAM);
    const updated = checked
      ? Array.from(new Set([...current, value]))
      : current.filter((v) => v !== value);
    updated.forEach((v) => next.append(FILTER_PARAM, v));
    setSearchParams(next, {replace: true, preventScrollReset: true});
  }

  function setSort(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === DEFAULT_SORT) {
      next.delete(SORT_PARAM);
    } else {
      next.set(SORT_PARAM, value);
    }
    setSearchParams(next, {replace: true, preventScrollReset: true});
  }

  function clearAll() {
    const next = new URLSearchParams(searchParams);
    next.delete(FILTER_PARAM);
    setSearchParams(next, {replace: true, preventScrollReset: true});
  }

  return (
    <div className="collection-page">
      <header className="collection-page-header">
        <p className="collection-page-eyebrow">{STORE_LABEL}</p>
        <h1 className="collection-page-title">{collection.title}</h1>
        {collection.description ? (
          <p className="collection-page-description">{collection.description}</p>
        ) : null}
      </header>

      <div className="collection-layout">
        <aside className="collection-sidebar" aria-label="Product filters">
          <FilterHeader
            count={filtered.length}
            sortBy={sortBy}
            onSortChange={setSort}
          />
          {activeTypes.length > 0 ? (
            <ActiveFilters
              values={activeTypes}
              onRemove={(value) => toggleType(value, false)}
              onClearAll={clearAll}
            />
          ) : null}
          <ProductTypeFilter
            options={productTypes}
            selected={activeTypes}
            onToggle={toggleType}
          />
        </aside>

        <section className="collection-results" aria-label="Products">
          {filtered.length === 0 ? (
            <p className="collection-empty">
              No products match these filters.{' '}
              <button type="button" className="link-btn" onClick={clearAll}>
                Clear filters
              </button>
            </p>
          ) : (
            <div className="products-grid">
              {filtered.map((product, index) => (
                <ProductItem
                  key={product.id}
                  product={product}
                  loading={index < 6 ? 'eager' : undefined}
                />
              ))}
            </div>
          )}
        </section>
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

function FilterHeader({
  count,
  sortBy,
  onSortChange,
}: {
  count: number;
  sortBy: string;
  onSortChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const activeLabel =
    SORT_OPTIONS.find((o) => o.value === sortBy)?.label ??
    SORT_OPTIONS[0].label;

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onClickOutside);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClickOutside);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="collection-filter-header">
      <h2 className="collection-filter-heading">Filters</h2>
      <span className="collection-filter-count">{count} items</span>
      <div className="collection-sort" ref={ref}>
        <button
          type="button"
          className="collection-sort-trigger"
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => setOpen((s) => !s)}
        >
          <span className="collection-sort-label">Sort</span>
          <ChevronIcon open={open} />
        </button>
        {open ? (
          <div className="collection-sort-panel" role="listbox">
            <p className="collection-sort-panel-title">Sort by</p>
            {SORT_OPTIONS.map((option) => (
              <label key={option.value} className="collection-sort-option">
                <input
                  type="radio"
                  name="sort_by"
                  value={option.value}
                  checked={sortBy === option.value}
                  onChange={() => {
                    onSortChange(option.value);
                    setOpen(false);
                  }}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        ) : null}
        <span className="sr-only" aria-live="polite">
          Sorted by {activeLabel}
        </span>
      </div>
    </div>
  );
}

function ProductTypeFilter({
  options,
  selected,
  onToggle,
}: {
  options: string[];
  selected: string[];
  onToggle: (value: string, checked: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(true);

  if (options.length === 0) return null;

  return (
    <div className="filter-group">
      <button
        type="button"
        className="filter-group-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((s) => !s)}
      >
        <span>Product Type</span>
        <ChevronIcon open={expanded} />
      </button>
      {expanded ? (
        <ul className="filter-group-list">
          {options.map((value) => {
            const checked = selected.includes(value);
            return (
              <li key={value} className="filter-option">
                <label className="filter-checkbox">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => onToggle(value, e.target.checked)}
                  />
                  <FilterIcon />
                  <span className="filter-option-label">{value}</span>
                </label>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

function ActiveFilters({
  values,
  onRemove,
  onClearAll,
}: {
  values: string[];
  onRemove: (value: string) => void;
  onClearAll: () => void;
}) {
  return (
    <div className="active-filters">
      <ul className="active-filter-chips">
        {values.map((value) => (
          <li key={value} className="active-filter-chip">
            <span>{value}</span>
            <button
              type="button"
              aria-label={`Remove filter ${value}`}
              onClick={() => onRemove(value)}
              className="active-filter-chip-remove"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <button type="button" className="active-filters-clear" onClick={onClearAll}>
        Clear all
      </button>
    </div>
  );
}

function ChevronIcon({open}: {open: boolean}) {
  return (
    <svg
      className={'chevron-icon ' + (open ? 'is-open' : '')}
      width="12"
      height="12"
      viewBox="0 0 12 12"
      aria-hidden="true"
    >
      <path
        d="M2 4l4 4 4-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function FilterIcon() {
  return (
    <svg
      className="filter-option-icon"
      width="20"
      height="20"
      viewBox="0 0 20 20"
      aria-hidden="true"
    >
      <rect width="20" height="20" rx="4" fill="#f4f6f8" />
      <rect x="4" y="6" width="12" height="2" rx="1" fill="#c3c7ca" />
      <rect x="4" y="10" width="9" height="2" rx="1" fill="#c3c7ca" />
      <rect x="4" y="14" width="6" height="2" rx="1" fill="#c3c7ca" />
    </svg>
  );
}

function uniqueProductTypes(products: Product[]): string[] {
  const set = new Set<string>();
  for (const p of products) {
    const value = (p.productType ?? '').trim();
    if (value) set.add(value);
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b));
}

function filterAndSort(
  products: Product[],
  activeTypes: string[],
  sortBy: string,
): Product[] {
  const filtered =
    activeTypes.length === 0
      ? products.slice()
      : products.filter((p) =>
          activeTypes.includes((p.productType ?? '').trim()),
        );

  switch (sortBy) {
    case 'title-ascending':
      filtered.sort((a, b) => a.title.localeCompare(b.title));
      break;
    case 'title-descending':
      filtered.sort((a, b) => b.title.localeCompare(a.title));
      break;
    case 'price-ascending':
      filtered.sort(
        (a, b) =>
          parsePrice(a.priceRange.minVariantPrice.amount) -
          parsePrice(b.priceRange.minVariantPrice.amount),
      );
      break;
    case 'price-descending':
      filtered.sort(
        (a, b) =>
          parsePrice(b.priceRange.minVariantPrice.amount) -
          parsePrice(a.priceRange.minVariantPrice.amount),
      );
      break;
    case 'best-selling':
    case 'manual':
    default:
      break;
  }
  return filtered;
}

function parsePrice(amount: string | null | undefined): number {
  if (!amount) return 0;
  const n = parseFloat(amount);
  return Number.isFinite(n) ? n : 0;
}

const PRODUCT_ITEM_FRAGMENT = `#graphql
  fragment MoneyProductItem on MoneyV2 {
    amount
    currencyCode
  }
  fragment ProductItem on Product {
    id
    handle
    title
    description
    productType
    availableForSale
    featuredImage {
      id
      altText
      url
      width
      height
    }
    priceRange {
      minVariantPrice {
        ...MoneyProductItem
      }
      maxVariantPrice {
        ...MoneyProductItem
      }
    }
  }
` as const;

const COLLECTION_QUERY = `#graphql
  ${PRODUCT_ITEM_FRAGMENT}
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
          ...ProductItem
        }
      }
    }
  }
` as const;
