import { Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { AccountNav, OrderDetails, orderGid } from '~/components/account';
import { getAppContext } from '~/lib/context';
import { requireCustomer } from '~/lib/customer';
import { ORDER_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { OrderDetail } from '~/lib/types';

interface OrderData {
  readonly order: OrderDetail | null;
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
  const data = await storefrontQuery<OrderData>(appContext, ORDER_QUERY, {
    id: orderGid(params.orderNumber),
  });
  const order = data.order;
  if (!order || order.email !== customer.email) {
    throw new Response('Order not found.', { status: 404 });
  }
  return { order };
}

export default function OrderRoute() {
  const { order } = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <h1>Order {order.name}</h1>
      <AccountNav />
      <OrderDetails order={order} />
      <Link to="/account/orders">Back to orders</Link>
    </div>
  );
}
