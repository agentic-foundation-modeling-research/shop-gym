import type {CartLineUpdateInput} from '@shopify/hydrogen/storefront-api-types';
import type {LineItemChildrenMap} from '~/components/CartMain';
import {CartForm, Image, Money, type OptimisticCartLine} from '@shopify/hydrogen';
import {useVariantUrl} from '~/lib/variants';
import {Link} from 'react-router';
import type {CartApiQueryFragment} from 'storefrontapi.generated';

export type CartLine = OptimisticCartLine<CartApiQueryFragment>;

export function CartLineItem({
  line,
  childrenMap,
}: {
  line: CartLine;
  childrenMap: LineItemChildrenMap;
}) {
  const {id, merchandise} = line;
  const {product, title, image, selectedOptions} = merchandise;
  const lineItemUrl = useVariantUrl(product.handle, selectedOptions);
  const lineItemChildren = childrenMap[id];
  const variantLabel = selectedOptions
    .filter((option) => option.value && option.value !== 'Default Title')
    .map((option) => `${option.name}: ${option.value}`)
    .join(' / ');

  return (
    <>
      <tr className="cart-line-row">
        <td className="cart-line-cell cart-line-cell-image">
          <Link to={lineItemUrl} prefetch="intent" className="cart-line-image-link">
            {image ? (
              <Image
                alt={title}
                aspectRatio="1/1"
                data={image}
                height={96}
                loading="lazy"
                width={96}
                className="cart-line-image"
              />
            ) : (
              <div className="cart-line-image-placeholder" aria-hidden="true">
                <svg
                  width="40"
                  height="40"
                  viewBox="0 0 48 48"
                  fill="none"
                >
                  <rect width="48" height="48" rx="4" fill="#f0ede8" />
                  <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
                  <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
                </svg>
              </div>
            )}
          </Link>
        </td>

        <td className="cart-line-cell cart-line-cell-product">
          <Link
            to={lineItemUrl}
            prefetch="intent"
            className="cart-line-title"
          >
            {product.title}
          </Link>
          {variantLabel ? (
            <p className="cart-line-variant">{variantLabel}</p>
          ) : null}
          {line?.cost?.amountPerQuantity?.amount ? (
            <p className="cart-line-unit-price">
              <Money data={line.cost.amountPerQuantity} />
            </p>
          ) : null}
        </td>

        <td className="cart-line-cell cart-line-cell-qty">
          <CartLineQuantity line={line} productTitle={product.title} />
        </td>

        <td className="cart-line-cell cart-line-cell-total">
          {line?.cost?.totalAmount?.amount ? (
            <Money data={line.cost.totalAmount} />
          ) : null}
        </td>
      </tr>

      {lineItemChildren?.length
        ? lineItemChildren.map((childLine) => (
            <CartLineItem
              key={childLine.id}
              line={childLine}
              childrenMap={childrenMap}
            />
          ))
        : null}
    </>
  );
}

function CartLineQuantity({
  line,
  productTitle,
}: {
  line: CartLine;
  productTitle: string;
}) {
  if (!line || typeof line?.quantity === 'undefined') return null;
  const {id: lineId, quantity, isOptimistic} = line;
  const prevQuantity = Number(Math.max(0, quantity - 1).toFixed(0));
  const nextQuantity = Number((quantity + 1).toFixed(0));

  return (
    <div className="cart-line-qty-controls">
      <div className="cart-qty-stepper" role="group" aria-label="Quantity">
        <CartLineUpdateButton lines={[{id: lineId, quantity: prevQuantity}]}>
          <button
            type="submit"
            className="cart-qty-btn"
            aria-label="Decrease quantity"
            disabled={quantity <= 1 || !!isOptimistic}
            name="decrease-quantity"
            value={prevQuantity}
          >
            <span aria-hidden="true">−</span>
          </button>
        </CartLineUpdateButton>
        <span
          className="cart-qty-value"
          role="spinbutton"
          aria-valuenow={quantity}
          aria-valuemin={1}
          aria-label="Quantity"
        >
          {quantity}
        </span>
        <CartLineUpdateButton lines={[{id: lineId, quantity: nextQuantity}]}>
          <button
            type="submit"
            className="cart-qty-btn"
            aria-label="Increase quantity"
            name="increase-quantity"
            value={nextQuantity}
            disabled={!!isOptimistic}
          >
            <span aria-hidden="true">+</span>
          </button>
        </CartLineUpdateButton>
      </div>
      <CartLineRemoveButton
        lineIds={[lineId]}
        disabled={!!isOptimistic}
        productTitle={productTitle}
      />
    </div>
  );
}

function CartLineRemoveButton({
  lineIds,
  disabled,
  productTitle,
}: {
  lineIds: string[];
  disabled: boolean;
  productTitle: string;
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
        aria-label={`Remove ${productTitle}`}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
          <path d="M10 11v6M14 11v6" />
        </svg>
        <span className="sr-only">Remove {productTitle}</span>
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
