import {
  type ActionFunctionArgs,
  Link,
  type LoaderFunctionArgs,
  redirect,
  useActionData,
  useLoaderData,
  useLocation,
} from 'react-router';
import { AddressBook, type FailedAddressAction } from '~/components/addresses';
import {
  addressInput,
  createAddress,
  deleteAddress,
  setDefaultAddress,
  updateAddress,
} from '~/lib/addresses';
import { getAppContext, getCustomerAccessToken } from '~/lib/context';
import { requireCustomer } from '~/lib/customer';
import { COUNTRIES_QUERY, CUSTOMER_ADDRESSES_QUERY } from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Country, Customer, CustomerUserError, MailingAddress } from '~/lib/types';

const ADDRESSES_PATH = '/account/addresses';

interface CustomerAddressesData {
  readonly customer:
    | (Customer & {
        readonly addresses: { readonly nodes: readonly MailingAddress[] };
      })
    | null;
}

interface CountriesData {
  readonly localization: { readonly availableCountries: readonly Country[] };
}

export function meta() {
  return [{ title: 'Addresses' }];
}

export async function loader({ context, request }: LoaderFunctionArgs) {
  const appContext = getAppContext(context);
  const customer = await requireCustomer(appContext, request);
  const [data, countries] = await Promise.all([
    storefrontQuery<CustomerAddressesData>(appContext, CUSTOMER_ADDRESSES_QUERY, {
      customerAccessToken: getCustomerAccessToken(appContext),
    }),
    storefrontQuery<CountriesData>(appContext, COUNTRIES_QUERY),
  ]);
  return {
    defaultAddressId: customer.defaultAddress?.id ?? null,
    addresses: data.customer?.addresses.nodes ?? [],
    countries: countries.localization.availableCountries,
  };
}

/**
 * Adds, updates or deletes one address, then shows the new list. With
 * "Set as default address" checked, the saved address also becomes the
 * default. A turned-down action returns the errors and the submitted fields.
 */
export async function action({ context, request }: ActionFunctionArgs) {
  const appContext = getAppContext(context);
  const customer = await requireCustomer(appContext, request);
  const formData = await request.formData();
  const values: Record<string, string> = {};
  for (const [key, value] of formData.entries()) {
    if (typeof value === 'string') values[key] = value;
  }
  const { intent, addressId = '' } = values;
  if (intent !== 'create' && intent !== 'update' && intent !== 'delete') {
    throw new Response('Unknown address action.', { status: 400 });
  }
  const failed = (errors: readonly CustomerUserError[]): FailedAddressAction => ({
    intent,
    addressId,
    errors,
    values,
  });

  if (intent === 'delete') {
    const errors = await deleteAddress(appContext, addressId);
    return errors.length > 0 ? failed(errors) : redirect(ADDRESSES_PATH);
  }
  const address = addressInput(formData);
  const saved =
    intent === 'create'
      ? await createAddress(appContext, address)
      : await updateAddress(appContext, addressId, address);
  if ('errors' in saved) return failed(saved.errors);
  if (values.default === 'true' && saved.addressId !== customer.defaultAddress?.id) {
    const errors = await setDefaultAddress(appContext, saved.addressId);
    if (errors.length > 0) return failed(errors);
  }
  return redirect(ADDRESSES_PATH);
}

export default function AddressesRoute() {
  const { addresses, defaultAddressId, countries } = useLoaderData<typeof loader>();
  const failed = useActionData<typeof action>();
  const location = useLocation();
  return (
    <div className="page-width stack addresses-page">
      <div className="addresses-heading">
        <h1>Addresses</h1>
        <Link to="/account">Return to Account details</Link>
      </div>
      <AddressBook
        key={location.key}
        addresses={addresses}
        defaultAddressId={defaultAddressId}
        countries={countries}
        failed={failed}
      />
    </div>
  );
}
