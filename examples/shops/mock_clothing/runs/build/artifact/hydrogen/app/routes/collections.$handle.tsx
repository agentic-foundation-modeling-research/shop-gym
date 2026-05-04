import {useMemo, useState, type ReactNode} from 'react';
import {Link, redirect, useLoaderData, useSearchParams} from 'react-router';
import type {Route} from './+types/collections.$handle';
import {Analytics} from '@shopify/hydrogen';
import {redirectIfHandleIsLocalized} from '~/lib/redirect';
import {ProductItem, type ProductItemRich} from '~/components/ProductItem';
import {
  FilterDrawer,
  type FilterFacet,
  type FilterState,
} from '~/components/FilterDrawer';
import {
  SortDropdown,
  isSortKey,
  type SortKey,
} from '~/components/SortDropdown';
import {Pagination} from '~/components/Pagination';

const PAGE_SIZE = 28;
const PRODUCTS_PER_BANNER = 28;

export const meta: Route.MetaFunction = ({data}) => {
  return [{title: `Mock Apparel | ${data?.collection.title ?? 'Collection'}`}];
};

export async function loader(args: Route.LoaderArgs) {
  return await loadCriticalData(args);
}

type CollectionResponse = {
  collection: {
    id: string;
    handle: string;
    title: string;
    description: string | null;
    products: {nodes: ProductItemRich[]};
  } | null;
};

type RelatedCollectionsResponse = {
  collections: {
    nodes: Array<{id: string; handle: string; title: string}>;
  };
};

async function loadCriticalData({context, params, request}: Route.LoaderArgs) {
  const {handle} = params;
  const {storefront} = context;

  if (!handle) throw redirect('/collections');

  const [collectionRes, relatedRes] = (await Promise.all([
    storefront.query(COLLECTION_QUERY, {variables: {handle}}),
    storefront.query(RELATED_COLLECTIONS_QUERY, {}),
  ])) as [CollectionResponse, RelatedCollectionsResponse];

  const collection = collectionRes.collection;
  if (!collection) {
    throw new Response(`Collection ${handle} not found`, {status: 404});
  }

  redirectIfHandleIsLocalized(request, {handle, data: collection});

  return {collection, relatedCollections: relatedRes.collections};
}

