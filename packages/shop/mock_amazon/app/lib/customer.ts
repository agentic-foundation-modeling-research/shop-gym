import { redirect } from 'react-router';
import {
  type AppLoadContext,
  clearCustomerAccessToken,
  commitCustomerAccessToken,
  getCartId,
  getCustomerAccessToken,
} from '~/lib/context';
import {
  CART_BUYER_IDENTITY_UPDATE_MUTATION,
  CUSTOMER_ACCESS_TOKEN_CREATE_MUTATION,
  CUSTOMER_QUERY,
} from '~/lib/queries';
import { storefrontQuery } from '~/lib/storefront';
import type { Customer, CustomerUserError } from '~/lib/types';

interface CustomerQueryData {
  readonly customer: Customer | null;
}

interface CustomerAccessTokenCreateData {
  readonly customerAccessTokenCreate: {
    readonly customerAccessToken: { readonly accessToken: string } | null;
    readonly customerUserErrors: readonly CustomerUserError[];
  };
}

interface CartBuyerIdentityUpdateData {
  readonly cartBuyerIdentityUpdate: {
    readonly cart: { readonly id: string } | null;
    readonly userErrors: readonly { readonly message: string }[];
  };
}

/** Logged-in customer from the session cookie, or null when absent or expired. */
export async function loadCustomer(context: AppLoadContext): Promise<Customer | null> {
  const customerAccessToken = getCustomerAccessToken(context);
  if (customerAccessToken === null) return null;
  const data = await storefrontQuery<CustomerQueryData>(context, CUSTOMER_QUERY, {
    customerAccessToken,
  });
  return data.customer;
}

/**
 * Logged-in customer for a protected route. Redirects to `/account/login`
 * (remembering `request`'s path) when there is no valid session.
 */
export async function requireCustomer(
  context: AppLoadContext,
  request: Request,
): Promise<Customer> {
  const customer = await loadCustomer(context);
  if (customer !== null) return customer;
  const redirectTo = new URL(request.url).pathname;
  const headers =
    getCustomerAccessToken(context) === null ? undefined : await clearCustomerAccessToken(context);
  throw redirect(loginPath(redirectTo), headers ? { headers } : undefined);
}

export function loginPath(redirectTo: string): string {
  const params = new URLSearchParams({ redirectTo });
  return `/account/login?${params.toString()}`;
}

/**
 * Exchanges credentials for an access token, attaches it to the current
 * cart, and returns the `Set-Cookie` headers. Returns the backend's
 * `customerUserErrors` when the credentials are rejected.
 */
export async function loginCustomer(
  context: AppLoadContext,
  email: string,
  password: string,
): Promise<{ readonly headers: Headers } | { readonly errors: readonly CustomerUserError[] }> {
  const data = await storefrontQuery<CustomerAccessTokenCreateData>(
    context,
    CUSTOMER_ACCESS_TOKEN_CREATE_MUTATION,
    { input: { email, password } },
  );
  const payload = data.customerAccessTokenCreate;
  const accessToken = payload.customerAccessToken?.accessToken;
  if (!accessToken) {
    return { errors: payload.customerUserErrors };
  }
  const cartId = getCartId(context);
  if (cartId !== null) {
    await storefrontQuery<CartBuyerIdentityUpdateData>(
      context,
      CART_BUYER_IDENTITY_UPDATE_MUTATION,
      { cartId, buyerIdentity: { customerAccessToken: accessToken } },
    );
  }
  return { headers: await commitCustomerAccessToken(context, accessToken) };
}

/** Internal redirect target from a form or query string, defaulting to `/account`. */
export function safeAccountRedirect(raw: string | null): string {
  if (raw === null || !raw.startsWith('/') || raw.startsWith('//')) {
    return '/account';
  }
  return raw;
}
