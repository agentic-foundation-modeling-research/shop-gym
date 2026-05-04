import type {CartApiQueryFragment} from 'storefrontapi.generated';
import type {CartLayout} from '~/components/CartMain';
import {Money, type OptimisticCart} from '@shopify/hydrogen';

type CartSummaryProps = {
  cart: OptimisticCart<CartApiQueryFragment | null>;
  layout: CartLayout;
};

export function CartSummary({cart}: CartSummaryProps) {
  const subtotal = cart?.cost?.subtotalAmount;
  return (
    <div className="cart-summary" aria-label="Cart summary">
      <div className="cart-gift-wrap-row" aria-hidden="true">
        <span className="cart-gift-wrap-icon">✦</span>
        <span className="cart-gift-wrap-label">Add Gift Wrapping</span>
        <span className="cart-gift-wrap-fee">+$4.00</span>
      </div>

      <div className="cart-subtotal-row">
        <span className="cart-subtotal-label">Subtotal</span>
        <span className="cart-subtotal-value">
          {subtotal?.amount ? <Money data={subtotal} /> : '—'}
        </span>
      </div>

      <a
        href="/checkout"
        className="cart-checkout-button"
        target="_self"
      >
        Checkout
        {subtotal?.amount ? (
          <>
            {' — '}
            <Money data={subtotal} />
          </>
        ) : null}
      </a>

      <div className="cart-payment-icons" aria-label="Accepted payment methods">
        <PaymentIcon label="Visa">VISA</PaymentIcon>
        <PaymentIcon label="Mastercard">MC</PaymentIcon>
        <PaymentIcon label="American Express">AMEX</PaymentIcon>
        <PaymentIcon label="PayPal">PP</PaymentIcon>
        <PaymentIcon label="Apple Pay">Pay</PaymentIcon>
      </div>

      <p className="cart-security-note">
        Secure checkout · Taxes calculated at next step
      </p>
    </div>
  );
}

function PaymentIcon({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <span className="cart-payment-icon" aria-label={label} role="img">
      {children}
    </span>
  );
}
