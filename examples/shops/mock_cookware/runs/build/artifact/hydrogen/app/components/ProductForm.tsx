import {useState} from 'react';
import {Link, useNavigate} from 'react-router';
import {type MappedProductOptions} from '@shopify/hydrogen';
import type {
  Maybe,
  ProductOptionValueSwatch,
} from '@shopify/hydrogen/storefront-api-types';
import {AddToCartButton} from './AddToCartButton';
import {useAside} from './Aside';
import type {ProductFragment} from 'storefrontapi.generated';

const COLOR_OPTION_NAMES = new Set([
  'color',
  'colour',
  'finish',
  'shade',
  'tone',
]);
const SIZE_OPTION_NAMES = new Set(['size', 'apparel size']);

type Variant = NonNullable<ProductFragment['selectedOrFirstAvailableVariant']>;

export function ProductForm({
  productOptions,
  selectedVariant,
  onOpenSizeGuide,
}: {
  productOptions: MappedProductOptions[];
  selectedVariant: ProductFragment['selectedOrFirstAvailableVariant'];
  onOpenSizeGuide?: () => void;
}) {
  const navigate = useNavigate();
  const {open} = useAside();
  const [quantity, setQuantity] = useState(1);

  const decrementQuantity = () => setQuantity((q) => Math.max(1, q - 1));
  const incrementQuantity = () => setQuantity((q) => Math.min(99, q + 1));

  return (
    <div className="pdp-form">
      {productOptions.map((option) => {
        if (option.optionValues.length === 1) return null;
        const lower = option.name.trim().toLowerCase();
        const isColor = COLOR_OPTION_NAMES.has(lower);
        const isSize = SIZE_OPTION_NAMES.has(lower);
        const selectedValue =
          option.optionValues.find((v) => v.selected)?.name ?? '';

        return (
          <fieldset key={option.name} className="pdp-option">
            <legend className="pdp-option-legend">
              <span className="pdp-option-name">
                {option.name.toUpperCase()}: <strong>{selectedValue}</strong>
              </span>
              {isSize && onOpenSizeGuide ? (
                <button
                  type="button"
                  className="pdp-option-aux-link"
                  onClick={onOpenSizeGuide}
                >
                  Size Guide
                </button>
              ) : null}
            </legend>
            <div
              className={`pdp-option-grid${
                isColor
                  ? ' pdp-option-grid-color'
                  : isSize
                  ? ' pdp-option-grid-size'
                  : ' pdp-option-grid-default'
              }`}
            >
              {option.optionValues.map((value) => {
                const {
                  name,
                  handle,
                  variantUriQuery,
                  selected,
                  available: rawAvailable,
                  exists: rawExists,
                  isDifferentProduct,
                  swatch,
                } = value;
                // Mock API workaround: the encoded existence/availability strings
                // are empty so Hydrogen reports every value as missing.
                const exists = rawExists || true;
                const available = rawAvailable || true;
                const itemClass = `pdp-option-item${
                  selected ? ' is-selected' : ''
                }${available ? '' : ' is-unavailable'}${
                  isColor ? ' pdp-option-item-color' : ''
                }${isSize ? ' pdp-option-item-size' : ''}`;

                if (isDifferentProduct) {
                  return (
                    <Link
                      key={option.name + name}
                      className={itemClass}
                      prefetch="intent"
                      preventScrollReset
                      replace
                      to={`/products/${handle}?${variantUriQuery}`}
                      aria-label={`${option.name}: ${name}`}
                      aria-current={selected ? 'true' : undefined}
                    >
                      <ProductOptionLabel
                        swatch={swatch}
                        name={name}
                        isColor={isColor}
                        isSize={isSize}
                      />
                    </Link>
                  );
                }
                return (
                  <button
                    key={option.name + name}
                    type="button"
                    className={itemClass}
                    aria-pressed={selected}
                    aria-label={`${option.name}: ${name}`}
                    disabled={!exists}
                    onClick={() => {
                      if (!selected) {
                        void navigate(`?${variantUriQuery}`, {
                          replace: true,
                          preventScrollReset: true,
                        });
                      }
                    }}
                  >
                    <ProductOptionLabel
                      swatch={swatch}
                      name={name}
                      isColor={isColor}
                      isSize={isSize}
                    />
                  </button>
                );
              })}
            </div>
          </fieldset>
        );
      })}

      <div className="pdp-purchase-row">
        <QuantityStepper
          quantity={quantity}
          onDecrement={decrementQuantity}
          onIncrement={incrementQuantity}
        />
        <AddToCartButton
          className="pdp-add-to-cart"
          disabled={!selectedVariant || !selectedVariant.availableForSale}
          onClick={() => {
            open('cart');
          }}
          lines={
            selectedVariant
              ? [
                  {
                    merchandiseId: selectedVariant.id,
                    quantity,
                    selectedVariant: selectedVariant as Variant,
                  },
                ]
              : []
          }
        >
          {selectedVariant?.availableForSale ? 'Add to Cart' : 'Sold Out'}
        </AddToCartButton>
      </div>
    </div>
  );
}

