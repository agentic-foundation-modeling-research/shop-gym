import {Link, useNavigate} from 'react-router';
import {type MappedProductOptions} from '@shopify/hydrogen';
import {colorNameToHex, isLightColor} from '~/lib/productColors';

const HIGHLIGHT_BADGES: Record<number, string> = {
  0: 'Best Seller',
  1: 'Limited Run',
};

export function ColorSwatches({
  option,
  selectedLabel,
}: {
  option: MappedProductOptions;
  selectedLabel?: string;
}) {
  const navigate = useNavigate();

  return (
    <div className="pdp-variant-block">
      <div className="pdp-variant-label-row">
        <span className="pdp-variant-label">{option.name}:</span>
        <span className="pdp-variant-value">{selectedLabel ?? '—'}</span>
      </div>
      <div className="pdp-color-swatches" role="radiogroup" aria-label={option.name}>
        {option.optionValues.map((value, idx) => {
          const {
            name,
            handle,
            variantUriQuery,
            selected,
            available: rawAvailable,
            exists: rawExists,
            isDifferentProduct,
          } = value;

          const exists = rawExists || true;
          const available = rawAvailable || true;
          const swatchHex = colorNameToHex(name);
          const isLight = isLightColor(swatchHex);
          const badge = HIGHLIGHT_BADGES[idx];

          const className = `pdp-color-swatch${
            selected ? ' is-selected' : ''
          }${!available ? ' is-unavailable' : ''}${isLight ? ' is-light' : ''}`;

          const inner = (
            <>
              <span
                className="pdp-color-swatch-chip"
                style={{background: swatchHex}}
                aria-hidden="true"
              />
              <span className="pdp-color-swatch-label">{name}</span>
              {badge ? (
                <span className="pdp-color-swatch-badge">{badge}</span>
              ) : null}
            </>
          );

          if (isDifferentProduct) {
            return (
              <Link
                key={`${option.name}-${name}`}
                to={`/products/${handle}?${variantUriQuery}`}
                prefetch="intent"
                preventScrollReset
                replace
                className={className}
                aria-checked={selected}
                role="radio"
                title={!available ? 'Currently unavailable' : name}
              >
                {inner}
              </Link>
            );
          }

          return (
            <button
              key={`${option.name}-${name}`}
              type="button"
              className={className}
              onClick={() => {
                if (!selected && exists) {
                  void navigate(`?${variantUriQuery}`, {
                    replace: true,
                    preventScrollReset: true,
                  });
                }
              }}
              disabled={!exists}
              role="radio"
              aria-checked={selected}
              aria-disabled={!available}
              title={!available ? 'Currently unavailable' : name}
            >
              {inner}
            </button>
          );
        })}
      </div>
    </div>
  );
}
