import type { ReactNode } from 'react';
import { Form, Link, useLocation } from 'react-router';
import {
  type PageLocation,
  categoryDepth,
  clearFiltersHref,
  isFilterSelected,
  paramsWithout,
  productFiltersOf,
  selectedPriceRange,
  toggleFilterHref,
} from '~/lib/facets';
import type { Filter, FilterValue } from '~/lib/types';

/** Values a facet shows before its "See more" toggle; selected values always show. */
const VISIBLE_VALUES = 10;

/**
 * A product list with the "Filters" panel beside it. With no facets it
 * renders `children` alone, so a shop without marketplace data looks as
 * before. Every control is a link or a GET form, so the URL holds the whole
 * filter state (see `~/lib/facets`).
 */
export function FacetLayout({
  filters,
  children,
}: {
  readonly filters: readonly Filter[];
  readonly children: ReactNode;
}) {
  const location = useLocation();
  if (filters.length === 0) return <>{children}</>;
  return (
    <div className="facet-layout">
      <aside className="facet-panel stack" aria-label="Filters">
        <h2>Filters</h2>
        {productFiltersOf(location).length > 0 ? (
          <Link to={clearFiltersHref(location)}>Clear all filters</Link>
        ) : null}
        {filters.map((filter) => (
          <FacetGroup key={filter.id} filter={filter} location={location} />
        ))}
      </aside>
      <div className="facet-results stack">{children}</div>
    </div>
  );
}

/** One facet as a region named by its label, e.g. "Brand". */
function FacetGroup({
  filter,
  location,
}: {
  readonly filter: Filter;
  readonly location: PageLocation;
}) {
  const headingId = `facet-${filter.id.replaceAll('.', '-')}`;
  return (
    <section className="facet stack" aria-labelledby={headingId}>
      <h3 id={headingId}>{filter.label}</h3>
      {filter.type === 'PRICE_RANGE' ? (
        <PriceRangeForm filter={filter} location={location} />
      ) : (
        <FacetValues values={filter.values} location={location} />
      )}
    </section>
  );
}

/**
 * The values of a list facet as links named "<label> (<count>)". A selected
 * value has `aria-current="true"`, and its link turns it off.
 */
function FacetValues({
  values,
  location,
}: {
  readonly values: readonly FilterValue[];
  readonly location: PageLocation;
}) {
  const shown = values.filter(
    (value, index) => index < VISIBLE_VALUES || isFilterSelected(location, value),
  );
  const more = values.filter((value) => !shown.includes(value));
  return (
    <>
      <ValueList values={shown} location={location} />
      {more.length > 0 ? (
        <details className="facet-more">
          <summary>See {more.length} more</summary>
          <ValueList values={more} location={location} />
        </details>
      ) : null}
    </>
  );
}

function ValueList({
  values,
  location,
}: {
  readonly values: readonly FilterValue[];
  readonly location: PageLocation;
}) {
  return (
    <ul className="facet-values">
      {values.map((value) => (
        <li key={value.id} style={{ paddingInlineStart: `${categoryDepth(value)}rem` }}>
          <Link
            className="facet-value"
            to={toggleFilterHref(location, value)}
            aria-current={isFilterSelected(location, value) ? 'true' : undefined}
          >
            {value.label} <span className="muted">({value.count})</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * The price facet as a GET form with "Min price" and "Max price". Hidden
 * fields keep the page's other parameters; the placeholders show the price
 * range of the list.
 */
function PriceRangeForm({
  filter,
  location,
}: {
  readonly filter: Filter;
  readonly location: PageLocation;
}) {
  const [value] = filter.values;
  const bounds = value
    ? ((JSON.parse(value.input) as { price?: { min?: number; max?: number } }).price ?? {})
    : {};
  const selected = selectedPriceRange(location);
  return (
    <Form key={location.search} method="get" action={location.pathname} className="facet-price">
      {paramsWithout(location, 'price').map(([name, paramValue]) => (
        <input key={`${name}=${paramValue}`} type="hidden" name={name} value={paramValue} />
      ))}
      <label>
        Min price
        <input
          type="number"
          name="filter.price.min"
          min={0}
          step="any"
          inputMode="decimal"
          placeholder={String(bounds.min ?? 0)}
          defaultValue={selected.min ?? ''}
        />
      </label>
      <label>
        Max price
        <input
          type="number"
          name="filter.price.max"
          min={0}
          step="any"
          inputMode="decimal"
          placeholder={bounds.max === undefined ? '' : String(bounds.max)}
          defaultValue={selected.max ?? ''}
        />
      </label>
      <button type="submit">Apply</button>
    </Form>
  );
}
