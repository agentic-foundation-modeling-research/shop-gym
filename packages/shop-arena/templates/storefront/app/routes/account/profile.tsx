import { Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { AccountNav, AddressBlock, OrderTable } from '~/components/account';
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

const RECENT_ORDERS = 5;

export function meta() {
  return [{ title: 'Account' }];
}

export async function loader({ context, request }: LoaderFunctionArgs) {
  const appContext = getAppContext(context);
  const customer = await requireCustomer(appContext, request);
  const data = await storefrontQuery<CustomerOrdersData>(appContext, CUSTOMER_ORDERS_QUERY, {
    customerAccessToken: getCustomerAccessToken(appContext),
    first: RECENT_ORDERS,
  });
  return { customer, orders: data.customer?.orders.nodes ?? [] };
}

export default function AccountRoute() {
  const { customer, orders } = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <h1>Account</h1>
      <AccountNav />
      <section className="stack" aria-labelledby="profile-heading">
        <h2 id="profile-heading">Profile</h2>
        <dl className="order-meta">
          <dt>Name</dt>
          <dd>{customer.displayName}</dd>
          <dt>Email</dt>
          <dd>{customer.email ?? '-'}</dd>
          <dt>Phone</dt>
          <dd>{customer.phone ?? '-'}</dd>
        </dl>
      </section>
      <section className="stack" aria-labelledby="address-heading">
        <h2 id="address-heading">Default address</h2>
        {customer.defaultAddress ? (
          <AddressBlock address={customer.defaultAddress} />
        ) : (
          <p>No default address on file.</p>
        )}
        <Link to="/account/addresses">All addresses</Link>
      </section>
      <section className="stack" aria-labelledby="orders-heading">
        <h2 id="orders-heading">Recent orders</h2>
        <OrderTable orders={orders} />
        <Link to="/account/orders">All orders</Link>
      </section>
    </div>
  );
}
