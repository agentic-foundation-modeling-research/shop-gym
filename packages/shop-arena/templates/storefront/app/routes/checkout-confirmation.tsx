import { Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { AddressBlock, orderDiscount, orderGid } from '~/components/account';
import { CheckoutSummary, variantTitle } from '~/components/checkout';
import { getAppContext } from '~/lib/context';
import { COMMERCE_SETTINGS_QUERY, ORDER_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { CommerceSettings, OrderDetail } from '~/lib/types';

interface OrderData {
  readonly order: OrderDetail | null;
}

interface CommerceSettingsData {
  readonly commerceSettings: CommerceSettings;
}

export function meta() {
  return [{ title: 'Thank you' }];
}

export async function loader({ context, params }: LoaderFunctionArgs) {
  if (!params.orderNumber) {
    throw new Response('Missing order number.', { status: 400 });
  }
  const appContext = getAppContext(context);
  const [data, settingsData] = await Promise.all([
    storefrontQuery<OrderData>(appContext, ORDER_QUERY, { id: orderGid(params.orderNumber) }),
    storefrontQuery<CommerceSettingsData>(appContext, COMMERCE_SETTINGS_QUERY),
  ]);
  if (!data.order) {
    throw new Response('Order not found.', { status: 404 });
  }
  return { order: data.order, settings: settingsData.commerceSettings };
}

export default function CheckoutConfirmationRoute() {
  const { order, settings } = useLoaderData<typeof loader>();
  const firstName = order.shippingAddress?.firstName;
  const currencyCode = order.totalPrice.currencyCode;
  const shippingMethod = settings.shippingMethods.find(
    (method) => method.handle === order.shippingMethod,
  );
  const paymentMethod = settings.paymentMethods.find(
    (method) => method.handle === order.paymentMethod,
  );
  return (
    <div className="page-width checkout-page">
      <CheckoutSummary
        lines={order.lineItems.nodes.map((line, index) => ({
          key: `${index}-${line.variant?.id ?? line.title}`,
          image: line.variant?.image ?? null,
          quantity: line.quantity,
          // An order line title is "<product> - <variant>"; the summary shows the two apart.
          title: line.variant?.product.title ?? line.title,
          variantTitle: line.variant ? variantTitle(line.variant.title) : null,
          price: line.originalTotalPrice,
        }))}
        totals={{
          subtotal: order.subtotalPrice ?? { amount: '0.00', currencyCode },
          discount: orderDiscount(order),
          shipping: order.totalShippingPrice,
          taxes: order.totalTax ?? { amount: '0.00', currencyCode },
          total: order.totalPrice,
        }}
      />
      <section className="stack checkout-form" aria-labelledby="thank-you-heading">
        <div className="thank-you-header">
          <span className="thank-you-check" aria-hidden="true">
            ✓
          </span>
          <div>
            <p className="muted thank-you-confirmation">Confirmation #{order.orderNumber}</p>
            <h1 id="thank-you-heading">{firstName ? `Thank you, ${firstName}!` : 'Thank you!'}</h1>
          </div>
        </div>
        <section className="thank-you-details stack" aria-labelledby="order-details-heading">
          <h2 id="order-details-heading">Order details</h2>
          <div className="thank-you-detail-grid">
            <div>
              <h3>Contact information</h3>
              <p>{order.email ?? '-'}</p>
            </div>
            <div>
              <h3>Shipping address</h3>
              {order.shippingAddress ? <AddressBlock address={order.shippingAddress} /> : <p>-</p>}
            </div>
            <div>
              <h3>Billing address</h3>
              {order.shippingAddress ? <AddressBlock address={order.shippingAddress} /> : <p>-</p>}
            </div>
            <div>
              <h3>Shipping method</h3>
              <p>{shippingMethod?.title ?? order.shippingMethod ?? '-'}</p>
            </div>
            <div>
              <h3>Payment method</h3>
              <p>{paymentMethod?.title ?? order.paymentMethod ?? '-'}</p>
            </div>
          </div>
        </section>
        <div className="checkout-actions">
          <Link className="button-link" to="/">
            Continue shopping
          </Link>
        </div>
      </section>
    </div>
  );
}
