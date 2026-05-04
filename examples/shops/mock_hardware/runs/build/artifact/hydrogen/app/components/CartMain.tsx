import {useOptimisticCart} from '@shopify/hydrogen';
import {Link} from 'react-router';
import type {CartApiQueryFragment} from 'storefrontapi.generated';
import {CartLineItem, type CartLine} from '~/components/CartLineItem';
import {CartSummary} from './CartSummary';

export type CartLayout = 'page' | 'aside';

export type CartMainProps = {
  cart: CartApiQueryFragment | null;
  layout: CartLayout;
};

export type LineItemChildrenMap = {[parentId: string]: CartLine[]};

function getLineItemChildrenMap(lines: CartLine[]): LineItemChildrenMap {
  const childrenMap: LineItemChildrenMap = {};
  for (const line of lines) {
    if ('parentRelationship' in line && line.parentRelationship?.parent) {
      const parentId = line.parentRelationship.parent.id;
      if (!childrenMap[parentId]) childrenMap[parentId] = [];
      childrenMap[parentId].push(line);
    }
  }
  return childrenMap;
}

/**
 * Full-page cart layout for /cart route. Renders the line items as a
 * table and the order summary below, matching the reference shop manual.
 */
export function CartMain({cart: originalCart}: CartMainProps) {
  const cart = useOptimisticCart(originalCart);
  const lines = cart?.lines?.nodes ?? [];
  const childrenMap = getLineItemChildrenMap(lines);
  const totalQuantity = cart?.totalQuantity ?? 0;
  const cartHasItems = totalQuantity > 0;

  return (
    <section className="cart-page" aria-label="Cart page">
      <p className="cart-processing-note">
        Orders are processed within 1–2 business days, excluding weekends and
        holidays.
      </p>

      {!cartHasItems ? (
        <CartEmpty />
      ) : (
        <>
          <h1 className="cart-page-heading">
            Cart <span aria-hidden="true">·</span>{' '}
            <span className="cart-page-count">{totalQuantity}</span>
            <span className="sr-only"> items</span>
          </h1>

          <div className="cart-page-grid">
            <div className="cart-page-table-wrapper">
              <table className="cart-table">
                <thead>
                  <tr>
                    <th scope="col" className="cart-table-th-image">
                      <span className="sr-only">Product image</span>
                    </th>
                    <th scope="col" className="cart-table-th-product">
                      Product
                    </th>
                    <th scope="col" className="cart-table-th-qty">
                      Quantity
                    </th>
                    <th scope="col" className="cart-table-th-total">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody>
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
                        childrenMap={childrenMap}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>

            <CartSummary cart={cart} />
          </div>
        </>
      )}
    </section>
  );
}

function CartEmpty() {
  return (
    <div className="cart-empty">
      <h1 className="cart-empty-heading">Your cart is empty</h1>
      <Link to="/collections" className="cart-empty-link" prefetch="intent">
        Continue shopping
      </Link>
    </div>
  );
}
