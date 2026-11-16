import { Link, type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { AddressBlock, LogoutLink, ORDER_HISTORY_SIZE, OrderHistory } from '~/components/account';
import { getAppContext, getCustomerAccessToken } from '~/lib/context';
import { requireCustomer } from '~/lib/customer';
import { CUSTOMER_ADDRESSES_QUERY, CUSTOMER_ORDERS_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { MailingAddress, OrderSummary } from '~/lib/types';

interface CustomerOrdersData {
  readonly customer: {
    readonly orders: { readonly nodes: readonly OrderSummary[] };
  } | null;
}

interface CustomerAddressesData {
  readonly customer: {
    readonly addresses: { readonly nodes: readonly MailingAddress[] };
  } | null;
}

export function meta() {
  return [{ title: 'Account' }];
}

export async function loader({ context, request }: LoaderFunctionArgs) {
  const appContext = getAppContext(context);
  const customer = await requireCustomer(appContext, request);
  const customerAccessToken = getCustomerAccessToken(appContext);
  const [ordersData, addressesData] = await Promise.all([
    storefrontQuery<CustomerOrdersData>(appContext, CUSTOMER_ORDERS_QUERY, {
      customerAccessToken,
      first: ORDER_HISTORY_SIZE,
    }),
    storefrontQuery<CustomerAddressesData>(appContext, CUSTOMER_ADDRESSES_QUERY, {
      customerAccessToken,
    }),
  ]);
  return {
    customer,
    addressCount: addressesData.customer?.addresses.nodes.length ?? 0,
    orders: ordersData.customer?.orders.nodes ?? [],
  };
}

export default function AccountRoute() {
  const { customer, addressCount, orders } = useLoaderData<typeof loader>();
  return (
    <div className="page-width account-page">
      <div>
        <h1>Account</h1>
        <LogoutLink />
      </div>
      <div className="account-columns">
        <section className="stack" aria-labelledby="order-history-heading">
          <h2 id="order-history-heading">Order history</h2>
          <OrderHistory orders={orders} />
        </section>
        <section className="stack" aria-labelledby="account-details-heading">
          <h2 id="account-details-heading">Account details</h2>
          {customer.defaultAddress ? (
            <AddressBlock address={customer.defaultAddress} withPhone />
          ) : null}
          <Link to="/account/addresses">View addresses ({addressCount})</Link>
        </section>
      </div>
    </div>
  );
}
