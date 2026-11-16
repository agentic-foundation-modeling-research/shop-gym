import { Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { ORDER_HISTORY_SIZE, OrderHistory } from '~/components/account';
import { getAppContext, getCustomerAccessToken } from '~/lib/context';
import { requireCustomer } from '~/lib/customer';
import { CUSTOMER_ORDERS_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { OrderSummary } from '~/lib/types';

interface CustomerOrdersData {
  readonly customer: {
    readonly orders: { readonly nodes: readonly OrderSummary[] };
  } | null;
}

export function meta() {
  return [{ title: 'Order history' }];
}

export async function loader({ context, request }: LoaderFunctionArgs) {
  const appContext = getAppContext(context);
  await requireCustomer(appContext, request);
  const data = await storefrontQuery<CustomerOrdersData>(appContext, CUSTOMER_ORDERS_QUERY, {
    customerAccessToken: getCustomerAccessToken(appContext),
    first: ORDER_HISTORY_SIZE,
  });
  return { orders: data.customer?.orders.nodes ?? [] };
}

export default function OrdersRoute() {
  const { orders } = useLoaderData<typeof loader>();
  return (
    <div className="page-width account-page">
      <div>
        <h1>Account</h1>
        <Link to="/account">Return to Account details</Link>
      </div>
      <section className="stack" aria-labelledby="order-history-heading">
        <h2 id="order-history-heading">Order history</h2>
        <OrderHistory orders={orders} />
      </section>
    </div>
  );
}
