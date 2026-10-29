/**
 * The functional sweep: a fixed shopper journey through the storefront in
 * one browser episode. Sign up, log out, log in, add an address and edit
 * it, add to cart, apply a Discount code, check out, view the order.
 * Returns are not supported by the backend, so that step is recorded as
 * skipped. Steps run in order and stop at the first failure.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { BrowserSession } from '@shop-gym/browser';
import { datasetSchema } from '@shop-gym/shop-backend';

import {
  addAddress,
  addToCart,
  applyDiscountCode,
  editAddress,
  logIn,
  logOut,
  placeOrder,
  register,
  viewOrder,
} from '../build/verifiers/browser_steps.js';
import { CHECKOUT_ADDRESS } from '../build/verifiers/storefront_target.js';

export type StepStatus = 'pass' | 'fail' | 'skipped';

export interface FunctionalStep {
  readonly name: string;
  readonly status: StepStatus;
  readonly detail: string;
  readonly url?: string;
}

export interface FunctionalSweepOptions {
  readonly session: BrowserSession;
  readonly storefrontUrl: string;
  /** Handle of the product to buy. */
  readonly productHandle: string | undefined;
  /** Dataset Discount code to apply at checkout, from `readSweepDiscountCode`. */
  readonly discountCode: string | undefined;
}

export const FUNCTIONAL_STEP_NAMES = [
  'signUp',
  'logOut',
  'logIn',
  'addAddress',
  'editAddress',
  'addToCart',
  'applyDiscountCode',
  'checkout',
  'viewOrder',
  'requestReturn',
] as const;

export async function runFunctionalSweep(
  options: FunctionalSweepOptions,
): Promise<FunctionalStep[]> {
  const { session, storefrontUrl, productHandle, discountCode } = options;
  const page = session.page;
  const account = {
    firstName: 'Final',
    lastName: 'Eval',
    email: `final.eval.${Date.now()}@example.com`,
    password: 'final-eval-password',
  };
  const steps: FunctionalStep[] = [];
  let orderNumber: number | undefined;
  const scripted: Record<(typeof FUNCTIONAL_STEP_NAMES)[number], () => Promise<FunctionalStep>> = {
    signUp: async () => step('signUp', await register(page, storefrontUrl, account)),
    logOut: async () => step('logOut', await logOut(page, storefrontUrl)),
    logIn: async () =>
      step(
        'logIn',
        await logIn(page, storefrontUrl, { email: account.email, password: account.password }),
      ),
    addAddress: async () =>
      step('addAddress', await addAddress(page, storefrontUrl, CHECKOUT_ADDRESS)),
    editAddress: async () =>
      step(
        'editAddress',
        await editAddress(page, storefrontUrl, 1, { address2: 'Unit 2' }, { setDefault: true }),
      ),
    addToCart: async () =>
      productHandle === undefined
        ? { name: 'addToCart', status: 'skipped', detail: 'the dataset has no product' }
        : step('addToCart', await addToCart(page, storefrontUrl, productHandle)),
    applyDiscountCode: async () =>
      discountCode === undefined
        ? {
            name: 'applyDiscountCode',
            status: 'skipped',
            detail: 'the dataset has no Discount code without a minimum subtotal',
          }
        : step('applyDiscountCode', await applyDiscountCode(page, storefrontUrl, discountCode)),
    checkout: async () => {
      const outcome = await placeOrder(page, storefrontUrl, account.email);
      orderNumber = outcome.orderNumber;
      return step('checkout', outcome);
    },
    viewOrder: async () =>
      orderNumber === undefined
        ? { name: 'viewOrder', status: 'skipped', detail: 'no order was placed' }
        : step('viewOrder', await viewOrder(page, storefrontUrl, orderNumber)),
    requestReturn: async () => ({
      name: 'requestReturn',
      status: 'skipped',
      detail: 'not supported by backend',
    }),
  };
  let failed = false;
  for (const name of FUNCTIONAL_STEP_NAMES) {
    if (failed && name !== 'requestReturn') {
      steps.push({ name, status: 'skipped', detail: 'a previous step failed' });
      continue;
    }
    const result = await scripted[name]();
    steps.push(result);
    failed ||= result.status === 'fail';
  }
  return steps;
}

/**
 * The Discount code in `<dataDir>/commerce.json` that the sweep applies to
 * its one-product cart. Only a code with no minimum subtotal surely applies.
 * A percent or fixed-amount code comes first, because it always changes the
 * total; a free-shipping code changes it while the cart pays for shipping.
 * `undefined` when there is no `commerce.json` or no such code.
 *
 * @throws Error when `commerce.json` is not valid JSON or not a valid
 *   commerce settings file.
 */
export async function readSweepDiscountCode(dataDir: string): Promise<string | undefined> {
  let raw: string;
  try {
    raw = await fs.readFile(path.join(dataDir, 'commerce.json'), 'utf-8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return undefined;
    }
    throw error;
  }
  const codes = datasetSchema.commerceSchema
    .parse(JSON.parse(raw))
    .discount_codes.filter((entry) => entry.minimum_subtotal === null);
  return (codes.find((entry) => entry.kind !== 'free_shipping') ?? codes[0])?.code;
}

function step(
  name: string,
  outcome: { ok: boolean; detail: string; url?: string },
): FunctionalStep {
  return {
    name,
    status: outcome.ok ? 'pass' : 'fail',
    detail: outcome.detail,
    ...(outcome.url !== undefined ? { url: outcome.url } : {}),
  };
}
