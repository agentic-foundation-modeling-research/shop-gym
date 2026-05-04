import {useMemo} from 'react';
import {Link, useLoaderData, useSearchParams} from 'react-router';
import type {Route} from './+types/search';
import {Analytics} from '@shopify/hydrogen';
import {ProductItem, type ProductItemRich} from '~/components/ProductItem';
import {
  SortDropdown,
  isSortKey,
  type SortKey,
} from '~/components/SortDropdown';
import {
  type RegularSearchReturn,
  type PredictiveSearchReturn,
  getEmptyPredictiveSearchResult,
} from '~/lib/search';
import type {PredictiveSearchQuery} from 'storefrontapi.generated';

const PAGE_SIZE = 24;

export const meta: Route.MetaFunction = ({data}) => {
  const term =
    data && 'term' in data ? (data.term as string | undefined) : undefined;
  return [{title: term ? `Search results for "${term}"` : 'Search'}];
};

type RegularSearchProductsNode = {
  id: string;
  handle: string;
  title: string;
  productType?: string | null;
  tags?: string[] | null;
  featuredImage?: {
    id?: string | null;
    url: string;
    altText?: string | null;
    width?: number | null;
    height?: number | null;
  } | null;
  priceRange: {
    minVariantPrice: {amount: string; currencyCode: string};
    maxVariantPrice: {amount: string; currencyCode: string};
  };
  compareAtPriceRange?: {
    minVariantPrice?: {amount: string; currencyCode: string} | null;
    maxVariantPrice?: {amount: string; currencyCode: string} | null;
  } | null;
  options?: Array<{name: string; values: string[]}>;
  trackingParameters?: string | null;
};

type RegularSearchResponse = {
  products: {nodes: RegularSearchProductsNode[]};
};

export async function loader({request, context}: Route.LoaderArgs) {
  const url = new URL(request.url);
  const isPredictive = url.searchParams.has('predictive');

  if (isPredictive) {
    return await predictiveSearch({request, context});
  }
  return await regularSearch({request, context});
}

const TOP_CATEGORIES: Array<{
  title: string;
  handle: string;
  background: string;
}> = [
  {
    title: 'Best Sellers',
    handle: 'best-sellers',
    background: 'linear-gradient(135deg, #efe6d6 0%, #c5a47e 100%)',
  },
  {
    title: 'New Arrivals',
    handle: 'new-arrivals',
    background: 'linear-gradient(135deg, #d8c4a8 0%, #a48560 100%)',
  },
  {
    title: 'Sale',
    handle: 'sale',
    background: 'linear-gradient(135deg, #2a201c 0%, #6e553f 100%)',
  },
  {
    title: 'Gifting Edit',
    handle: 'gifting-edit',
    background: 'linear-gradient(135deg, #c5a47e 0%, #6e553f 100%)',
  },
];

export default function SearchPage() {
  const data = useLoaderData<typeof loader>();
  if (data.type === 'predictive') return null;
  return <RegularSearchPage data={data} />;
}

