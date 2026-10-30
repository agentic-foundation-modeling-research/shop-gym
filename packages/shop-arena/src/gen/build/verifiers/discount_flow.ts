/**
 * `discount_flow` verifier: the checkout "Discount code" field still works
 * after a task restyles checkout. In a real browser, in a fresh episode:
 * add the first sampled product to the cart, apply a Dataset code that
 * applies to that cart (the "Total" must change), then enter a code the
 * Dataset does not have (the field must show "Enter a valid discount code"
 * and the "Total" must stay). A Dataset with no code that surely applies
 * skips the first check.
 */

import type { Verifier } from '@shop-gym/harness';

import { type FlowStep, browserFlowVerifier } from './browser_flow.js';
import { addToCart, applyDiscountCode, rejectDiscountCode } from './browser_steps.js';
import { type StorefrontTarget, readApplicableDiscountCode } from './storefront_target.js';
import { SWEEP_CAPS, readDatasetHandles, sampleProductHandles } from './task_routes.js';

export const DISCOUNT_FLOW_NAME = 'discount_flow';
const DISCOUNT_TASKS: ReadonlySet<string> = new Set(['gen_checkout', 'visual_fix']);
/** The code the flow enters as unknown; no Dataset is expected to hold it. */
const UNKNOWN_DISCOUNT_CODE = 'NOT-A-SHOPGYM-CODE';

export interface DiscountFlowOptions {
  readonly target: StorefrontTarget;
  readonly dataDir: string;
}

export function discountFlowVerifier(options: DiscountFlowOptions): Verifier {
  const url = options.target.url;
  return browserFlowVerifier({
    name: DISCOUNT_FLOW_NAME,
    flow: 'discount flow',
    tasks: DISCOUNT_TASKS,
    target: options.target,
    steps: async () => {
      const handles = await readDatasetHandles(options.dataDir);
      const productHandle = sampleProductHandles(handles, SWEEP_CAPS)[0];
      const code = await readApplicableDiscountCode(options.dataDir);
      const apply: FlowStep =
        code === undefined
          ? {
              name: 'applyDiscountCode',
              skip: 'the dataset has no Discount code without a minimum subtotal',
            }
          : { name: 'applyDiscountCode', run: (page) => applyDiscountCode(page, url, code) };
      return [
        {
          name: 'addToCart',
          run: async (page) =>
            productHandle === undefined
              ? { ok: false, detail: 'the dataset has no product to add to the cart' }
              : addToCart(page, url, productHandle),
        },
        apply,
        {
          name: 'rejectDiscountCode',
          run: (page) => rejectDiscountCode(page, url, UNKNOWN_DISCOUNT_CODE),
        },
      ];
    },
  });
}
