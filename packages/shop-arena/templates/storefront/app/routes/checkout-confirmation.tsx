import { Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { OrderDetails, orderGid } from '~/components/account';
import { getAppContext } from '~/lib/context';
import { ORDER_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { OrderDetail } from '~/lib/types';

interface OrderData {
  readonly order: OrderDetail | null;
}

export function meta() {
  return [{ title: 'Order confirmed' }];
}

export async function loader({ context, params }: LoaderFunctionArgs) {
  if (!params.orderNumber) {
    throw new Response('Missing order number.', { status: 400 });
  }
  const data = await storefrontQuery<OrderData>(getAppContext(context), ORDER_QUERY, {
    id: orderGid(params.orderNumber),
  });
  if (!data.order) {
    throw new Response('Order not found.', { status: 404 });
  }
  return { order: data.order };
}

export default function CheckoutConfirmationRoute() {
  const { order } = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <p className="eyebrow">Order confirmed</p>
      <h1>Thank you, your order {order.name} is confirmed</h1>
      <OrderDetails order={order} />
      <Link to="/collections">Continue shopping</Link>
    </div>
  );
}
