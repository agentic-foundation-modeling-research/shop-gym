import type {CartApiQueryFragment} from 'storefrontapi.generated';
import {CartForm, Money, type OptimisticCart} from '@shopify/hydrogen';
import {useId, useState} from 'react';

const SHOP_PAY_INSTALLMENT_THRESHOLD = 50;

type CartSummaryProps = {
  cart: OptimisticCart<CartApiQueryFragment | null>;
};

export function CartSummary({cart}: CartSummaryProps) {
  const summaryId = useId();
  const checkoutUrl = '/checkout';
  const totalAmount = cart?.cost?.totalAmount;
  const totalAmountValue = totalAmount?.amount
    ? parseFloat(totalAmount.amount)
    : 0;
  const showInstallments = totalAmountValue >= SHOP_PAY_INSTALLMENT_THRESHOLD;

  return (
    <aside className="cart-summary" aria-labelledby={summaryId}>
      <CartDiscount discountCodes={cart?.discountCodes} />

      <div className="cart-summary-divider" aria-hidden="true" />

      <h2 id={summaryId} className="cart-summary-heading">
        Order summary
      </h2>

      <dl className="cart-summary-row cart-summary-total-row">
        <dt>Estimated total</dt>
        <dd>
          {totalAmount?.amount ? (
            <>
              <Money data={totalAmount} />{' '}
              <span className="cart-summary-currency">
                {totalAmount.currencyCode}
              </span>
            </>
          ) : (
            '—'
          )}
        </dd>
      </dl>

      {showInstallments ? (
        <p className="cart-summary-installments">
          Pay in 4 interest-free installments with{' '}
          <strong>Shop Pay</strong>.{' '}
          <a
            href="https://shop.app/pay/installments"
            className="cart-summary-installments-link"
            target="_blank"
            rel="noreferrer"
          >
            Learn more
          </a>
        </p>
      ) : null}

      <p className="cart-summary-tax-note">
        Taxes and shipping calculated at checkout.
      </p>

      <a href={checkoutUrl} className="cart-checkout-button" target="_self">
        Check out
      </a>
    </aside>
  );
}

function CartDiscount({
  discountCodes,
}: {
  discountCodes?: CartApiQueryFragment['discountCodes'];
}) {
  const inputId = useId();
  const codes: string[] =
    discountCodes
      ?.filter((discount) => discount.applicable)
      ?.map(({code}) => code) ?? [];
  const [open, setOpen] = useState(codes.length > 0);

  return (
    <details
      className="cart-discount"
      open={open}
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}
    >
      <summary className="cart-discount-summary">
        <span>Discount</span>
        <svg
          className="cart-discount-chevron"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </summary>

      <div className="cart-discount-body">
        {codes.length > 0 ? (
          <UpdateDiscountForm>
            <div className="cart-discount-applied">
              <code className="cart-discount-code">{codes.join(', ')}</code>
              <button
                type="submit"
                className="cart-discount-remove"
                aria-label="Remove discount"
              >
                Remove
              </button>
            </div>
          </UpdateDiscountForm>
        ) : null}

        <UpdateDiscountForm discountCodes={codes}>
          <div className="cart-discount-form">
            <label htmlFor={inputId} className="sr-only">
              Discount code
            </label>
            <input
              id={inputId}
              className="cart-discount-input"
              type="text"
              name="discountCode"
              placeholder="Discount code"
            />
            <button type="submit" className="cart-discount-apply">
              Apply
            </button>
          </div>
        </UpdateDiscountForm>
      </div>
    </details>
  );
}

function UpdateDiscountForm({
  discountCodes,
  children,
}: {
  discountCodes?: string[];
  children: React.ReactNode;
}) {
  return (
    <CartForm
      route="/cart"
      action={CartForm.ACTIONS.DiscountCodesUpdate}
      inputs={{discountCodes: discountCodes ?? []}}
    >
      {children}
    </CartForm>
  );
}
