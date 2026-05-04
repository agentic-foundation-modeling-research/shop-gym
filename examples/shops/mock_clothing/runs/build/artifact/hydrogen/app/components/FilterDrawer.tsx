import {useEffect, useState, type ReactNode} from 'react';

export type FilterState = {
  minPrice: number;
  maxPrice: number;
  productTypes: string[];
  colors: string[];
  sizes: string[];
  justDropped: string[];
};

export type FilterFacet = {
  productTypes: Array<{value: string; count: number}>;
  colors: Array<{value: string; count: number}>;
  sizes: Array<{value: string; count: number}>;
  hasSizes: boolean;
  priceMin: number;
  priceMax: number;
};

const JUST_DROPPED_OPTIONS = ['This Week', 'This Month', 'This Season'];

function formatProductTypeLabel(value: string): string {
  if (!value.includes(':')) return value;
  const parts = value.split(':').map((p) => p.trim()).filter(Boolean);
  return parts[parts.length - 1] || value;
}

export function FilterDrawer({
  open,
  onClose,
  facets,
  initial,
  resultCount,
  onApply,
  onClearAll,
}: {
  open: boolean;
  onClose: () => void;
  facets: FilterFacet;
  initial: FilterState;
  resultCount: number;
  onApply: (next: FilterState) => void;
  onClearAll: () => void;
}) {
  const [pending, setPending] = useState<FilterState>(initial);

  useEffect(() => {
    if (open) setPending(initial);
  }, [open, initial]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  function toggle(arr: string[], value: string): string[] {
    return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
  }

  return (
    <div
      className={`filter-drawer-root${open ? ' is-open' : ''}`}
      aria-hidden={!open}
    >
      <button
        type="button"
        className="filter-drawer-backdrop"
        aria-label="Close filters"
        onClick={onClose}
        tabIndex={open ? 0 : -1}
      />
      <div
        className="filter-drawer-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Filters"
      >
        <header className="filter-drawer-header">
          <h2 className="filter-drawer-title">Filters</h2>
          <div className="filter-drawer-header-actions">
            <button
              type="button"
              className="filter-drawer-clear"
              onClick={() => {
                onClearAll();
                setPending({
                  minPrice: facets.priceMin,
                  maxPrice: facets.priceMax,
                  productTypes: [],
                  colors: [],
                  sizes: [],
                  justDropped: [],
                });
              }}
            >
              Clear all
            </button>
            <button
              type="button"
              className="filter-drawer-close"
              aria-label="Close"
              onClick={onClose}
            >
              ×
            </button>
          </div>
        </header>
        <div className="filter-drawer-body">
          <FilterSection title="Price">
            <PriceSlider
              min={facets.priceMin}
              max={facets.priceMax}
              minValue={pending.minPrice}
              maxValue={pending.maxPrice}
              onChange={(lo, hi) =>
                setPending((p) => ({...p, minPrice: lo, maxPrice: hi}))
              }
            />
          </FilterSection>

          {facets.productTypes.length > 0 ? (
            <FilterSection title="Product Type">
              <CheckboxList
                options={facets.productTypes}
                selected={pending.productTypes}
                formatLabel={formatProductTypeLabel}
                onToggle={(v) =>
                  setPending((p) => ({
                    ...p,
                    productTypes: toggle(p.productTypes, v),
                  }))
                }
                onClear={() =>
                  setPending((p) => ({...p, productTypes: []}))
                }
              />
            </FilterSection>
          ) : null}

          {facets.colors.length > 0 ? (
            <FilterSection title="Colour / Finish">
              <CheckboxList
                options={facets.colors}
                selected={pending.colors}
                onToggle={(v) =>
                  setPending((p) => ({...p, colors: toggle(p.colors, v)}))
                }
                onClear={() => setPending((p) => ({...p, colors: []}))}
              />
            </FilterSection>
          ) : null}

          {facets.hasSizes && facets.sizes.length > 0 ? (
            <FilterSection title="Size">
              <CheckboxList
                options={facets.sizes}
                selected={pending.sizes}
                onToggle={(v) =>
                  setPending((p) => ({...p, sizes: toggle(p.sizes, v)}))
                }
                onClear={() => setPending((p) => ({...p, sizes: []}))}
              />
            </FilterSection>
          ) : null}

          <FilterSection title="Just Dropped">
            <CheckboxList
              options={JUST_DROPPED_OPTIONS.map((v) => ({value: v, count: 0}))}
              selected={pending.justDropped}
              showCounts={false}
              onToggle={(v) =>
                setPending((p) => ({
                  ...p,
                  justDropped: toggle(p.justDropped, v),
                }))
              }
              onClear={() => setPending((p) => ({...p, justDropped: []}))}
            />
          </FilterSection>
        </div>
        <footer className="filter-drawer-footer">
          <button
            type="button"
            className="filter-drawer-apply"
            onClick={() => onApply(pending)}
          >
            View {resultCount} {resultCount === 1 ? 'product' : 'products'}
          </button>
        </footer>
      </div>
    </div>
  );
}

function FilterSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <section className="filter-section">
      <button
        type="button"
        className="filter-section-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>{title}</span>
        <span className={`filter-section-chevron${open ? ' is-open' : ''}`}>
          ›
        </span>
      </button>
      {open ? <div className="filter-section-body">{children}</div> : null}
    </section>
  );
}

