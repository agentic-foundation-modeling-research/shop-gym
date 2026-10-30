/**
 * The functional sweep: a fixed shopper journey through the storefront in
 * one browser episode. Sign up, log out, request a password reset with
 * "Forgot your password?", log in, add an address and edit it, add to
 * cart, apply a Discount code, check out, view the order.
 * Returns are not supported by the backend, so that step is recorded as
 * skipped. Steps run in order and stop at the first failure.
 */

import type { BrowserSession } from '@shop-gym/browser';

import {
  type StepRecord,
  addAddress,
  addToCart,
  applyDiscountCode,
  editAddress,
  logIn,
  logOut,
  placeOrder,
  recordStep,
  register,
  requestPasswordReset,
  viewOrder,
} from '../build/verifiers/browser_steps.js';
import {
  CHECKOUT_ADDRESS,
  NO_APPLICABLE_DISCOUNT_CODE,
} from '../build/verifiers/storefront_target.js';

export type StepStatus = StepRecord['status'];

export type FunctionalStep = StepRecord;

export interface FunctionalSweepOptions {
  readonly session: BrowserSession;
  readonly storefrontUrl: string;
  /** Handle of the product to buy. */
  readonly productHandle: string | undefined;
  /** Dataset Discount code to apply at checkout, from `readApplicableDiscountCode`. */
  readonly discountCode: string | undefined;
}

export const FUNCTIONAL_STEP_NAMES = [
  'signUp',
  'logOut',
  'requestPasswordReset',
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
    signUp: async () => recordStep('signUp', await register(page, storefrontUrl, account)),
    logOut: async () => recordStep('logOut', await logOut(page, storefrontUrl)),
    requestPasswordReset: async () =>
      recordStep(
        'requestPasswordReset',
        await requestPasswordReset(page, storefrontUrl, account.email),
      ),
    logIn: async () =>
      recordStep(
        'logIn',
        await logIn(page, storefrontUrl, { email: account.email, password: account.password }),
      ),
    addAddress: async () =>
      recordStep('addAddress', await addAddress(page, storefrontUrl, CHECKOUT_ADDRESS)),
    editAddress: async () =>
      recordStep('editAddress', await editAddress(page, storefrontUrl, 1, { address2: 'Unit 2' })),
    addToCart: async () =>
      productHandle === undefined
        ? { name: 'addToCart', status: 'skipped', detail: 'the dataset has no product' }
        : recordStep('addToCart', await addToCart(page, storefrontUrl, productHandle)),
    applyDiscountCode: async () =>
      discountCode === undefined
        ? { name: 'applyDiscountCode', status: 'skipped', detail: NO_APPLICABLE_DISCOUNT_CODE }
        : recordStep(
            'applyDiscountCode',
            await applyDiscountCode(page, storefrontUrl, discountCode),
          ),
    checkout: async () => {
      const outcome = await placeOrder(page, storefrontUrl, account.email);
      orderNumber = outcome.orderNumber;
      return recordStep('checkout', outcome);
    },
    viewOrder: async () =>
      orderNumber === undefined
        ? { name: 'viewOrder', status: 'skipped', detail: 'no order was placed' }
        : recordStep('viewOrder', await viewOrder(page, storefrontUrl, orderNumber)),
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
