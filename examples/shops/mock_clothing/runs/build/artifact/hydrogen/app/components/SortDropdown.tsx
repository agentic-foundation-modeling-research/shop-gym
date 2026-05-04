import {useEffect, useRef, useState} from 'react';

export type SortKey =
  | 'trending'
  | 'discount-desc'
  | 'price-asc'
  | 'price-desc'
  | 'new';

const SORT_OPTIONS: Array<{value: SortKey; label: string}> = [
  {value: 'trending', label: 'Trending'},
  {value: 'discount-desc', label: 'Discount — High to Low'},
  {value: 'price-asc', label: 'Price — Low to High'},
  {value: 'price-desc', label: 'Price — High to Low'},
  {value: 'new', label: 'New Arrivals'},
];

export function SortDropdown({
  value,
  onChange,
}: {
  value: SortKey;
  onChange: (next: SortKey) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const current = SORT_OPTIONS.find((o) => o.value === value) ?? SORT_OPTIONS[0];

  return (
    <div className="sort-dropdown" ref={wrapperRef}>
      <button
        type="button"
        className="sort-dropdown-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="sort-dropdown-label">Sort:</span>
        <span className="sort-dropdown-value">{current.label}</span>
        <span className={`sort-dropdown-chevron${open ? ' is-open' : ''}`}>
          ▾
        </span>
      </button>
      {open ? (
        <ul className="sort-dropdown-menu" role="listbox">
          {SORT_OPTIONS.map((opt) => (
            <li
              key={opt.value}
              role="option"
              aria-selected={opt.value === value}
            >
              <button
                type="button"
                className={`sort-dropdown-item${
                  opt.value === value ? ' is-active' : ''
                }`}
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
              >
                {opt.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function isSortKey(value: string): value is SortKey {
  return SORT_OPTIONS.some((o) => o.value === value);
}
