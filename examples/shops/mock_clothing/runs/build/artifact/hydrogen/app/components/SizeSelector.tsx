import {useState} from 'react';
import {Link, useNavigate} from 'react-router';
import {type MappedProductOptions} from '@shopify/hydrogen';
import {SizeGuideModal} from './SizeGuideModal';

const SIZE_RANGE_HINT: Record<string, string> = {
  XS: '(0-2)',
  S: '(4-6)',
  M: '(8-10)',
  L: '(12-14)',
  XL: '(16-18)',
  XXL: '(20-22)',
};

export function SizeSelector({option}: {option: MappedProductOptions}) {
  const navigate = useNavigate();
  const [guideOpen, setGuideOpen] = useState(false);

  return (
    <div className="pdp-variant-block">
      <div className="pdp-variant-label-row">
        <span className="pdp-variant-label">{option.name}</span>
        <button
          type="button"
          className="pdp-size-guide-link"
          onClick={() => setGuideOpen(true)}
        >
          Size Guide
        </button>
      </div>
      <div className="pdp-size-pills" role="radiogroup" aria-label={option.name}>
        {option.optionValues.map((value) => {
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
          const hint = SIZE_RANGE_HINT[name.toUpperCase()];
          const className = `pdp-size-pill${selected ? ' is-selected' : ''}${
            !available ? ' is-unavailable' : ''
          }`;

          const label = (
            <>
              <span className="pdp-size-pill-name">{name}</span>
              {hint ? <span className="pdp-size-pill-hint">{hint}</span> : null}
            </>
          );

          if (isDifferentProduct) {
            return (
              <Link
                key={`size-${name}`}
                to={`/products/${handle}?${variantUriQuery}`}
                prefetch="intent"
                preventScrollReset
                replace
                className={className}
                aria-checked={selected}
                role="radio"
              >
                {label}
              </Link>
            );
          }

          return (
            <button
              key={`size-${name}`}
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
            >
              {label}
            </button>
          );
        })}
      </div>
      <p className="pdp-size-fit-note">Fits true to size — relaxed silhouette.</p>
      {guideOpen ? (
        <SizeGuideModal
          optionName={option.name}
          values={option.optionValues.map((v) => v.name)}
          onClose={() => setGuideOpen(false)}
        />
      ) : null}
    </div>
  );
}
