import {Money, type MappedProductOptions} from '@shopify/hydrogen';
import {Link, useNavigate} from 'react-router';
import {useState} from 'react';
import {AddToCartButton} from './AddToCartButton';
import {QuantitySelector} from './QuantitySelector';
import type {ProductFragment} from 'storefrontapi.generated';

export function ProductForm({
  productOptions,
  selectedVariant,
}: {
  productOptions: MappedProductOptions[];
  selectedVariant: ProductFragment['selectedOrFirstAvailableVariant'];
}) {
  const navigate = useNavigate();
  const [quantity, setQuantity] = useState(1);

  return (
    <div className="product-form">
      {productOptions.map((option) => {
        if (option.optionValues.length === 1) return null;
        return (
          <fieldset className="product-options" key={option.name}>
            <legend className="product-options-legend">{option.name}</legend>
            <div className="product-options-list" role="radiogroup">
              {option.optionValues.map((value) => {
                const {
                  name,
                  handle,
                  variantUriQuery,
                  selected,
                  available: rawAvailable,
                  exists: rawExists,
                  isDifferentProduct,
                  firstSelectableVariant,
                } = value;

                const available = rawAvailable || true;
                const exists = rawExists || true;
                const sellable =
                  firstSelectableVariant?.availableForSale !== false;
                const variantPrice = firstSelectableVariant?.price;

                if (isDifferentProduct) {
                  return (
                    <Link
                      key={option.name + name}
                      to={`/products/${handle}?${variantUriQuery}`}
                      prefetch="intent"
                      preventScrollReset
                      replace
                      className={`product-option-row${
                        selected ? ' is-selected' : ''
                      }`}
                      aria-checked={selected}
                      role="radio"
                    >
                      <span
                        className={`product-option-radio${
                          selected ? ' is-checked' : ''
                        }`}
                        aria-hidden="true"
                      />
                      <span className="product-option-label">{name}</span>
                      {variantPrice ? (
                        <span className="product-option-price">
                          <Money data={variantPrice} />
                        </span>
                      ) : null}
                    </Link>
                  );
                }

                const disabled = !exists || !sellable;
                return (
                  <label
                    key={option.name + name}
                    className={`product-option-row${
                      selected ? ' is-selected' : ''
                    }${disabled ? ' is-disabled' : ''}`}
                  >
                    <input
                      type="radio"
                      name={`option-${option.name}`}
                      value={name}
                      checked={selected}
                      disabled={disabled}
                      className="product-option-input"
                      onChange={() => {
                        if (!selected) {
                          void navigate(`?${variantUriQuery}`, {
                            replace: true,
                            preventScrollReset: true,
                          });
                        }
                      }}
                    />
                    <span
                      className={`product-option-radio${
                        selected ? ' is-checked' : ''
                      }${disabled ? ' is-disabled' : ''}`}
                      aria-hidden="true"
                    />
                    <span className="product-option-label">{name}</span>
                    {variantPrice ? (
                      <span className="product-option-price">
                        <Money data={variantPrice} />
                      </span>
                    ) : null}
                    {disabled && !sellable ? (
                      <span className="product-option-badge">Sold out</span>
                    ) : null}
                  </label>
                );
              })}
            </div>
          </fieldset>
        );
      })}

      <div className="product-cta-row">
        <QuantitySelector value={quantity} onChange={setQuantity} />
        <AddToCartButton
          disabled={!selectedVariant || !selectedVariant.availableForSale}
          lines={
            selectedVariant
              ? [
                  {
                    merchandiseId: selectedVariant.id,
                    quantity,
                    selectedVariant,
                  },
                ]
              : []
          }
        >
          {selectedVariant?.availableForSale ? 'Add to cart' : 'Sold out'}
        </AddToCartButton>
      </div>
    </div>
  );
}
