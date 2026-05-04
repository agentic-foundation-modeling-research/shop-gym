import type {CartApiQueryFragment} from 'storefrontapi.generated';
import type {CartLayout} from '~/components/CartMain';
import {Money, type OptimisticCart} from '@shopify/hydrogen';
import {useId} from 'react';

type CartSummaryProps = {
  cart: OptimisticCart<CartApiQueryFragment | null>;
  layout: CartLayout;
};

export function CartSummary({cart, layout}: CartSummaryProps) {
  const summaryId = useId();


  const itemCount = cart?.totalQuantity ?? 0;
  const subtotal = cart?.cost?.subtotalAmount;
  const currencyCode = subtotal?.currencyCode ?? 'USD';

  const lines = cart?.lines?.nodes ?? [];
  const visibleLines = lines.filter(
    (line) =>
      !('parentRelationship' in line && line.parentRelationship?.parent),
  );

  let listSubtotal = 0;
  let savings = 0;
  for (const line of visibleLines) {
    const qty = line.quantity ?? 1;
    const compareAt = line.merchandise?.compareAtPrice?.amount;
    const price = line.merchandise?.price?.amount;
    if (compareAt && price) {
      listSubtotal += parseFloat(compareAt) * qty;
      savings += (parseFloat(compareAt) - parseFloat(price)) * qty;
    } else if (price) {
      listSubtotal += parseFloat(price) * qty;
    }
  }

  const subtotalNumber = subtotal?.amount ? parseFloat(subtotal.amount) : 0;
  const installment = (subtotalNumber / 4).toFixed(2);

  const checkoutHref = '/checkout';

  return (
    <div
      className={`cart-summary cart-summary-${layout}`}
      aria-labelledby={summaryId}
    >
      <h4 id={summaryId} className="cart-summary-heading">
        Order summary
      </h4>

      <dl className="cart-summary-rows">
        <div className="cart-summary-row">
          <dt>
            Items <span className="cart-summary-count">({itemCount})</span>
          </dt>
          <dd>
            <Money
              data={{amount: listSubtotal.toFixed(2), currencyCode}}
            />
          </dd>
        </div>
        {savings > 0 ? (
          <div className="cart-summary-row cart-summary-savings">
            <dt>You save</dt>
            <dd>
              −
              <Money data={{amount: savings.toFixed(2), currencyCode}} />
            </dd>
          </div>
        ) : null}
        <div className="cart-summary-row cart-summary-subtotal">
          <dt>Subtotal</dt>
          <dd>{subtotal ? <Money data={subtotal} /> : '—'}</dd>
        </div>
      </dl>

      <div className="cart-summary-installments">
        Or 4 interest-free payments of{' '}
        <strong>
          <Money data={{amount: installment, currencyCode}} />
        </strong>{' '}
        with <span className="cart-summary-bnpl">Affirm</span>.
      </div>

      <p className="cart-summary-discount-notice">
        Discount codes can be entered at checkout.
      </p>

      <a
        className="cart-checkout-button"
        href={checkoutHref}
        target="_self"
      >
        <span>Checkout</span>
        <span className="cart-checkout-amount">
          {subtotal ? <Money data={subtotal} /> : '—'}
        </span>
      </a>

      <ul className="cart-trust-badges" aria-label="Shopping guarantees">
        <li>
          <span aria-hidden="true">⌛</span>
          Lifetime warranty
        </li>
        <li>
          <span aria-hidden="true">🚚</span>
          Free shipping over $75
        </li>
        <li>
          <span aria-hidden="true">↩</span>
          30-day returns
        </li>
      </ul>
    </div>
  );
}