function CheckboxList({
  options,
  selected,
  onToggle,
  onClear,
  showCounts = true,
  formatLabel,
}: {
  options: Array<{value: string; count: number}>;
  selected: string[];
  onToggle: (value: string) => void;
  onClear: () => void;
  showCounts?: boolean;
  formatLabel?: (value: string) => string;
}) {
  return (
    <div className="filter-checkbox-list">
      {options.map(({value, count}) => {
        const isChecked = selected.includes(value);
        const label = formatLabel ? formatLabel(value) : value;
        return (
          <label key={value} className="filter-checkbox-row">
            <input
              type="checkbox"
              className="filter-checkbox-input"
              checked={isChecked}
              onChange={() => onToggle(value)}
            />
            <span className="filter-checkbox-box" aria-hidden="true">
              {isChecked ? '✓' : ''}
            </span>
            <span className="filter-checkbox-label">{label}</span>
            {showCounts ? (
              <span className="filter-checkbox-count">({count})</span>
            ) : null}
          </label>
        );
      })}
      {selected.length > 0 ? (
        <button
          type="button"
          className="filter-section-reset"
          onClick={onClear}
        >
          Reset
        </button>
      ) : null}
    </div>
  );
}

function PriceSlider({
  min,
  max,
  minValue,
  maxValue,
  onChange,
}: {
  min: number;
  max: number;
  minValue: number;
  maxValue: number;
  onChange: (lo: number, hi: number) => void;
}) {
  const range = Math.max(max - min, 1);
  const lowPct = ((minValue - min) / range) * 100;
  const highPct = ((maxValue - min) / range) * 100;

  return (
    <div className="price-slider">
      <div className="price-slider-track">
        <div
          className="price-slider-track-active"
          style={{left: `${lowPct}%`, right: `${100 - highPct}%`}}
        />
        <input
          type="range"
          className="price-slider-input"
          min={min}
          max={max}
          value={minValue}
          step={1}
          aria-label="Minimum price"
          onChange={(e) => {
            const next = Math.min(parseInt(e.target.value, 10), maxValue);
            onChange(next, maxValue);
          }}
        />
        <input
          type="range"
          className="price-slider-input"
          min={min}
          max={max}
          value={maxValue}
          step={1}
          aria-label="Maximum price"
          onChange={(e) => {
            const next = Math.max(parseInt(e.target.value, 10), minValue);
            onChange(minValue, next);
          }}
        />
      </div>
      <div className="price-slider-fields">
        <label className="price-slider-field">
          <span>Min</span>
          <div className="price-slider-input-wrap">
            <span>$</span>
            <input
              type="number"
              min={min}
              max={maxValue}
              value={minValue}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                if (Number.isFinite(n))
                  onChange(Math.max(min, Math.min(n, maxValue)), maxValue);
              }}
            />
          </div>
        </label>
        <label className="price-slider-field">
          <span>Max</span>
          <div className="price-slider-input-wrap">
            <span>$</span>
            <input
              type="number"
              min={minValue}
              max={max}
              value={maxValue}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                if (Number.isFinite(n))
                  onChange(minValue, Math.min(max, Math.max(n, minValue)));
              }}
            />
          </div>
        </label>
      </div>
    </div>
  );
}
