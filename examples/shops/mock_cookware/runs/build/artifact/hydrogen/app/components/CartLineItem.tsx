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
  const {id, merchandise, cost} = line;
  const {product, title, image, selectedOptions, compareAtPrice, price} =
    merchandise;
  const lineItemUrl = useVariantUrl(product.handle, selectedOptions);
  const {close} = useAside();
  const lineItemChildren = childrenMap[id];
  const childrenLabelId = `cart-line-children-${id}`;

  const variantLabel =
    title && title !== 'Default Title'
      ? title
      : selectedOptions
          .filter((opt) => opt.name !== 'Title' && opt.value !== 'Default Title')
          .map((opt) => opt.value)
          .join(' / ');

  const onItemClick = () => {
    if (layout === 'aside') close();
  };

  return (
    <li className="cart-line">
      <Link
        prefetch="intent"
        to={lineItemUrl}
        onClick={onItemClick}
        className="cart-line-image"
      >
        {image ? (
          <Image
            alt={image.altText || product.title}
            aspectRatio="1/1"
            data={image}
            height={120}
            loading="lazy"
            width={120}
            sizes="120px"
          />
        ) : (
          <div className="cart-line-image-placeholder" aria-hidden="true">
            <svg width="32" height="32" viewBox="0 0 48 48" fill="none">
              <rect width="48" height="48" rx="4" fill="#f0ede8" />
              <path d="M17 31l5-7 4 5 6-8 7 10H9l8-10z" fill="#d4cfc7" />
              <circle cx="18" cy="19" r="3" fill="#d4cfc7" />
            </svg>
          </div>
        )}
      </Link>

      <div className="cart-line-content">
        <div className="cart-line-header">
          <Link
            prefetch="intent"
            to={lineItemUrl}
            onClick={onItemClick}
            className="cart-line-title"
          >
            {product.title}
          </Link>
          <CartLineRemoveButton lineIds={[id]} disabled={!!line.isOptimistic} />
        </div>

        {variantLabel ? (
          <p className="cart-line-variant">{variantLabel}</p>
        ) : null}

        <div className="cart-line-price">
          {compareAtPrice ? (
            <s className="cart-line-compare">
              <Money data={compareAtPrice} />
            </s>
          ) : null}
          {price ? <Money data={price} /> : null}
        </div>

        <CartLineQuantity line={line} />

        {cost?.totalAmount ? (
          <div className="cart-line-line-total">
            <span>Line total</span>
            <Money data={cost.totalAmount} />
          </div>
        ) : null}
      </div>

      {lineItemChildren ? (
        <div className="cart-line-children-wrap">
          <p id={childrenLabelId} className="sr-only">
            Line items with {product.title}
          </p>
          <ul aria-labelledby={childrenLabelId} className="cart-line-children">
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
    </li>
  );
}

function CartLineQuantity({line}: {line: CartLine}) {
  if (!line || typeof line?.quantity === 'undefined') return null;
  const {id: lineId, quantity, isOptimistic} = line;
  const prevQuantity = Number(Math.max(0, quantity - 1).toFixed(0));
  const nextQuantity = Number((quantity + 1).toFixed(0));

  return (
    <div className="cart-line-quantity" role="group" aria-label="Quantity">
      <CartLineUpdateButton lines={[{id: lineId, quantity: prevQuantity}]}>
        <button
          type="submit"
          className="cart-qty-btn"
          aria-label="Decrease quantity"
          disabled={quantity <= 1 || !!isOptimistic}
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
          name="increase-quantity"
          value={nextQuantity}
          disabled={!!isOptimistic}
        >
          +
        </button>
      </CartLineUpdateButton>
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
        aria-label="Remove item"
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