function RegularSearchPage({data}: {data: RegularSearchReturn}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const {term, result, error} = data;
  const products = (result?.items?.products?.nodes ?? []) as unknown as ProductItemRich[];

  const currentSort: SortKey = useMemo(() => {
    const raw = searchParams.get('sort');
    return raw && isSortKey(raw) ? raw : 'trending';
  }, [searchParams]);

  const filtered = useMemo(
    () => applyFilters(products, searchParams),
    [products, searchParams],
  );

  const sorted = useMemo(
    () => applySort(filtered, currentSort),
    [filtered, currentSort],
  );

  const facets = useMemo(() => deriveFacets(products), [products]);

  const visible = sorted.slice(0, PAGE_SIZE);

  function changeSort(sort: SortKey) {
    const params = new URLSearchParams(searchParams);
    if (sort === 'trending') params.delete('sort');
    else params.set('sort', sort);
    setSearchParams(params, {preventScrollReset: true});
  }

  function toggleFilter(key: string, value: string) {
    const params = new URLSearchParams(searchParams);
    const current = (params.get(key) ?? '').split(',').filter(Boolean);
    if (current.includes(value)) {
      const next = current.filter((v) => v !== value);
      if (next.length === 0) params.delete(key);
      else params.set(key, next.join(','));
    } else {
      params.set(key, [...current, value].join(','));
    }
    setSearchParams(params, {preventScrollReset: true});
  }

  const totalLabel = term
    ? `${sorted.length} ${sorted.length === 1 ? 'result' : 'results'} for “${term}”`
    : 'Search the store';

  if (!term) {
    return (
      <div className="search-page">
        <header className="search-page-header">
          <h1 className="search-page-heading">Search</h1>
          <p className="search-page-empty-body">
            Enter a search term to find products and collections.
          </p>
        </header>
      </div>
    );
  }

  return (
    <div className="search-page">
      <header className="search-page-header">
        <h1 className="search-page-heading">{totalLabel}</h1>
      </header>

      {error ? (
        <p className="search-page-error" role="alert">
          {error}
        </p>
      ) : null}

      {sorted.length === 0 ? (
        <NoResults term={term} />
      ) : (
        <>
          <div className="search-page-toolbar">
            <SearchFilterBar
              facets={facets}
              params={searchParams}
              onToggle={toggleFilter}
            />
            <SortDropdown value={currentSort} onChange={changeSort} />
          </div>

          <div className="search-page-grid">
            {visible.map((product, i) => (
              <ProductItem
                key={product.id}
                product={product}
                loading={i < 8 ? 'eager' : 'lazy'}
              />
            ))}
          </div>

          {sorted.length > PAGE_SIZE ? (
            <p className="search-page-grid-footer">
              Showing {visible.length} of {sorted.length} results
            </p>
          ) : null}
        </>
      )}

      <Analytics.SearchView
        data={{searchTerm: term, searchResults: result}}
      />
    </div>
  );
}

