import type { FilterValue } from '~/lib/types';

/** One filter of a product list, in the backend's `ProductFilter` input shape. */
export type ProductFilter = Readonly<Record<string, unknown>>;

/** The path and query of a page: a `URL` or a router location. */
export interface PageLocation {
  readonly pathname: string;
  readonly search: string;
}

/** URL parameters of the product filters start with this prefix. */
const FILTER_PARAM_PREFIX = 'filter.';

/** Filter keys that hold one value at a time: choosing a value replaces the old one. */
const SINGLE_CHOICE_KEYS: ReadonlySet<string> = new Set(['categoryPath', 'rating']);

/**
 * The product filters that `location` asks for. A parameter `filter.<key>`
 * holds the JSON of one filter value, e.g. `filter.brand="Acme"` or
 * `filter.categoryPath=["Pets","Dogs"]`. A parameter `filter.<key>.<field>`
 * holds the JSON of one field of an object value, e.g. `filter.price.min=10`,
 * so a plain form can send it. Empty values and values that are not JSON are
 * skipped.
 */
export function productFiltersOf(location: PageLocation): ProductFilter[] {
  const filters: ProductFilter[] = [];
  const objects = new Map<string, Record<string, unknown>>();
  for (const [name, raw] of new URLSearchParams(location.search)) {
    if (!name.startsWith(FILTER_PARAM_PREFIX)) continue;
    const value = parseJson(raw);
    const [key, field, ...rest] = name.slice(FILTER_PARAM_PREFIX.length).split('.');
    if (value === undefined || !key || rest.length > 0) continue;
    if (field === undefined) {
      filters.push({ [key]: value });
      continue;
    }
    let object = objects.get(key);
    if (object === undefined) {
      object = {};
      objects.set(key, object);
      filters.push({ [key]: object });
    }
    object[field] = value;
  }
  return filters;
}

/** Whether `location` has `value` among its product filters. */
export function isFilterSelected(location: PageLocation, value: FilterValue): boolean {
  const wanted = value.input;
  return productFiltersOf(location).some((filter) => JSON.stringify(filter) === wanted);
}

/**
 * The link that turns `value` on, or off when it is on. A value of a
 * single-choice facet (category, rating) replaces the facet's current value.
 */
export function toggleFilterHref(location: PageLocation, value: FilterValue): string {
  const params = new URLSearchParams(location.search);
  const [entry] = Object.entries(JSON.parse(value.input) as ProductFilter);
  if (entry === undefined) return hrefOf(location.pathname, params);
  const [key, inner] = entry;
  const name = `${FILTER_PARAM_PREFIX}${key}`;
  const encoded = JSON.stringify(inner);
  const selected = isFilterSelected(location, value);
  const kept = [...params].filter(([paramName, raw]) => {
    if (SINGLE_CHOICE_KEYS.has(key)) return !isParamOf(paramName, key);
    return !(paramName === name && JSON.stringify(parseJson(raw)) === encoded);
  });
  const next = new URLSearchParams(kept);
  if (!selected) next.append(name, encoded);
  return hrefOf(location.pathname, next);
}

/** The link to the page at `location` with no product filters. */
export function clearFiltersHref(location: PageLocation): string {
  const kept = [...new URLSearchParams(location.search)].filter(
    ([name]) => !name.startsWith(FILTER_PARAM_PREFIX),
  );
  return hrefOf(location.pathname, new URLSearchParams(kept));
}

/** The query parameters of `location` that are not filters of `key`, for hidden form fields. */
export function paramsWithout(location: PageLocation, key: string): [string, string][] {
  return [...new URLSearchParams(location.search)].filter(([name]) => !isParamOf(name, key));
}

/** The price range that `location` filters by; each bound is absent when not set. */
export function selectedPriceRange(location: PageLocation): {
  readonly min?: number;
  readonly max?: number;
} {
  for (const filter of productFiltersOf(location)) {
    const range = filter.price;
    if (typeof range !== 'object' || range === null) continue;
    const { min, max } = range as Record<string, unknown>;
    return {
      ...(typeof min === 'number' ? { min } : {}),
      ...(typeof max === 'number' ? { max } : {}),
    };
  }
  return {};
}

/** The depth of a category value below its department (0 for a department); 0 for other values. */
export function categoryDepth(value: FilterValue): number {
  const path = (JSON.parse(value.input) as ProductFilter).categoryPath;
  return Array.isArray(path) ? Math.max(path.length - 1, 0) : 0;
}

function isParamOf(name: string, key: string): boolean {
  const prefix = `${FILTER_PARAM_PREFIX}${key}`;
  return name === prefix || name.startsWith(`${prefix}.`);
}

function parseJson(raw: string): unknown {
  if (raw.trim() === '') return undefined;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return undefined;
  }
}

function hrefOf(pathname: string, params: URLSearchParams): string {
  const search = params.toString();
  return search === '' ? pathname : `${pathname}?${search}`;
}
