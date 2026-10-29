import { type AppLoadContext, getCustomerAccessToken } from '~/lib/context';
import {
  CUSTOMER_ADDRESS_CREATE_MUTATION,
  CUSTOMER_ADDRESS_DELETE_MUTATION,
  CUSTOMER_ADDRESS_UPDATE_MUTATION,
  CUSTOMER_DEFAULT_ADDRESS_UPDATE_MUTATION,
} from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { CustomerUserError } from '~/lib/types';

/** Address fields of the address book forms and of checkout, named as in `MailingAddressInput`. */
export const ADDRESS_FIELDS = [
  'firstName',
  'lastName',
  'company',
  'address1',
  'address2',
  'city',
  'province',
  'country',
  'zip',
  'phone',
] as const;

export type AddressField = (typeof ADDRESS_FIELDS)[number];

/** A `MailingAddressInput`: each address field as submitted, trimmed. */
export type AddressInput = Readonly<Record<AddressField, string>>;

/** A saved address, or the backend's reasons not to save it. */
export type AddressSaveResult =
  | { readonly addressId: string }
  | { readonly errors: readonly CustomerUserError[] };

interface AddressPayload {
  readonly customerAddress: { readonly id: string } | null;
  readonly customerUserErrors: readonly CustomerUserError[];
}

/** The address fields of a submitted form; a missing field is empty. */
export function addressInput(formData: FormData): AddressInput {
  const field = (name: AddressField) => {
    const value = formData.get(name);
    return typeof value === 'string' ? value.trim() : '';
  };
  return {
    firstName: field('firstName'),
    lastName: field('lastName'),
    company: field('company'),
    address1: field('address1'),
    address2: field('address2'),
    city: field('city'),
    province: field('province'),
    country: field('country'),
    zip: field('zip'),
    phone: field('phone'),
  };
}

/** Adds `address` to the logged-in customer's address book. */
export async function createAddress(
  context: AppLoadContext,
  address: AddressInput,
): Promise<AddressSaveResult> {
  const data = await storefrontQuery<{ readonly customerAddressCreate: AddressPayload }>(
    context,
    CUSTOMER_ADDRESS_CREATE_MUTATION,
    { customerAccessToken: getCustomerAccessToken(context), address },
  );
  return saveResult(data.customerAddressCreate);
}

/** Replaces the fields of the logged-in customer's address `addressId` with `address`. */
export async function updateAddress(
  context: AppLoadContext,
  addressId: string,
  address: AddressInput,
): Promise<AddressSaveResult> {
  const data = await storefrontQuery<{ readonly customerAddressUpdate: AddressPayload }>(
    context,
    CUSTOMER_ADDRESS_UPDATE_MUTATION,
    { customerAccessToken: getCustomerAccessToken(context), id: addressId, address },
  );
  return saveResult(data.customerAddressUpdate);
}

/** Removes the logged-in customer's address `addressId`; returns the backend's errors. */
export async function deleteAddress(
  context: AppLoadContext,
  addressId: string,
): Promise<readonly CustomerUserError[]> {
  const data = await storefrontQuery<{
    readonly customerAddressDelete: { readonly customerUserErrors: readonly CustomerUserError[] };
  }>(context, CUSTOMER_ADDRESS_DELETE_MUTATION, {
    customerAccessToken: getCustomerAccessToken(context),
    id: addressId,
  });
  return data.customerAddressDelete.customerUserErrors;
}

/** Makes `addressId` the logged-in customer's default address; returns the backend's errors. */
export async function setDefaultAddress(
  context: AppLoadContext,
  addressId: string,
): Promise<readonly CustomerUserError[]> {
  const data = await storefrontQuery<{
    readonly customerDefaultAddressUpdate: {
      readonly customerUserErrors: readonly CustomerUserError[];
    };
  }>(context, CUSTOMER_DEFAULT_ADDRESS_UPDATE_MUTATION, {
    customerAccessToken: getCustomerAccessToken(context),
    addressId,
  });
  return data.customerDefaultAddressUpdate.customerUserErrors;
}

function saveResult(payload: AddressPayload): AddressSaveResult {
  return payload.customerAddress
    ? { addressId: payload.customerAddress.id }
    : { errors: payload.customerUserErrors };
}