function QuantityStepper({
  quantity,
  onDecrement,
  onIncrement,
}: {
  quantity: number;
  onDecrement: () => void;
  onIncrement: () => void;
}) {
  return (
    <div className="pdp-quantity" role="group" aria-label="Quantity">
      <span className="pdp-quantity-label" aria-hidden="true">
        QTY
      </span>
      <div className="pdp-quantity-controls">
        <button
          type="button"
          className="pdp-quantity-btn"
          aria-label="Decrease quantity"
          onClick={onDecrement}
          disabled={quantity <= 1}
        >
          −
        </button>
        <span className="pdp-quantity-value" aria-live="polite">
          {quantity}
        </span>
        <button
          type="button"
          className="pdp-quantity-btn"
          aria-label="Increase quantity"
          onClick={onIncrement}
          disabled={quantity >= 99}
        >
          +
        </button>
      </div>
    </div>
  );
}

function ProductOptionLabel({
  swatch,
  name,
  isColor,
  isSize,
}: {
  swatch?: Maybe<ProductOptionValueSwatch> | undefined;
  name: string;
  isColor: boolean;
  isSize: boolean;
}) {
  if (isColor) {
    const color = swatch?.color || colorFromName(name);
    const image = swatch?.image?.previewImage?.url;
    return (
      <span
        className="pdp-color-swatch"
        style={{backgroundColor: color}}
        aria-hidden="true"
      >
        {image ? <img src={image} alt="" /> : null}
      </span>
    );
  }
  if (isSize) {
    return <span className="pdp-size-pill-text">{name}</span>;
  }
  return <span className="pdp-option-text">{name}</span>;
}

function colorFromName(name: string): string {
  const map: Record<string, string> = {
    'slate gray': '#5a6168',
    'slate grey': '#5a6168',
    'onyx black': '#1a1a1a',
    black: '#1a1a1a',
    'matte black': '#202020',
    white: '#f5f0e6',
    cream: '#f1e9d8',
    ivory: '#f6efe1',
    sand: '#cdb892',
    natural: '#cdb892',
    copper: '#b87333',
    bronze: '#7d4f25',
    gold: '#c2a261',
    'rose gold': '#c98a7a',
    silver: '#bfc1c2',
    stainless: '#c4c8cc',
    chrome: '#bfc4c8',
    blue: '#2c4a6b',
    'navy blue': '#1c2c44',
    navy: '#1c2c44',
    teal: '#1f6b6c',
    'forest green': '#2f4a35',
    green: '#2f6b3a',
    olive: '#5a5b2a',
    sage: '#9eaa86',
    red: '#a4332c',
    'cherry red': '#a4332c',
    'flame orange': '#c8531f',
    orange: '#c8531f',
    burgundy: '#5a1f25',
    pink: '#d68aa1',
    yellow: '#d4a637',
    purple: '#5d3b73',
    charcoal: '#3a3a3a',
    graphite: '#3f4448',
    gunmetal: '#414851',
    pearl: '#e6e0d4',
    bone: '#e3d8c1',
    espresso: '#3f2a1d',
    walnut: '#5a3a23',
  };
  const key = name.trim().toLowerCase();
  return map[key] ?? '#c8c2b6';
}