function NoResults({term}: {term: string}) {
  return (
    <div className="search-page-no-results">
      <h2 className="search-page-no-results-heading">
        No results for “{term}”
      </h2>
      <p className="search-page-no-results-body">
        Try a different spelling or browse by category below.
      </p>
      <div className="search-page-category-row">
        {TOP_CATEGORIES.map((cat) => (
          <Link
            key={cat.handle}
            to={`/collections/${cat.handle}`}
            className="search-page-category-tile"
            style={{background: cat.background}}
          >
            <span className="search-page-category-title">{cat.title}</span>
            <span className="search-page-category-cta">Shop now →</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function SearchFilterBar({
  facets,
  params,
  onToggle,
}: {
  facets: ReturnType<typeof deriveFacets>;
  params: URLSearchParams;
  onToggle: (key: string, value: string) => void;
}) {
  const activeTypes = (params.get('type') ?? '').split(',').filter(Boolean);
  const activeColors = (params.get('color') ?? '').split(',').filter(Boolean);
  const activeSizes = (params.get('size') ?? '').split(',').filter(Boolean);
  const activeMaterials = (params.get('material') ?? '')
    .split(',')
    .filter(Boolean);

  return (
    <div className="search-filter-bar" role="navigation" aria-label="Filters">
      <SearchFilterPill label="All" active={false} disabled />
      <SearchFilterDropdown
        label="Category"
        options={facets.productTypes}
        active={activeTypes}
        onToggle={(v) => onToggle('type', v)}
      />
      <SearchFilterDropdown
        label="Size"
        options={facets.sizes}
        active={activeSizes}
        onToggle={(v) => onToggle('size', v)}
      />
      <SearchFilterDropdown
        label="Color"
        options={facets.colors}
        active={activeColors}
        onToggle={(v) => onToggle('color', v)}
      />
      <SearchFilterDropdown
        label="Material"
        options={facets.materials}
        active={activeMaterials}
        onToggle={(v) => onToggle('material', v)}
      />
    </div>
  );
}

function SearchFilterPill({
  label,
  active,
  disabled,
}: {
  label: string;
  active: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={`search-filter-pill${active ? ' is-active' : ''}`}
      disabled={disabled}
    >
      {label}
    </button>
  );
}

function SearchFilterDropdown({
  label,
  options,
  active,
  onToggle,
}: {
  label: string;
  options: string[];
  active: string[];
  onToggle: (value: string) => void;
}) {
  if (options.length === 0) return null;
  return (
    <details className="search-filter-dropdown">
      <summary className="search-filter-pill">
        {label}
        {active.length > 0 ? (
          <span className="search-filter-pill-count"> · {active.length}</span>
        ) : null}
      </summary>
      <ul className="search-filter-menu" role="menu">
        {options.map((option) => (
          <li key={option}>
            <label className="search-filter-option">
              <input
                type="checkbox"
                checked={active.includes(option)}
                onChange={() => onToggle(option)}
              />
              <span>{option}</span>
            </label>
          </li>
        ))}
      </ul>
    </details>
  );
}

function deriveFacets(products: ProductItemRich[]): {
  productTypes: string[];
  sizes: string[];
  colors: string[];
  materials: string[];
} {
  const types = new Set<string>();
  const sizes = new Set<string>();
  const colors = new Set<string>();
  const materials = new Set<string>();
  for (const p of products) {
    if (p.productType) types.add(p.productType);
    for (const opt of p.options ?? []) {
      const name = opt.name.toLowerCase();
      if (name === 'size') opt.values.forEach((v) => sizes.add(v));
      if (name === 'color' || name === 'colour') {
        opt.values.forEach((v) => colors.add(v));
      }
      if (name === 'material' || name === 'fabric') {
        opt.values.forEach((v) => materials.add(v));
      }
    }
    for (const tag of p.tags ?? []) {
      if (tag.toLowerCase().startsWith('material:')) {
        materials.add(tag.slice('material:'.length));
      }
    }
  }
  return {
    productTypes: Array.from(types).sort(),
    sizes: Array.from(sizes),
    colors: Array.from(colors).sort(),
    materials: Array.from(materials).sort(),
  };
}

function applyFilters(
  products: ProductItemRich[],
  params: URLSearchParams,
): ProductItemRich[] {
  const types = (params.get('type') ?? '').split(',').filter(Boolean);
  const sizes = (params.get('size') ?? '').split(',').filter(Boolean);
  const colors = (params.get('color') ?? '').split(',').filter(Boolean);
  const materials = (params.get('material') ?? '').split(',').filter(Boolean);

  return products.filter((p) => {
    if (types.length && !(p.productType && types.includes(p.productType))) {
      return false;
    }
    if (sizes.length) {
      const sizeOpt = p.options?.find((o) => o.name.toLowerCase() === 'size');
      if (!sizeOpt || !sizeOpt.values.some((v) => sizes.includes(v))) {
        return false;
      }
    }
    if (colors.length) {
      const colorOpt = p.options?.find(
        (o) =>
          o.name.toLowerCase() === 'color' || o.name.toLowerCase() === 'colour',
      );
      if (!colorOpt || !colorOpt.values.some((v) => colors.includes(v))) {
        return false;
      }
    }
    if (materials.length) {
      const matOpt = p.options?.find(
        (o) =>
          o.name.toLowerCase() === 'material' ||
          o.name.toLowerCase() === 'fabric',
      );
      const tagMatch = (p.tags ?? []).some((t) =>
        materials.some((m) => t.toLowerCase().includes(m.toLowerCase())),
      );
      const optMatch = matOpt
        ? matOpt.values.some((v) => materials.includes(v))
        : false;
      if (!optMatch && !tagMatch) return false;
    }
    return true;
  });
}

function applySort(
  products: ProductItemRich[],
  sort: SortKey,
): ProductItemRich[] {
  const arr = [...products];
  switch (sort) {
    case 'price-asc':
      arr.sort(
        (a, b) =>
          parseFloat(a.priceRange.minVariantPrice.amount) -
          parseFloat(b.priceRange.minVariantPrice.amount),
      );
      break;
    case 'price-desc':
      arr.sort(
        (a, b) =>
          parseFloat(b.priceRange.minVariantPrice.amount) -
          parseFloat(a.priceRange.minVariantPrice.amount),
      );
      break;
    case 'discount-desc':
      arr.sort((a, b) => discountPct(b) - discountPct(a));
      break;
    case 'new':
    case 'trending':
    default:
      break;
  }
  return arr;
}

function discountPct(p: ProductItemRich): number {
  const c = p.compareAtPriceRange?.minVariantPrice;
  if (!c) return 0;
  const compare = parseFloat(c.amount);
  const price = parseFloat(p.priceRange.minVariantPrice.amount);
  if (!compare || compare <= price) return 0;
  return 1 - price / compare;
}

const SEARCH_QUERY = `#graphql
  query RegularSearch(
    $term: String!
    $first: Int
    $country: CountryCode
    $language: LanguageCode
  ) @inContext(country: $country, language: $language) {
    products: search(
      first: $first,
      query: $term,
      sortKey: RELEVANCE,
      types: [PRODUCT],
      unavailableProducts: HIDE,
    ) {
      nodes {
        ... on Product {
          id
          handle
          title
          productType
          tags
          trackingParameters
          featuredImage {
            id
            altText
            url
            width
            height
          }
          priceRange {
            minVariantPrice { amount currencyCode }
            maxVariantPrice { amount currencyCode }
          }
          compareAtPriceRange {
            minVariantPrice { amount currencyCode }
            maxVariantPrice { amount currencyCode }
          }
          options {
            name
            values
          }
        }
      }
    }
  }
` as const;

async function regularSearch({
  request,
  context,
}: Pick<Route.LoaderArgs, 'request' | 'context'>): Promise<RegularSearchReturn> {
  const {storefront} = context;
  const url = new URL(request.url);
  const term = String(url.searchParams.get('q') || '').trim();

  if (!term) {
    return {
      type: 'regular',
      term: '',
      result: {total: 0, items: {products: {nodes: []}} as never},
    };
  }

  let response: RegularSearchResponse;
  let error: string | undefined;
  try {
    response = (await storefront.query(SEARCH_QUERY, {
      variables: {term, first: 60},
    })) as RegularSearchResponse;
  } catch (err) {
    console.error('Search error', err);
    return {
      type: 'regular',
      term,
      error: err instanceof Error ? err.message : 'Search failed',
      result: {total: 0, items: {products: {nodes: []}} as never},
    };
  }

  const productsNodes = response?.products?.nodes ?? [];

  return {
    type: 'regular',
    term,
    error,
    result: {
      total: productsNodes.length,
      items: {products: {nodes: productsNodes}} as never,
    },
  };
}

const PREDICTIVE_SEARCH_QUERY = `#graphql
  query PredictiveSearch(
    $country: CountryCode
    $language: LanguageCode
    $limit: Int!
    $limitScope: PredictiveSearchLimitScope!
    $term: String!
  ) @inContext(country: $country, language: $language) {
    predictiveSearch(
      limit: $limit,
      limitScope: $limitScope,
      query: $term,
      types: [PRODUCT, COLLECTION, QUERY],
    ) {
      products {
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
            id
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
      collections {
        __typename
        id
        title
        handle
        image {
          id
          url
          altText
          width
          height
        }
        trackingParameters
      }
      queries {
        __typename
        text
        styledText
        trackingParameters
      }
    }
  }
` as const;

async function predictiveSearch({
  request,
  context,
}: Pick<
  Route.LoaderArgs,
  'request' | 'context'
>): Promise<PredictiveSearchReturn> {
  const {storefront} = context;
  const url = new URL(request.url);
  const term = String(url.searchParams.get('q') || '').trim();
  const limit = Number(url.searchParams.get('limit') || 6);
  const type = 'predictive';

  if (!term) {
    return {type, term, result: getEmptyPredictiveSearchResult()};
  }

  try {
    const {predictiveSearch: items} = (await storefront.query(
      PREDICTIVE_SEARCH_QUERY,
      {
        variables: {limit, limitScope: 'EACH', term},
      },
    )) as PredictiveSearchQuery;

    if (!items) {
      return {type, term, result: getEmptyPredictiveSearchResult()};
    }

    const total =
      (items.products?.length ?? 0) +
      (items.collections?.length ?? 0) +
      (items.queries?.length ?? 0);

    const empty = getEmptyPredictiveSearchResult();
    return {
      type,
      term,
      result: {
        total,
        items: {
          ...empty.items,
          products: items.products ?? [],
          collections: items.collections ?? [],
          queries: items.queries ?? [],
        },
      },
    };
  } catch (err) {
    console.error('Predictive search error', err);
    return {type, term, result: getEmptyPredictiveSearchResult()};
  }
}
