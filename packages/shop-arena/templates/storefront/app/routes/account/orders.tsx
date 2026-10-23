import { type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { AccountNav, OrderTable } from '~/components/account';
import { getAppContext, getCustomerAccessToken } from '~/lib/context';
import { requireCustomer } from '~/lib/customer';
import { CUSTOMER_ORDERS_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Customer, OrderSummary } from '~/lib/types';

interface CustomerOrdersData {
  readonly customer:
    | (Customer & {
        readonly orders: {
          readonly totalCount: number;
          readonly nodes: readonly OrderSummary[];
        };
      })
    | null;
}

const MAX_ORDERS = 100;

export function meta() {
  return [{ title: 'Orders' }];
}

export async function loader({ context, request }: LoaderFunctionArgs) {
  const appContext = getAppContext(context);
  await requireCustomer(appContext, request);
  const data = await storefrontQuery<CustomerOrdersData>(appContext, CUSTOMER_ORDERS_QUERY, {
    customerAccessToken: getCustomerAccessToken(appContext),
    first: MAX_ORDERS,
  });
  return {
    orders: data.customer?.orders.nodes ?? [],
    totalCount: data.customer?.orders.totalCount ?? 0,
  };
}

export default function OrdersRoute() {
  const { orders, totalCount } = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <h1>Orders</h1>
      <AccountNav />
      <p className="muted">
        {totalCount} {totalCount === 1 ? 'order' : 'orders'}
      </p>
      <OrderTable orders={orders} />
    </div>
  );
}
