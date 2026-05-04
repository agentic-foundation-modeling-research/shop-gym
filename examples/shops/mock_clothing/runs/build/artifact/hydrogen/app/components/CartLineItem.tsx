import type {CartLineUpdateInput} from '@shopify/hydrogen/storefront-api-types';
import type {CartLayout, LineItemChildrenMap} from '~/components/CartMain';
import {CartForm, Image, Money, type OptimisticCartLine} from '@shopify/hydrogen';
import {useVariantUrl} from '~/lib/variants';
import {Link} from 'react-router';
import {useAside} from './Aside';
import type {CartApiQueryFragment} from 'storefrontapi.generated';

export type CartLine = OptimisticCartLine<CartApiQueryFragment>;

export function CartLineItem({
  layout,
  line,
  childrenMap,
}: {
  layout: CartLayout;
  line: CartLine;
  childrenMap: LineItemChildrenMap;
}) {
  const {id, merchandise} = line;
  const {product, title, image, selectedOptions} = merchandise;
  const lineItemUrl = useVariantUrl(product.handle, selectedOptions);
  const {close} = useAside();
  const lineItemChildren = childrenMap[id];
  const childrenLabelId = `cart-line-children-${id}`;
  const totalAmount = line?.cost?.totalAmount;
  const compareAtAmount = line?.cost?.compareAtAmountPerQuantity;

  const handleClose = () => {
    if (layout === 'aside') close();
  };

  return (
    <li className="cart-line">
      <Link
        prefetch="intent"
        to={lineItemUrl}
        onClick={handleClose}
        className="cart-line-thumbnail"
        aria-hidden={!image}
      >
        {image ? (
          <Image
            alt={title}
            aspectRatio="1/1"
            data={image}
            height={96}
            loading="lazy"
            width={96}
            sizes="96px"
          />
        ) : (
          <div className="cart-line-thumbnail-placeholder" aria-hidden="true">
            <svg width="32" height="32" viewBox="0 0 48 48" fill="none">
              <rect width="48" height="48" rx="4" fill="#f0ede8" />
              <path
                d="M17 31l5-7 4 5 6-8 7 10H9l8-10z"
                fill="#d4cfc7"
              />
            </svg>
          </div>
        )}
      </Link>

      <div className="cart-line-body">
        <div className="cart-line-row">
          <Link
            prefetch="intent"
            to={lineItemUrl}
            onClick={handleClose}
            className="cart-line-title"
          >
            {product.title}
          </Link>
          <div className="cart-line-price">
            {compareAtAmount?.amount &&
            Number(compareAtAmount.amount) >
              Number(totalAmount?.amount ?? 0) ? (
              <>
                <span className="cart-line-price-sale">
                  {totalAmount && <Money data={totalAmount} />}
                </span>
                <s className="cart-line-price-was">
                  <Money data={compareAtAmount} />
                </s>
              </>
            ) : (
              totalAmount && <Money data={totalAmount} />
            )}
          </div>
        </div>

        {selectedOptions.length > 0 && (
          <ul className="cart-line-options" aria-label="Selected options">
            {selectedOptions.slice(0, 3).map((option) => (
              <li key={option.name} className="cart-line-option">
                {option.name}: {option.value}
              </li>
            ))}
          </ul>
        )}

        <CartLineQuantity line={line} />

        {lineItemChildren ? (
          <div className="cart-line-children-wrapper">
            <p id={childrenLabelId} className="sr-only">
              Line items with {product.title}
            </p>
            <ul
              aria-labelledby={childrenLabelId}
              className="cart-line-children"
            >
              {lineItemChildren.map((childLine) => (
                <CartLineItem
                  childrenMap={childrenMap}
                  key={childLine.id}
                  line={childLine}
                  layout={layout}
                />
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </li>
  );
}

function CartLineQuantity({line}: {line: CartLine}) {
  if (!line || typeof line?.quantity === 'undefined') return null;
  const {id: lineId, quantity, isOptimistic} = line;
  const prevQuantity = Number(Math.max(0, quantity - 1).toFixed(0));
  const nextQuantity = Number((quantity + 1).toFixed(0));

  return (
    <div className="cart-line-controls">
      <div className="cart-line-stepper">
        <CartLineUpdateButton lines={[{id: lineId, quantity: prevQuantity}]}>
          <button
            type="submit"
            className="cart-qty-btn"
            aria-label="Decrease quantity"
            disabled={!!isOptimistic}
            name="decrease-quantity"
            value={prevQuantity}
          >
            −
          </button>
        </CartLineUpdateButton>
        <span className="cart-qty-value" aria-live="polite">
          {quantity}
        </span>
        <CartLineUpdateButton lines={[{id: lineId, quantity: nextQuantity}]}>
          <button
            type="submit"
            className="cart-qty-btn"
            aria-label="Increase quantity"
            disabled={!!isOptimistic}
            name="increase-quantity"
            value={nextQuantity}
          >
            +
          </button>
        </CartLineUpdateButton>
      </div>
      <CartLineRemoveButton lineIds={[lineId]} disabled={!!isOptimistic} />
    </div>
  );
}

function CartLineRemoveButton({
  lineIds,
  disabled,
}: {
  lineIds: string[];
  disabled: boolean;
}) {
  return (
    <CartForm
      fetcherKey={getUpdateKey(lineIds)}
      route="/cart"
      action={CartForm.ACTIONS.LinesRemove}
      inputs={{lineIds}}
    >
      <button
        type="submit"
        className="cart-remove-btn"
        disabled={disabled}
      >
        Remove
      </button>
    </CartForm>
  );
}

function CartLineUpdateButton({
  children,
  lines,
}: {
  children: React.ReactNode;
  lines: CartLineUpdateInput[];
}) {
  const lineIds = lines.map((line) => line.id);

  return (
    <CartForm
      fetcherKey={getUpdateKey(lineIds)}
      route="/cart"
      action={CartForm.ACTIONS.LinesUpdate}
      inputs={{lines}}
    >
      {children}
    </CartForm>
  );
}

function getUpdateKey(lineIds: string[]) {
  return [CartForm.ACTIONS.LinesUpdate, ...lineIds].join('-');
}
