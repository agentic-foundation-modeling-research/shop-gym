import { type ReactNode, useState } from 'react';
import { DiscountRow, ImageFrame, Price } from '~/components/storefront';
import type { AppliedDiscount, Image, Money } from '~/lib/types';

export interface SummaryLine {
  readonly key: string;
  readonly image: Image | null;
  readonly quantity: number;
  readonly title: string;
  readonly variantTitle: string | null;
  readonly price: Money;
}

export interface SummaryTotals {
  readonly subtotal: Money;
  readonly discount: AppliedDiscount | null;
  readonly shipping: Money;
  readonly taxes: Money;
  readonly total: Money;
}

/**
 * The order summary column of checkout and the thank-you page: the lines,
 * an optional slot (the "Discount code" field at checkout), and the totals.
 * On a mobile screen it collapses to an "Order summary" bar with the total.
 */
export function CheckoutSummary({
  lines,
  totals,
  children,
}: {
  readonly lines: readonly SummaryLine[];
  readonly totals: SummaryTotals;
  readonly children?: ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <aside
      className={`checkout-summary${isOpen ? ' checkout-summary-open' : ''}`}
      aria-label="Order summary"
    >
      <button
        type="button"
        className="checkout-summary-toggle"
        aria-expanded={isOpen}
        aria-controls="checkout-summary-body"
        onClick={() => setIsOpen(!isOpen)}
      >
        <span>
          Order summary <span aria-hidden="true">{isOpen ? '▲' : '▼'}</span>
        </span>
        <TotalAmount money={totals.total} />
      </button>
      <div id="checkout-summary-body" className="checkout-summary-body">
        <ul className="checkout-lines">
          {lines.map((line) => (
            <li className="checkout-line" key={line.key}>
              <div className="checkout-line-image">
                <ImageFrame image={line.image} altFallback={line.title} />
                <span className="checkout-line-quantity" aria-label={`Quantity ${line.quantity}`}>
                  {line.quantity}
                </span>
              </div>
              <div>
                <p>{line.title}</p>
                {line.variantTitle ? <p className="muted">{line.variantTitle}</p> : null}
              </div>
              <Price money={line.price} />
            </li>
          ))}
        </ul>
        {children}
        <div className="checkout-totals">
          <div className="cart-total-row">
            <span>Subtotal</span>
            <Price money={totals.subtotal} />
          </div>
          {totals.discount ? <DiscountRow discount={totals.discount} /> : null}
          <div className="cart-total-row">
            <span>Shipping</span>
            <ShippingPrice money={totals.shipping} />
          </div>
          <div className="cart-total-row">
            <span>Taxes</span>
            <Price money={totals.taxes} />
          </div>
          <div className="cart-total-row checkout-total-row">
            <span>Total</span>
            <TotalAmount money={totals.total} />
          </div>
        </div>
      </div>
    </aside>
  );
}

/** A shipping charge, or "Free" when there is none. */
export function ShippingPrice({ money }: { readonly money: Money }) {
  if (Number.parseFloat(money.amount) === 0) return <span>Free</span>;
  return <Price money={money} />;
}

/** The variant title, or null for the "Default Title" of a product with one variant. */
export function variantTitle(title: string): string | null {
  return title === 'Default Title' ? null : title;
}

/** Checkout's grand total: the currency code, then the amount, e.g. "CAD $45.97". */
function TotalAmount({ money }: { readonly money: Money }) {
  return (
    <span className="checkout-total">
      <span className="checkout-total-currency">{money.currencyCode}</span>{' '}
      <Price money={money} currencyDisplay="narrowSymbol" />
    </span>
  );
}
