import { type LoaderFunctionArgs, useLoaderData } from 'react-router';
import { AccountNav, AddressBlock } from '~/components/account';
import { getAppContext, getCustomerAccessToken } from '~/lib/context';
import { requireCustomer } from '~/lib/customer';
import { CUSTOMER_ADDRESSES_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Customer, MailingAddress } from '~/lib/types';

interface CustomerAddressesData {
  readonly customer:
    | (Customer & {
        readonly addresses: { readonly nodes: readonly MailingAddress[] };
      })
    | null;
}

export function meta() {
  return [{ title: 'Addresses' }];
}

export async function loader({ context, request }: LoaderFunctionArgs) {
  const appContext = getAppContext(context);
  const customer = await requireCustomer(appContext, request);
  const data = await storefrontQuery<CustomerAddressesData>(appContext, CUSTOMER_ADDRESSES_QUERY, {
    customerAccessToken: getCustomerAccessToken(appContext),
  });
  return {
    defaultAddressId: customer.defaultAddress?.id ?? null,
    addresses: data.customer?.addresses.nodes ?? [],
  };
}

export default function AddressesRoute() {
  const { addresses, defaultAddressId } = useLoaderData<typeof loader>();
  return (
    <div className="page-width stack">
      <h1>Addresses</h1>
      <AccountNav />
      {addresses.length === 0 ? (
        <p>No saved addresses.</p>
      ) : (
        <ul className="address-list">
          {addresses.map((address) => (
            <li key={address.id}>
              {address.id === defaultAddressId ? <p className="eyebrow">Default</p> : null}
              <AddressBlock address={address} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
