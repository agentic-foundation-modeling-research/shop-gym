import {Money, useOptimisticCart} from '@shopify/hydrogen';
import {Link} from 'react-router';
import type {CartApiQueryFragment} from 'storefrontapi.generated';
import {useAside} from '~/components/Aside';
import {CartLineItem, type CartLine} from '~/components/CartLineItem';
import {CartSummary} from './CartSummary';

export type CartLayout = 'page' | 'aside';

export type CartMainProps = {
  cart: CartApiQueryFragment | null;
  layout: CartLayout;
};

export type LineItemChildrenMap = {[parentId: string]: CartLine[]};

const FREE_SHIP_THRESHOLD = 75;
const FREE_GIFT_THRESHOLD = 150;

function getLineItemChildrenMap(lines: CartLine[]): LineItemChildrenMap {
  const children: LineItemChildrenMap = {};
  for (const line of lines) {
    if ('parentRelationship' in line && line.parentRelationship?.parent) {
      const parentId = line.parentRelationship.parent.id;
      if (!children[parentId]) children[parentId] = [];
      children[parentId].push(line);
    }
    if ('lineComponents' in line) {
      const nested = getLineItemChildrenMap(line.lineComponents);
      for (const [parentId, childIds] of Object.entries(nested)) {
        if (!children[parentId]) children[parentId] = [];
        children[parentId].push(...childIds);
      }
    }
  }
  return children;
}

export function CartMain({layout, cart: originalCart}: CartMainProps) {
  const cart = useOptimisticCart(originalCart);

  const lines = cart?.lines?.nodes ?? [];
  const visibleLines = lines.filter(
    (line) =>
      !('parentRelationship' in line && line.parentRelationship?.parent),
  );
  const itemCount = cart?.totalQuantity ?? 0;
  const hasItems = itemCount > 0;
  const childrenMap = getLineItemChildrenMap(lines);

  const subtotalAmount = cart?.cost?.subtotalAmount?.amount;
  const subtotal = subtotalAmount ? parseFloat(subtotalAmount) : 0;
  const currencyCode = cart?.cost?.subtotalAmount?.currencyCode ?? 'USD';

  const shippingProgress = Math.min(
    100,
    (subtotal / FREE_SHIP_THRESHOLD) * 100,
  );

  let progressMessage: React.ReactNode;
  if (subtotal >= FREE_GIFT_THRESHOLD) {
    progressMessage = (
      <>
        You unlocked <strong>free shipping</strong> and a{' '}
        <strong>free gift</strong>!
      </>
    );
  } else if (subtotal >= FREE_SHIP_THRESHOLD) {
    progressMessage = (
      <>
        Free shipping unlocked! Add{' '}
        <strong>
          <Money
            data={{
              amount: (FREE_GIFT_THRESHOLD - subtotal).toFixed(2),
              currencyCode,
            }}
          />
        </strong>{' '}
        more for a free gift.
      </>
    );
  } else {
    progressMessage = (
      <>
        Add{' '}
        <strong>
          <Money
            data={{
              amount: (FREE_SHIP_THRESHOLD - subtotal).toFixed(2),
              currencyCode,
            }}
          />
        </strong>{' '}
        more for free shipping.
      </>
    );
  }

  return (
    <section
      className={`cart-drawer ${hasItems ? '' : 'is-empty'}`}
      aria-label={layout === 'page' ? 'Cart page' : 'Cart drawer'}
    >
      <div className="cart-progress">
        <div className="cart-progress-message">{progressMessage}</div>
        <div className="cart-progress-track" aria-hidden="true">
          <div
            className="cart-progress-fill"
            style={{width: `${shippingProgress}%`}}
          />
        </div>
        <div className="cart-progress-labels" aria-hidden="true">
          <span>
            ${FREE_SHIP_THRESHOLD} · Free shipping
            {subtotal >= FREE_SHIP_THRESHOLD ? ' ✓' : ''}
          </span>
          <span>
            ${FREE_GIFT_THRESHOLD} · Free gift
            {subtotal >= FREE_GIFT_THRESHOLD ? ' ✓' : ''}
          </span>
        </div>
      </div>

      <div className="cart-drawer-body">
        {hasItems ? (
          <ul className="cart-line-list" aria-label="Cart items">
            {visibleLines.map((line) => (
              <CartLineItem
                key={line.id}
                line={line}
                layout={layout}
                childrenMap={childrenMap}
              />
            ))}
          </ul>
        ) : (
          <CartEmpty />
        )}
      </div>

      {hasItems && <CartSummary cart={cart} layout={layout} />}
    </section>
  );
}

function CartEmpty() {
  const {close} = useAside();
  return (
    <div className="cart-empty">
      <p className="cart-empty-message">
        Your cart is empty. Start with the pieces home cooks reach for most.
      </p>
      <Link
        to="/collections/best-sellers"
        onClick={close}
        prefetch="viewport"
        className="cart-empty-cta"
      >
        Shop best sellers
      </Link>
    </div>
  );
}
