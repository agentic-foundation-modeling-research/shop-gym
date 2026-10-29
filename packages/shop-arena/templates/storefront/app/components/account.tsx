import type { ReactNode } from 'react';
import { Form, Link, NavLink } from 'react-router';
import { variantTitle } from '~/components/checkout';
import { DiscountAmount, Price } from '~/components/storefront';
import type { MailingAddress, Money, OrderDetail, OrderLineItem, OrderSummary } from '~/lib/types';

/** Most orders that the order history lists. */
export const ORDER_HISTORY_SIZE = 100;

export function AccountNav() {
  return (
    <nav className="account-nav" aria-label="Account navigation">
      <NavLink to="/account" end>
        Profile
      </NavLink>
      <NavLink to="/account/orders">Orders</NavLink>
      <NavLink to="/account/addresses">Addresses</NavLink>
      <Form method="post" action="/account/logout" reloadDocument>
        <button type="submit" className="text-button">
          Log out
        </button>
      </Form>
    </nav>
  );
}

/**
 * "Log out" with the account icon. It looks like a link, but it is the
 * button of a form that posts to `/account/logout`.
 */
export function LogoutLink() {
  return (
    <Form method="post" action="/account/logout" reloadDocument className="account-logout">
      <button type="submit" className="text-button">
        <svg aria-hidden="true" focusable="false" viewBox="0 0 18 19" width="18" height="18">
          <circle cx="9" cy="5.5" r="4" fill="none" stroke="currentColor" />
          <path d="M1.5 18c0-4 3.4-6.5 7.5-6.5s7.5 2.5 7.5 6.5" fill="none" stroke="currentColor" />
        </svg>
        Log out
      </button>
    </Form>
  );
}

export function FormErrors({
  errors,
}: {
  readonly errors: readonly { readonly message: string }[] | undefined;
}) {
  if (!errors || errors.length === 0) return null;
  return (
    <ul className="form-errors" role="alert">
      {errors.map((error) => (
        <li key={error.message}>{error.message}</li>
      ))}
    </ul>
  );
}

