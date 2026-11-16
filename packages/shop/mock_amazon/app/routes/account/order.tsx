import { Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { OrderDetails, orderGid } from '~/components/account';
import { getAppContext } from '~/lib/context';
import { requireCustomer } from '~/lib/customer';
import { COMMERCE_SETTINGS_QUERY, ORDER_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { CommerceSettings, OrderDetail } from '~/lib/types';

interface OrderData {
  readonly order: OrderDetail | null;
}

interface CommerceSettingsData {
  readonly commerceSettings: CommerceSettings;
}

export function meta({ data }: { readonly data: { readonly order: OrderDetail } | undefined }) {
  return [{ title: data ? `Order ${data.order.name}` : 'Order' }];
}

export async function loader({ context, params, request }: LoaderFunctionArgs) {
  if (!params.orderNumber) {
    throw new Response('Missing order number.', { status: 400 });
  }
  const appContext = getAppContext(context);
  const customer = await requireCustomer(appContext, request);
  const [data, settingsData] = await Promise.all([
    storefrontQuery<OrderData>(appContext, ORDER_QUERY, { id: orderGid(params.orderNumber) }),
    storefrontQuery<CommerceSettingsData>(appContext, COMMERCE_SETTINGS_QUERY),
  ]);
  const order = data.order;
  if (!order || order.email !== customer.email) {
    throw new Response('Order not found.', { status: 404 });
  }
  const shippingMethod = settingsData.commerceSettings.shippingMethods.find(
    (method) => method.handle === order.shippingMethod,
  );
  return { order, shippingMethodTitle: shippingMethod?.title ?? order.shippingMethod ?? '-' };
}

export default function OrderRoute() {
  const { order, shippingMethodTitle } = useLoaderData<typeof loader>();
  return (
    <div className="page-width account-page">
      <div>
        <h1>Account</h1>
        <Link to="/account">Return to Account details</Link>
      </div>
      <OrderDetails order={order} shippingMethodTitle={shippingMethodTitle} />
    </div>
  );
}
