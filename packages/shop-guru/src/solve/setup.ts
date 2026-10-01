/**
 * Puts an episode into the state its task's `setup` describes before the
 * agent takes over. Everything goes through the storefront's own HTTP
 * endpoints from the episode's browser context, so cookies and the episode
 * header behave exactly as they would for a human shopper.
 */

import type { BrowserSession } from '@shop-gym/browser';
import type { TaskSetup } from '@shop-gym/core';
import type { Customer } from '@shop-gym/shop-backend';

/** `setup` could not be applied; the episode is reported as an error. */
export class SetupError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SetupError';
  }
}

/** Storefront route that creates the customer session cookie. */
export const LOGIN_PATH = '/account/login';
/** Storefront route that mutates the session cart. */
export const CART_PATH = '/cart';

/**
 * Log the browser context in as `persona` by posting the storefront's login
 * form. The storefront exchanges the credentials for a customer access token
 * and stores it in its signed session cookie, which the browser then sends on
 * every page load.
 */
export async function loginThroughStorefront(
  session: BrowserSession,
  baseUrl: string,
  persona: Pick<Customer, 'email' | 'password'>,
): Promise<void> {
  const response = await session.page.request.post(new URL(LOGIN_PATH, baseUrl).toString(), {
    form: { email: persona.email, password: persona.password },
    maxRedirects: 0,
  });
  // A successful login redirects to the account page; errors re-render the form.
  if (response.status() < 300 || response.status() >= 400) {
    throw new SetupError(`login as ${persona.email} failed with HTTP ${response.status()}`);
  }
}

/** Add one variant to the session cart through the storefront's cart action. */
export async function addToCartThroughStorefront(
  session: BrowserSession,
  baseUrl: string,
  line: { readonly variantId: number; readonly quantity: number },
): Promise<void> {
  const response = await session.page.request.post(new URL(CART_PATH, baseUrl).toString(), {
    form: {
      intent: 'add',
      merchandiseId: `gid://shopify/ProductVariant/${line.variantId}`,
      quantity: String(line.quantity),
    },
    maxRedirects: 0,
  });
  if (response.status() >= 400) {
    throw new SetupError(`adding variant ${line.variantId} failed with HTTP ${response.status()}`);
  }
}

/**
 * Apply `setup` in storefront order: fill the cart first, then log in, so
 * the storefront attaches the guest cart to the customer the same way it
 * does for a real shopper.
 */
export async function applySetup(
  setup: TaskSetup | undefined,
  session: BrowserSession,
  baseUrl: string,
  customers: readonly Customer[],
): Promise<void> {
  if (setup === undefined) return;
  for (const line of setup.cart ?? []) {
    await addToCartThroughStorefront(session, baseUrl, line);
  }
  if (setup.login !== undefined) {
    const persona = customers.find((c) => String(c.id) === setup.login);
    if (persona === undefined) throw new SetupError(`unknown persona "${setup.login}"`);
    await loginThroughStorefront(session, baseUrl, persona);
  }
}