/** The address as postal lines; with `withPhone`, the phone number is the last line. */
export function AddressBlock({
  address,
  withPhone = false,
}: {
  readonly address: MailingAddress;
  readonly withPhone?: boolean;
}) {
  const lines =
    withPhone && address.phone ? [...address.formatted, address.phone] : address.formatted;
  return (
    <address className="address-block">
      {lines.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </address>
  );
}

/** The "Order history" table, newest order first, or a sentence when there are no orders. */
export function OrderHistory({ orders }: { readonly orders: readonly OrderSummary[] }) {
  if (orders.length === 0) {
    return <p>You haven't placed any orders yet.</p>;
  }
  return (
    <table className="data-table responsive-table">
      <thead>
        <tr>
          <th scope="col">Order</th>
          <th scope="col">Date</th>
          <th scope="col">Payment status</th>
          <th scope="col">Fulfillment status</th>
          <th scope="col">Total</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((order) => (
          <tr key={order.id}>
            <td data-label="Order">
              <Link to={orderPath(order)} aria-label={`Order number ${order.name}`}>
                {order.name}
              </Link>
            </td>
            <td data-label="Date">{formatDate(order.processedAt)}</td>
            <td data-label="Payment status">{statusLabel(order.financialStatus)}</td>
            <td data-label="Fulfillment status">{statusLabel(order.fulfillmentStatus)}</td>
            <td data-label="Total">
              <PriceWithCurrency money={order.totalPrice} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * One order: its lines and totals on the left, its billing and shipping
 * addresses with the payment and fulfillment statuses on the right. The
 * billing address is the shipping address.
 */
export function OrderDetails({
  order,
  shippingMethodTitle,
}: {
  readonly order: OrderDetail;
  readonly shippingMethodTitle: string;
}) {
  const zero = { amount: '0.00', currencyCode: order.totalPrice.currencyCode };
  const address = order.shippingAddress ? <AddressBlock address={order.shippingAddress} /> : null;
  return (
    <div className="account-columns">
      <section className="stack" aria-labelledby="order-heading">
        <div>
          <h2 id="order-heading">Order {order.name}</h2>
          <p>Placed on {formatDateTime(order.processedAt)}</p>
        </div>
        <table className="data-table responsive-table">
          <thead>
            <tr>
              <th scope="col">Product</th>
              <th scope="col">SKU</th>
              <th scope="col">Price</th>
              <th scope="col">Quantity</th>
              <th scope="col">Total</th>
            </tr>
          </thead>
          <tbody>
            {order.lineItems.nodes.map((line, index) => {
              const variantName = line.variant ? variantTitle(line.variant.title) : null;
              return (
                <tr key={`${index}-${line.variant?.id ?? line.title}`}>
                  <td data-label="Product">
                    <div>
                      {line.variant ? (
                        <Link to={`/products/${line.variant.product.handle}`}>
                          {line.variant.product.title}
                        </Link>
                      ) : (
                        line.title
                      )}
                      {variantName ? <div className="muted">{variantName}</div> : null}
                    </div>
                  </td>
                  <td data-label="SKU">{line.variant?.sku ?? ''}</td>
                  <td data-label="Price">
                    <Amount money={unitPrice(line)} />
                  </td>
                  <td data-label="Quantity">{line.quantity}</td>
                  <td data-label="Total">
                    <Amount money={line.originalTotalPrice} />
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <TotalRow label="Subtotal">
              <Amount money={order.subtotalPrice ?? zero} />
            </TotalRow>
            {order.discountCode ? (
              <TotalRow label="Discount">
                <DiscountAmount discount={order.discountCode} currencyDisplay="narrowSymbol" />
              </TotalRow>
            ) : null}
            <TotalRow label={`Shipping (${shippingMethodTitle})`}>
              <Amount money={order.totalShippingPrice} />
            </TotalRow>
            <TotalRow label="Tax">
              <Amount money={order.totalTax ?? zero} />
            </TotalRow>
            <TotalRow label="Total">
              <PriceWithCurrency money={order.totalPrice} />
            </TotalRow>
          </tfoot>
        </table>
      </section>
      <aside className="stack" aria-label="Order addresses">
        <section className="stack">
          <h2>Billing Address</h2>
          <p>Payment Status: {statusLabel(order.financialStatus)}</p>
          {address}
        </section>
        <section className="stack">
          <h2>Shipping Address</h2>
          <p>Fulfillment Status: {statusLabel(order.fulfillmentStatus)}</p>
          {address}
        </section>
      </aside>
    </div>
  );
}

function TotalRow({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <tr>
      <th scope="row" colSpan={4}>
        {label}
      </th>
      <td>{children}</td>
    </tr>
  );
}

/** An amount with the narrow currency symbol, e.g. "$58.00". */
function Amount({ money }: { readonly money: Money }) {
  return <Price money={money} currencyDisplay="narrowSymbol" />;
}

/** An amount followed by its currency code, e.g. "$58.00 USD". */
function PriceWithCurrency({ money }: { readonly money: Money }) {
  return (
    <span>
      <Amount money={money} /> {money.currencyCode}
    </span>
  );
}

/** Unit price of an order line: the line total over the quantity. */
function unitPrice(line: OrderLineItem): Money {
  const totalCents = Math.round(Number.parseFloat(line.originalTotalPrice.amount) * 100);
  return {
    amount: (totalCents / line.quantity / 100).toFixed(2),
    currencyCode: line.originalTotalPrice.currencyCode,
  };
}

/** A status such as `PARTIALLY_REFUNDED` in sentence case: "Partially refunded". */
function statusLabel(status: string | null): string {
  if (status === null) return '';
  const words = status.toLowerCase().replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function orderPath(order: { readonly orderNumber: number }): string {
  return `/account/orders/${order.orderNumber}`;
}

/** Storefront order id for the `:orderNumber` route param. */
export function orderGid(orderNumber: string): string {
  return `gid://shopify/Order/${orderNumber}`;
}

// Dates and times are in UTC: the sandbox has no shop time zone, and the
// server and the browser must render the same text.

/** "March 3, 2025", in UTC. */
export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(iso));
}

/** "March 3, 2025 at 2:15 pm". */
function formatDateTime(iso: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'UTC',
  }).formatToParts(new Date(iso));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? '';
  return `${formatDate(iso)} at ${part('hour')}:${part('minute')} ${part('dayPeriod').toLowerCase()}`;
}
