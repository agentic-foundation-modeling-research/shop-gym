/**
 * `account_flow` verifier: a shopper can still use the account pages after
 * a task restyles them. In a real browser, in a fresh episode: sign up, log
 * out, request a password reset with "Forgot your password?" (the login
 * page must show the sent message), log in again, add an address and edit
 * it. Each step drives the storefront's own forms, so a changed form
 * selector or a broken page shows as the step that failed.
 */

import type { Verifier } from '@shop-gym/harness';

import { browserFlowVerifier } from './browser_flow.js';
import {
  addAddress,
  editAddress,
  logIn,
  logOut,
  register,
  requestPasswordReset,
} from './browser_steps.js';
import { CHECKOUT_ADDRESS, type StorefrontTarget } from './storefront_target.js';

export const ACCOUNT_FLOW_NAME = 'account_flow';
const ACCOUNT_TASKS: ReadonlySet<string> = new Set(['gen_account', 'visual_fix']);
/** The customer the flow signs up; each run is a fresh episode, so the email is free. */
const ACCOUNT = {
  firstName: 'Account',
  lastName: 'Flow',
  email: 'account.flow@example.com',
  password: 'account-flow-password',
};

export interface AccountFlowOptions {
  readonly target: StorefrontTarget;
}

export function accountFlowVerifier(options: AccountFlowOptions): Verifier {
  const url = options.target.url;
  return browserFlowVerifier({
    name: ACCOUNT_FLOW_NAME,
    tasks: ACCOUNT_TASKS,
    target: options.target,
    steps: async () => [
      { name: 'signUp', run: (page) => register(page, url, ACCOUNT) },
      { name: 'logOut', run: (page) => logOut(page, url) },
      {
        name: 'requestPasswordReset',
        run: (page) => requestPasswordReset(page, url, ACCOUNT.email),
      },
      {
        name: 'logIn',
        run: (page) => logIn(page, url, { email: ACCOUNT.email, password: ACCOUNT.password }),
      },
      { name: 'addAddress', run: (page) => addAddress(page, url, CHECKOUT_ADDRESS) },
      { name: 'editAddress', run: (page) => editAddress(page, url, 1, { address2: 'Unit 2' }) },
    ],
  });
}
