import { Form, Link, NavLink } from 'react-router';
import { Price } from '~/components/storefront';
import type { MailingAddress, OrderDetail, OrderSummary } from '~/lib/types';

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

export function AddressBlock({ address }: { readonly address: MailingAddress }) {
  return (
    <address className="address-block">
      {address.formatted.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </address>
  );
}

export function OrderTable({
  orders,
}: {
  readonly orders: readonly OrderSummary[];
}) {
  if (orders.length === 0) {
    return <p>No orders yet.</p>;
  }
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Order</th>
          <th>Date</th>
          <th>Payment</th>
          <th>Fulfillment</th>
          <th>Total</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((order) => (
          <tr key={order.id}>
            <td>
              <Link to={orderPath(order)}>{order.name}</Link>
            </td>
            <td>{formatDate(order.processedAt)}</td>
            <td>{order.financialStatus ?? '-'}</td>
            <td>{order.fulfillmentStatus}</td>
            <td>
              <Price money={order.totalPrice} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function OrderDetails({ order }: { readonly order: OrderDetail }) {
  return (
    <div className="order-detail">
      <section className="stack" aria-label="Order items">
        <p className="muted">
          Placed {formatDate(order.processedAt)}
          {order.email ? ` for ${order.email}` : ''}
        </p>
        <table className="data-table">
          <thead>
            <tr>
              <th>Item</th>
              <th>Quantity</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            {order.lineItems.nodes.map((line) => (
              <tr key={`${line.title}-${line.variant?.id ?? ''}`}>
                <td>
                  {line.variant ? (
                    <Link to={`/products/${line.variant.product.handle}`}>{line.title}</Link>
                  ) : (
                    line.title
                  )}
                </td>
                <td>{line.quantity}</td>
                <td>
                  <Price money={line.originalTotalPrice} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <dl className="order-meta">
          <dt>Payment</dt>
          <dd>
            {order.financialStatus ?? '-'}
            {order.paymentMethod ? ` (${order.paymentMethod})` : ''}
          </dd>
          <dt>Fulfillment</dt>
          <dd>
            {order.fulfillmentStatus}
            {order.shippingMethod ? ` (${order.shippingMethod})` : ''}
          </dd>
        </dl>
        {order.shippingAddress ? (
          <section className="stack">
            <h2>Shipping address</h2>
            <AddressBlock address={order.shippingAddress} />
          </section>
        ) : null}
      </section>
      <aside className="checkout-summary" aria-label="Order totals">
        {order.subtotalPrice ? (
          <div className="cart-total-row">
            <span>Subtotal</span>
            <Price money={order.subtotalPrice} />
          </div>
        ) : null}
        <div className="cart-total-row">
          <span>Shipping</span>
          <Price money={order.totalShippingPrice} />
        </div>
        {order.totalTax ? (
          <div className="cart-total-row">
            <span>Tax</span>
            <Price money={order.totalTax} />
          </div>
        ) : null}
        <div className="cart-total-row cart-total-row-grand">
          <span>Total</span>
          <Price money={order.totalPrice} />
        </div>
      </aside>
    </div>
  );
}

export function orderPath(order: { readonly orderNumber: number }): string {
  return `/account/orders/${order.orderNumber}`;
}

/** Storefront order id for the `:orderNumber` route param. */
export function orderGid(orderNumber: string): string {
  return `gid://shopify/Order/${orderNumber}`;
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toISOString().slice(0, 10);
}
