import {useOptimisticCart} from '@shopify/hydrogen';
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

const FREE_SHIPPING_THRESHOLD = 75;
const PROMO_BANNER_TEXT = 'Use code WELCOME20 for 20% off your first order';

export function CartMain({layout, cart: originalCart}: CartMainProps) {
  const cart = useOptimisticCart(originalCart);
  const {close} = useAside();
  const lines = cart?.lines?.nodes ?? [];
  const itemCount = cart?.totalQuantity ?? 0;
  const cartHasItems = itemCount > 0;
  const childrenMap = getLineItemChildrenMap(lines);
  const subtotalAmount = Number(cart?.cost?.subtotalAmount?.amount ?? 0);
  const currencyCode = cart?.cost?.subtotalAmount?.currencyCode ?? 'USD';
  const remaining = Math.max(0, FREE_SHIPPING_THRESHOLD - subtotalAmount);
  const progressPct = Math.min(
    100,
    (subtotalAmount / FREE_SHIPPING_THRESHOLD) * 100,
  );

  return (
    <section
      className={`cart-drawer cart-drawer-${layout}`}
      aria-label={layout === 'page' ? 'Cart page' : 'Cart drawer'}
    >
      {layout === 'aside' ? (
        <div className="cart-drawer-header">
          <h3 className="cart-drawer-heading">
            Your Bag ({itemCount} {itemCount === 1 ? 'item' : 'items'})
          </h3>
          <button
            type="button"
            className="cart-drawer-close"
            aria-label="Close cart"
            onClick={close}
          >
            ×
          </button>
        </div>
      ) : (
        <p className="cart-page-itemcount">
          {itemCount} {itemCount === 1 ? 'item' : 'items'}
        </p>
      )}

      {!cartHasItems ? (
        <CartEmpty />
      ) : (
        <>
          <div className="cart-promo-banner">{PROMO_BANNER_TEXT}</div>

          <CartFreeShippingBar
            progressPct={progressPct}
            remaining={remaining}
            currencyCode={currencyCode}
          />

          <ul className="cart-line-list" aria-label="Cart line items">
            {lines.map((line) => {
              if (
                'parentRelationship' in line &&
                line.parentRelationship?.parent
              ) {
                return null;
              }
              return (
                <CartLineItem
                  key={line.id}
                  line={line}
                  layout={layout}
                  childrenMap={childrenMap}
                />
              );
            })}
          </ul>

          <CartSummary cart={cart} layout={layout} />
        </>
      )}
    </section>
  );
}

function CartFreeShippingBar({
  progressPct,
  remaining,
  currencyCode,
}: {
  progressPct: number;
  remaining: number;
  currencyCode: string;
}) {
  const symbol = currencySymbol(currencyCode);
  const unlocked = remaining <= 0;
  return (
    <div className="cart-shipping-bar" aria-live="polite">
      <div className="cart-shipping-track">
        <div
          className="cart-shipping-fill"
          style={{width: `${progressPct}%`}}
        />
      </div>
      <p className="cart-shipping-label">
        {unlocked
          ? "You've unlocked free shipping 🎉"
          : `Add ${symbol}${remaining.toFixed(2)} more for free shipping`}
      </p>
    </div>
  );
}

function currencySymbol(code: string): string {
  switch (code) {
    case 'GBP':
      return '£';
    case 'EUR':
      return '€';
    case 'USD':
    case 'CAD':
    case 'AUD':
    default:
      return '$';
  }
}

function CartEmpty() {
  const {close} = useAside();
  return (
    <div className="cart-empty">
      <h4 className="cart-empty-heading">Your bag is empty</h4>
      <p className="cart-empty-body">
        Looks like you haven&rsquo;t added anything yet.
      </p>
      <Link
        to="/collections"
        onClick={close}
        prefetch="viewport"
        className="cart-empty-cta"
      >
        Continue Shopping
      </Link>
    </div>
  );
}