export default function Collection() {
  const {collection, relatedCollections} = useLoaderData<typeof loader>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [filterOpen, setFilterOpen] = useState(false);

  const products = collection.products.nodes;

  const facets = useMemo<FilterFacet>(
    () => deriveFacets(products),
    [products],
  );

  const currentFilters = useMemo<FilterState>(
    () => readFiltersFromParams(searchParams, facets),
    [searchParams, facets],
  );

  const currentSort: SortKey = useMemo(() => {
    const raw = searchParams.get('sort');
    return raw && isSortKey(raw) ? raw : 'trending';
  }, [searchParams]);

  const currentPage = Math.max(1, parseInt(searchParams.get('page') ?? '1', 10) || 1);

  const filtered = useMemo(
    () => applyFilters(products, currentFilters),
    [products, currentFilters],
  );

  const sorted = useMemo(
    () => applySort(filtered, currentSort),
    [filtered, currentSort],
  );

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pageStart = (safePage - 1) * PAGE_SIZE;
  const pageProducts = sorted.slice(pageStart, pageStart + PAGE_SIZE);

  const activeFilterCount = countActiveFilterGroups(currentFilters, facets);

  const subPills = useMemo(() => {
    const pillSource = relatedCollections?.nodes ?? [];
    return derivePills(collection.handle, pillSource);
  }, [collection.handle, relatedCollections]);

  function commitFilters(next: FilterState) {
    const params = new URLSearchParams(searchParams);
    params.delete('page');
    writeFiltersToParams(params, next, facets);
    setSearchParams(params, {preventScrollReset: true});
    setFilterOpen(false);
  }

  function clearAllFilters() {
    const params = new URLSearchParams(searchParams);
    params.delete('minPrice');
    params.delete('maxPrice');
    params.delete('type');
    params.delete('color');
    params.delete('size');
    params.delete('drop');
    params.delete('page');
    setSearchParams(params, {preventScrollReset: true});
  }

  function changeSort(sort: SortKey) {
    const params = new URLSearchParams(searchParams);
    if (sort === 'trending') params.delete('sort');
    else params.set('sort', sort);
    params.delete('page');
    setSearchParams(params, {preventScrollReset: true});
  }

  // Live preview of result count using the drawer's pending state would be
  // complex. We pass the *currently committed* count so the user gets a
  // reasonable signal without extra plumbing.
  const drawerResultCount = filtered.length;

  return (
    <div className="collection-page">
      <CollectionHeader
        title={collection.title}
        description={collection.description}
        handle={collection.handle}
        productCount={products.length}
        subPills={subPills}
      />

      <div className="collection-toolbar">
        <button
          type="button"
          className="collection-toolbar-filter-btn"
          onClick={() => setFilterOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={filterOpen}
        >
          <FilterIcon />
          <span>Filters</span>
          {activeFilterCount > 0 ? (
            <span className="collection-toolbar-filter-count">
              · {activeFilterCount}
            </span>
          ) : null}
        </button>
        <SortDropdown value={currentSort} onChange={changeSort} />
      </div>

      {pageProducts.length > 0 ? (
        <ProductGrid products={pageProducts} pageStart={pageStart} />
      ) : (
        <EmptyState onClear={clearAllFilters} />
      )}

      <Pagination totalPages={totalPages} currentPage={safePage} />

      <FilterDrawer
        open={filterOpen}
        onClose={() => setFilterOpen(false)}
        facets={facets}
        initial={currentFilters}
        resultCount={drawerResultCount}
        onApply={commitFilters}
        onClearAll={clearAllFilters}
      />

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

function CollectionHeader({
  title,
  description,
  handle,
  productCount,
  subPills,
}: {
  title: string;
  description: string | null | undefined;
  handle: string;
  productCount: number;
  subPills: Array<{title: string; handle: string}>;
}) {
  const crumb = breadcrumbForHandle(handle, title);
  return (
    <header className="collection-header">
      <nav className="collection-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li>
            <Link to="/" prefetch="intent">
              Home
            </Link>
          </li>
          {crumb.parent ? (
            <li>
              <span className="collection-breadcrumb-sep">›</span>
              <Link
                to={`/collections/${crumb.parent.handle}`}
                prefetch="intent"
              >
                {crumb.parent.title}
              </Link>
            </li>
          ) : null}
          <li>
            <span className="collection-breadcrumb-sep">›</span>
            <span className="collection-breadcrumb-current">{title}</span>
          </li>
        </ol>
      </nav>
      <h1 className="collection-title">{title}</h1>
      {description ? (
        <p className="collection-description">{description}</p>
      ) : null}
      <p className="collection-count">
        {productCount} {productCount === 1 ? 'product' : 'products'}
      </p>
      {subPills.length > 0 ? (
        <div
          className="collection-subpill-row"
          role="navigation"
          aria-label="Subcategories"
        >
          {subPills.map((p) => (
            <Link
              key={p.handle}
              to={`/collections/${p.handle}`}
              prefetch="intent"
              className="collection-subpill"
            >
              {p.title}
            </Link>
          ))}
        </div>
      ) : null}
    </header>
  );
}

function ProductGrid({
  products,
  pageStart,
}: {
  products: ProductItemRich[];
  pageStart: number;
}) {
  // Insert promotional banners every PRODUCTS_PER_BANNER cards within the
  // current page (banner = full-width grid row).
  const items: ReactNode[] = [];
  products.forEach((product, idx) => {
    const absoluteIdx = pageStart + idx;
    items.push(
      <ProductItem
        key={product.id}
        product={product}
        loading={idx < 8 ? 'eager' : 'lazy'}
      />,
    );
    if ((absoluteIdx + 1) % PRODUCTS_PER_BANNER === 0) {
      items.push(<PromoBanner key={`banner-${absoluteIdx}`} variant={(absoluteIdx / PRODUCTS_PER_BANNER) % 2 === 0 ? 'a' : 'b'} />);
    }
  });
  return <div className="collection-grid">{items}</div>;
}

function PromoBanner({variant}: {variant: 'a' | 'b'}) {
  const isA = variant === 'a';
  return (
    <Link
      to={isA ? '/collections/universal-gift-guide' : '/collections/fan-favorites'}
      prefetch="intent"
      className={`collection-promo-banner${isA ? '' : ' is-alt'}`}
    >
      <div className="collection-promo-banner-content">
        <span className="collection-promo-eyebrow">
          {isA ? 'The Gifting Edit' : 'Member Favourites'}
        </span>
        <h3 className="collection-promo-heading">
          {isA
            ? 'Pieces they will reach for again and again'
            : 'Top-rated picks from the Mock Apparel community'}
        </h3>
        <span className="collection-promo-cta">
          {isA ? 'Shop the edit' : 'See what is trending'} →
        </span>
      </div>
    </Link>
  );
}

function EmptyState({onClear}: {onClear: () => void}) {
  return (
    <div className="collection-empty" role="status">
      <h2>No products found</h2>
      <p>Try adjusting your filters or clearing your selection.</p>
      <button
        type="button"
        className="collection-empty-clear"
        onClick={onClear}
      >
        Clear all filters
      </button>
    </div>
  );
}

function FilterIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      aria-hidden="true"
    >
      <path d="M2 4h12M4 8h8M6 12h4" strokeLinecap="round" />
    </svg>
  );
}

// ---- helpers ----

function deriveFacets(products: ProductItemRich[]): FilterFacet {
  const typeCounts = new Map<string, number>();
  const colorCounts = new Map<string, number>();
  const sizeCounts = new Map<string, number>();
  let priceMin = Number.POSITIVE_INFINITY;
  let priceMax = 0;
  let hasSizes = false;

  for (const p of products) {
    const price = parseFloat(p.priceRange.minVariantPrice.amount);
    if (Number.isFinite(price)) {
      priceMin = Math.min(priceMin, price);
      priceMax = Math.max(priceMax, price);
    }
    if (p.productType) {
      typeCounts.set(p.productType, (typeCounts.get(p.productType) ?? 0) + 1);
    }
    const colorOpt = p.options?.find((o) => o.name.toLowerCase() === 'color');
    if (colorOpt) {
      for (const v of colorOpt.values) {
        colorCounts.set(v, (colorCounts.get(v) ?? 0) + 1);
      }
    }
    const sizeOpt = p.options?.find((o) => o.name.toLowerCase() === 'size');
    if (sizeOpt) {
      hasSizes = true;
      for (const v of sizeOpt.values) {
        sizeCounts.set(v, (sizeCounts.get(v) ?? 0) + 1);
      }
    }
  }

  if (!Number.isFinite(priceMin)) priceMin = 0;
  if (priceMax === 0) priceMax = 100;
  const flooredMin = Math.floor(priceMin);
  const ceiledMax = Math.ceil(priceMax);

  return {
    productTypes: sortByCount(typeCounts),
    colors: sortByCount(colorCounts),
    sizes: sortSizes(sizeCounts),
    hasSizes,
    priceMin: flooredMin,
    priceMax: ceiledMax === flooredMin ? flooredMin + 1 : ceiledMax,
  };
}

function sortByCount(
  counts: Map<string, number>,
): Array<{value: string; count: number}> {
  return Array.from(counts.entries())
    .map(([value, count]) => ({value, count}))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

const SIZE_ORDER = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL'];

function sortSizes(
  counts: Map<string, number>,
): Array<{value: string; count: number}> {
  const arr = Array.from(counts.entries()).map(([value, count]) => ({
    value,
    count,
  }));
  arr.sort((a, b) => {
    const ai = SIZE_ORDER.indexOf(a.value.toUpperCase());
    const bi = SIZE_ORDER.indexOf(b.value.toUpperCase());
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.value.localeCompare(b.value);
  });
  return arr;
}

function readFiltersFromParams(
  params: URLSearchParams,
  facets: FilterFacet,
): FilterState {
  const minP = parseInt(params.get('minPrice') ?? '', 10);
  const maxP = parseInt(params.get('maxPrice') ?? '', 10);
  return {
    minPrice: Number.isFinite(minP) ? minP : facets.priceMin,
    maxPrice: Number.isFinite(maxP) ? maxP : facets.priceMax,
    productTypes: parseList(params.get('type')),
    colors: parseList(params.get('color')),
    sizes: parseList(params.get('size')),
    justDropped: parseList(params.get('drop')),
  };
}

function writeFiltersToParams(
  params: URLSearchParams,
  state: FilterState,
  facets: FilterFacet,
) {
  if (state.minPrice > facets.priceMin) {
    params.set('minPrice', String(state.minPrice));
  } else {
    params.delete('minPrice');
  }
  if (state.maxPrice < facets.priceMax) {
    params.set('maxPrice', String(state.maxPrice));
  } else {
    params.delete('maxPrice');
  }
  setOrDelete(params, 'type', state.productTypes);
  setOrDelete(params, 'color', state.colors);
  setOrDelete(params, 'size', state.sizes);
  setOrDelete(params, 'drop', state.justDropped);
}

function setOrDelete(params: URLSearchParams, key: string, values: string[]) {
  if (values.length === 0) {
    params.delete(key);
  } else {
    params.set(key, values.join(','));
  }
}

function parseList(raw: string | null): string[] {
  if (!raw) return [];
  return raw.split(',').filter(Boolean);
}

function applyFilters(
  products: ProductItemRich[],
  state: FilterState,
): ProductItemRich[] {
  return products.filter((p) => {
    const price = parseFloat(p.priceRange.minVariantPrice.amount);
    if (Number.isFinite(price)) {
      if (price < state.minPrice || price > state.maxPrice) return false;
    }
    if (
      state.productTypes.length > 0 &&
      (!p.productType || !state.productTypes.includes(p.productType))
    ) {
      return false;
    }
    if (state.colors.length > 0) {
      const colorOpt = p.options?.find(
        (o) => o.name.toLowerCase() === 'color',
      );
      if (!colorOpt) return false;
      if (!colorOpt.values.some((v) => state.colors.includes(v))) return false;
    }
    if (state.sizes.length > 0) {
      const sizeOpt = p.options?.find((o) => o.name.toLowerCase() === 'size');
      if (!sizeOpt) return false;
      if (!sizeOpt.values.some((v) => state.sizes.includes(v))) return false;
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
      arr.reverse();
      break;
    case 'trending':
    default:
      // keep server order
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

function countActiveFilterGroups(
  state: FilterState,
  facets: FilterFacet,
): number {
  let n = 0;
  if (state.minPrice > facets.priceMin || state.maxPrice < facets.priceMax) n++;
  if (state.productTypes.length > 0) n++;
  if (state.colors.length > 0) n++;
  if (state.sizes.length > 0) n++;
  if (state.justDropped.length > 0) n++;
  return n;
}

function breadcrumbForHandle(
  handle: string,
  title: string,
): {parent: {handle: string; title: string} | null; current: string} {
  const lc = handle.toLowerCase();
  const parents: Array<{prefix: string; handle: string; title: string}> = [
    {prefix: 'womens-', handle: 'womens-browse-all', title: "Women's"},
    {prefix: 'mens-', handle: 'mens-browse-all', title: "Men's"},
  ];
  for (const p of parents) {
    if (lc.startsWith(p.prefix) && lc !== p.handle) {
      return {parent: {handle: p.handle, title: p.title}, current: title};
    }
  }
  return {parent: null, current: title};
}

function derivePills(
  currentHandle: string,
  collections: Array<{handle: string; title: string}>,
): Array<{title: string; handle: string}> {
  const lc = currentHandle.toLowerCase();
  const groups: Array<{match: (h: string) => boolean; exclude: string[]}> = [
    {
      match: (h) => h.startsWith('womens-'),
      exclude: ['womens-shop-all'],
    },
    {
      match: (h) => h.startsWith('mens-'),
      exclude: ['mens-shop-all'],
    },
    {
      match: (h) =>
        ['necklaces', 'bracelets', 'rings-earrings', 'watches', 'personalised-jewellery'].includes(h),
      exclude: [],
    },
  ];

  let related: Array<{title: string; handle: string}> = [];
  for (const g of groups) {
    if (g.match(lc) || g.exclude.includes(lc)) {
      related = collections
        .filter((c) => g.match(c.handle.toLowerCase()))
        .filter((c) => c.handle !== currentHandle)
        .slice(0, 12)
        .map((c) => ({title: c.title, handle: c.handle}));
      break;
    }
  }

  if (related.length === 0 && lc !== 'all') {
    related = collections
      .filter((c) =>
        ['new-arrivals', 'best-sellers', 'sale', 'gifting-edit'].includes(
          c.handle,
        ),
      )
      .filter((c) => c.handle !== currentHandle)
      .map((c) => ({title: c.title, handle: c.handle}));
  }

  return related;
}

const COLLECTION_QUERY = `#graphql
  query Collection(
    $handle: String!
    $country: CountryCode
    $language: LanguageCode
  ) @inContext(country: $country, language: $language) {
    collection(handle: $handle) {
      id
      handle
      title
      description
      products(first: 250) {
        nodes {
          id
          handle
          title
          productType
          tags
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

const RELATED_COLLECTIONS_QUERY = `#graphql
  query RelatedCollections(
    $country: CountryCode
    $language: LanguageCode
  ) @inContext(country: $country, language: $language) {
    collections(first: 50) {
      nodes {
        id
        handle
        title
      }
    }
  }
` as const;
