/**
 * The functional sweep: a fixed shopper journey through the storefront in
 * one browser episode. Sign up, log out, log in, add to cart, check out,
 * view the order. Returns are not supported by the backend, so that step
 * is recorded as skipped. Steps run in order and stop at the first failure.
 */

import type { BrowserSession } from '@shop-gym/browser';

import {
  addToCart,
  logIn,
  logOut,
  placeOrder,
  register,
  viewOrder,
} from '../build/verifiers/browser_steps.js';

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
}

export const FUNCTIONAL_STEP_NAMES = [
  'signUp',
  'logOut',
  'logIn',
  'addToCart',
  'checkout',
  'viewOrder',
  'requestReturn',
] as const;

export async function runFunctionalSweep(
  options: FunctionalSweepOptions,
): Promise<FunctionalStep[]> {
  const { session, storefrontUrl, productHandle } = options;
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
    addToCart: async () =>
      productHandle === undefined
        ? { name: 'addToCart', status: 'skipped', detail: 'the dataset has no product' }
        : step('addToCart', await addToCart(page, storefrontUrl, productHandle)),
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
