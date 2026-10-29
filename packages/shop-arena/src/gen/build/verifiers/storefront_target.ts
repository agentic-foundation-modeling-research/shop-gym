/**
 * What the HTTP-level storefront verifiers share: the served storefront
 * (URL plus a hook that brings the server up to date with the iteration's
 * edits), the seeded customer used for logged-in checks, and the fixed
 * checkout form used by the functional checks.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { VerifierResult } from '@shop-gym/harness';

export interface StorefrontTarget {
  readonly url: string;
  /**
   * Runs before the first request of a verifier so the served tree reflects
   * the iteration's edits (the sidecar's `ensureCurrent`). Omit when the
   * server is managed elsewhere, e.g. in `final_eval`.
   */
  readonly prepare?: () => Promise<unknown>;
}

/**
 * Run `target.prepare`; a thrown error becomes a failing result, since a
 * storefront that no longer starts is the iteration's fault, not a verifier
 * crash.
 */
export async function prepareTarget(target: StorefrontTarget): Promise<VerifierResult | undefined> {
  if (target.prepare === undefined) {
    return undefined;
  }
  try {
    await target.prepare();
    return undefined;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      verdict: 'fail',
      feedback: `The storefront did not start after this iteration: ${message}`,
      details: { startError: message },
    };
  }
}

export interface SeededCustomer {
  readonly email: string;
  readonly password: string;
}

/** The first account in `customers.json` with credentials; `undefined` when none. */
export async function readSeededCustomer(dataDir: string): Promise<SeededCustomer | undefined> {
  const raw = await fs
    .readFile(path.join(dataDir, 'customers.json'), 'utf-8')
    .catch(() => undefined);
  if (raw === undefined) {
    return undefined;
  }
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    return undefined;
  }
  for (const item of parsed) {
    if (typeof item === 'object' && item !== null) {
      const { email, password } = item as { email?: unknown; password?: unknown };
      if (typeof email === 'string' && typeof password === 'string') {
        return { email, password };
      }
    }
  }
  return undefined;
}

export interface CheckoutMethods {
  readonly shippingMethodHandle: string;
  readonly paymentMethodHandle: string;
}

/** First shipping and payment handles from `commerce.json`, else the backend defaults. */
export async function readCheckoutMethods(dataDir: string): Promise<CheckoutMethods> {
  const raw = await fs
    .readFile(path.join(dataDir, 'commerce.json'), 'utf-8')
    .catch(() => undefined);
  const commerce = raw === undefined ? {} : (JSON.parse(raw) as Record<string, unknown>);
  return {
    shippingMethodHandle: firstHandle(commerce.shipping_methods) ?? 'standard',
    paymentMethodHandle: firstHandle(commerce.payment_methods) ?? 'card',
  };
}

function firstHandle(methods: unknown): string | undefined {
  if (!Array.isArray(methods)) {
    return undefined;
  }
  const first: unknown = methods[0];
  if (typeof first === 'object' && first !== null && 'handle' in first) {
    const handle = (first as { handle: unknown }).handle;
    return typeof handle === 'string' ? handle : undefined;
  }
  return undefined;
}

/** Shipping address used by every scripted checkout. */
export const CHECKOUT_ADDRESS: Readonly<Record<string, string>> = {
  firstName: 'Sample',
  lastName: 'Shopper',
  address1: '1 Sample Road',
  address2: '',
  company: '',
  city: 'Ottawa',
  province: 'Ontario',
  country: 'Canada',
  zip: 'K1A 0B1',
  phone: '',
};
