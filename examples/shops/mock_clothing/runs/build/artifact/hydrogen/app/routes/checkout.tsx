import {useLoaderData, type HeadersFunction} from 'react-router';
import {useState} from 'react';
import type {Route} from './+types/checkout';
import {Money, Image} from '@shopify/hydrogen';
import type {CartApiQueryFragment} from 'storefrontapi.generated';

export const meta: Route.MetaFunction = () => {
  return [{title: `Hydrogen | Checkout`}];
};

export const headers: HeadersFunction = ({loaderHeaders}) => loaderHeaders;

export async function loader({context}: Route.LoaderArgs) {
  const {cart} = context;
  return await cart.get();
}

type CartLine = NonNullable<CartApiQueryFragment['lines']>['nodes'][number];

export default function Checkout() {
  const cart = useLoaderData<typeof loader>();
  const [deliveryMethod, setDeliveryMethod] = useState<'ship' | 'pickup'>(
    'ship',
  );

  const lines = cart?.lines?.nodes ?? [];
  const subtotal = cart?.cost?.subtotalAmount;
  const total = cart?.cost?.totalAmount ?? subtotal;
  const itemCount = cart?.totalQuantity ?? 0;

  return (
    <div className="checkout-page">
      <div className="checkout-layout">
        <div className="checkout-form-section">
          <div className="checkout-form-inner">
            <div className="express-checkout">
              <p className="express-checkout-heading">Express checkout</p>
              <div className="express-checkout-buttons">
                <button type="button" className="express-btn express-shop">
                  shop
                </button>
                <button type="button" className="express-btn express-paypal">
                  PayPal
                </button>
                <button type="button" className="express-btn express-gpay">
                  G Pay
                </button>
                <button type="button" className="express-btn express-venmo">
                  venmo
                </button>
              </div>
              <div className="express-divider">
                <span>OR</span>
              </div>
            </div>

            <form
              className="checkout-form"
              onSubmit={(e) => e.preventDefault()}
            >
              <section className="checkout-section">
                <div className="checkout-section-header">
                  <h2 className="checkout-section-title">Contact</h2>
                  <a href="/account/login" className="checkout-signin-link">
                    Sign in
                  </a>
                </div>
                <input
                  type="email"
                  placeholder="Email"
                  className="checkout-input"
                  autoComplete="email"
                />
                <label className="checkout-checkbox-row">
                  <input type="checkbox" />
                  <span>Email me with news and offers</span>
                </label>
              </section>

              <section className="checkout-section">
                <h2 className="checkout-section-title">Delivery</h2>
                <div className="checkout-delivery-toggle">
                  <button
                    type="button"
                    onClick={() => setDeliveryMethod('ship')}
                    className={`checkout-delivery-option${deliveryMethod === 'ship' ? ' checkout-delivery-option-active' : ''}`}
                    aria-pressed={deliveryMethod === 'ship'}
                  >
                    Ship
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeliveryMethod('pickup')}
                    className={`checkout-delivery-option${deliveryMethod === 'pickup' ? ' checkout-delivery-option-active' : ''}`}
                    aria-pressed={deliveryMethod === 'pickup'}
                  >
                    Pickup
                  </button>
                </div>

                <div className="checkout-field">
                  <label className="checkout-field-label">
                    Country/Region
                  </label>
                  <select className="checkout-input checkout-select">
                    <option>United States</option>
                    <option>Canada</option>
                    <option>United Kingdom</option>
                    <option>Australia</option>
                  </select>
                </div>

                <div className="checkout-field-row">
                  <input
                    type="text"
                    placeholder="First name"
                    className="checkout-input"
                    autoComplete="given-name"
                  />
                  <input
                    type="text"
                    placeholder="Last name"
                    className="checkout-input"
                    autoComplete="family-name"
                  />
                </div>

                <input
                  type="text"
                  placeholder="Company (optional)"
                  className="checkout-input"
                  autoComplete="organization"
                />

                <input
                  type="text"
                  placeholder="Address"
                  className="checkout-input"
                  autoComplete="street-address"
                />

                <input
                  type="text"
                  placeholder="Apartment, suite, etc. (optional)"
                  className="checkout-input"
                  autoComplete="address-line2"
                />

                <div className="checkout-field-row checkout-field-row-three">
                  <input
                    type="text"
                    placeholder="City"
                    className="checkout-input"
                    autoComplete="address-level2"
                  />
                  <input
                    type="text"
                    placeholder="State"
                    className="checkout-input"
                    autoComplete="address-level1"
                  />
                  <input
                    type="text"
                    placeholder="ZIP code"
                    className="checkout-input"
                    autoComplete="postal-code"
                  />
                </div>
              </section>

              <section className="checkout-section">
                <h2 className="checkout-section-title">Payment</h2>
                <p className="checkout-section-sub">
                  All transactions are secure and encrypted.
                </p>

                <div className="checkout-payment-methods">
                  <label className="checkout-payment-option checkout-payment-option-active">
                    <input
                      type="radio"
                      name="payment"
                      defaultChecked
                      className="checkout-radio"
                    />
                    <span className="checkout-payment-label">Credit card</span>
                  </label>

                  <div className="checkout-payment-body">
                    <input
                      type="text"
                      placeholder="Card number"
                      className="checkout-input"
                      autoComplete="cc-number"
                    />
                    <div className="checkout-field-row">
                      <input
                        type="text"
                        placeholder="Expiration date (MM / YY)"
                        className="checkout-input"
                        autoComplete="cc-exp"
                      />
                      <input
                        type="text"
                        placeholder="Security code"
                        className="checkout-input"
                        autoComplete="cc-csc"
                      />
                    </div>
                    <input
                      type="text"
                      placeholder="Name on card"
                      className="checkout-input"
                      autoComplete="cc-name"
                    />
                    <label className="checkout-checkbox-row">
                      <input type="checkbox" defaultChecked />
                      <span>Use shipping address as billing address</span>
                    </label>
                  </div>

                  <label className="checkout-payment-option">
                    <input
                      type="radio"
                      name="payment"
                      className="checkout-radio"
                    />
                    <span className="checkout-payment-label">
                      Shop Pay{' '}
                      <span className="checkout-payment-sub">
                        · Pay in full or in installments
                      </span>
                    </span>
                  </label>

                  <label className="checkout-payment-option">
                    <input
                      type="radio"
                      name="payment"
                      className="checkout-radio"
                    />
                    <span className="checkout-payment-label">PayPal</span>
                  </label>
                </div>
              </section>

              <button
                type="submit"
                className="checkout-pay-button"
                aria-label="Pay now"
              >
                Pay now
              </button>
            </form>
          </div>
        </div>

        <aside className="checkout-summary-section">
          <div className="checkout-summary-inner">
            <ul className="checkout-order-items">
              {lines.map((line: CartLine) => (
                <OrderLineItem key={line.id} line={line} />
              ))}
            </ul>

            <div className="checkout-discount">
              <input
                type="text"
                placeholder="Discount code or gift card"
                className="checkout-input"
              />
              <button type="button" className="checkout-apply-button">
                Apply
              </button>
            </div>

            <div className="checkout-totals">
              <div className="checkout-total-row">
                <span>Subtotal · {itemCount} items</span>
                <span>{subtotal ? <Money data={subtotal} /> : '—'}</span>
              </div>
              <div className="checkout-total-row">
                <span>Shipping</span>
                <span className="checkout-total-muted">
                  Enter shipping address
                </span>
              </div>
              <div className="checkout-total-row checkout-total-row-grand">
                <span>Total</span>
                <span>
                  <span className="checkout-total-currency">USD</span>{' '}
                  {total ? <Money data={total} /> : '—'}
                </span>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function OrderLineItem({line}: {line: CartLine}) {
  const {merchandise, quantity, cost} = line;
  const {product, title, image, selectedOptions} = merchandise;
  const hasVariant = selectedOptions.some(
    (o) => o.value && o.value !== 'Default Title',
  );

  return (
    <li className="checkout-order-item">
      <div className="checkout-order-item-image-wrap">
        {image ? (
          <Image
            alt={title}
            aspectRatio="1/1"
            data={image}
            height={64}
            loading="lazy"
            width={64}
            className="checkout-order-item-image"
          />
        ) : (
          <div className="checkout-order-item-placeholder" />
        )}
        <span className="checkout-order-item-qty">{quantity}</span>
      </div>
      <div className="checkout-order-item-details">
        <p className="checkout-order-item-title">{product.title}</p>
        {hasVariant ? (
          <p className="checkout-order-item-variant">
            {selectedOptions
              .filter((o) => o.value !== 'Default Title')
              .map((o) => o.value)
              .join(' / ')}
          </p>
        ) : null}
      </div>
      <div className="checkout-order-item-price">
        {cost?.totalAmount ? <Money data={cost.totalAmount} /> : null}
      </div>
    </li>
  );
}
