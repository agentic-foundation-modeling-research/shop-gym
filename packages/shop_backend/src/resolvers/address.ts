/**
 * Mailing address input that the address book mutations and checkout share:
 * the lines an address must have, and the conversion of a
 * `MailingAddressInput` into a new address of the episode state.
 */

import type { MailingAddressInput } from '../__generated__/resolvers-types.js';
import type { NewAddress } from '../state/shop_state.js';

/** Address lines that a saved address and a checkout shipping address must have. */
export const REQUIRED_ADDRESS_FIELDS = ['address1', 'city', 'country', 'zip'] as const;

/**
 * A new address from `input`, whose required lines are not blank. Each line
 * is trimmed, a blank optional line is `null`, and the country code is the
 * store's `countryCode`.
 */
export function toNewAddress(input: MailingAddressInput, countryCode: string): NewAddress {
  return {
    firstName: optionalLine(input.firstName),
    lastName: optionalLine(input.lastName),
    company: optionalLine(input.company),
    address1: (input.address1 ?? '').trim(),
    address2: optionalLine(input.address2),
    city: (input.city ?? '').trim(),
    province: optionalLine(input.province),
    provinceCode: null,
    country: (input.country ?? '').trim(),
    countryCode,
    zip: (input.zip ?? '').trim(),
    phone: optionalLine(input.phone),
  };
}

/** A trimmed optional line; blank is `null`. */
export function optionalLine(value: string | null | undefined): string | null {
  const trimmed = (value ?? '').trim();
  return trimmed === '' ? null : trimmed;
}
