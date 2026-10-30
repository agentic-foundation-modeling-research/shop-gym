/**
 * `synth_commerce`: checkout rules consistent with the shipping and refund
 * policies, with three to five Discount codes. The LLM picks the codes,
 * amounts and hint texts; deterministic checks reject a reply that breaks
 * a Discount code rule.
 */

import * as path from 'node:path';

import { datasetSchema } from '@shop-gym/shop-backend';
import { z } from 'zod';

import { checkDiscountCodes } from '../discount_codes.js';
import { readJsonFile } from '../io.js';
import { completeStructured } from '../llm.js';
import { type SynthContext, cached, duplicates, pretty, synthPrompt } from './context.js';
import {
  type CommerceDraft,
  type Identity,
  type PageDraft,
  commerceDraftSchema,
} from './schemas.js';

/**
 * The first problem with `commerce`, or `undefined`. Besides the rules of
 * every Dataset, synthesized Discount codes cover every kind, include a
 * percent or fixed code with no minimum (so every order can use one), and
 * never set a free-shipping minimum at or above the free-shipping
 * threshold (where the code would save nothing).
 */
function commerceProblem(commerce: CommerceDraft): string | undefined {
  const dupes = duplicates([
    ...commerce.shipping_methods.map((m) => m.handle),
    ...commerce.payment_methods.map((m) => m.handle),
  ]);
  if (dupes.length > 0) return `duplicate method handles: ${dupes.join(', ')}`;
  const codes = commerce.discount_codes;
  const missing = datasetSchema.discountCodeKindSchema.options.filter(
    (kind) => !codes.some((c) => c.kind === kind),
  );
  if (missing.length > 0) return `no Discount code of kind ${missing.join(', ')}`;
  if (!codes.some((c) => c.kind !== 'free_shipping' && c.minimum_subtotal === null)) {
    return 'no percentage or fixed_amount Discount code without a minimum_subtotal';
  }
  const threshold = commerce.free_shipping_threshold;
  const useless = codes.filter(
    (c) =>
      c.kind === 'free_shipping' &&
      threshold !== null &&
      c.minimum_subtotal !== null &&
      Number(c.minimum_subtotal) >= Number(threshold),
  );
  if (useless.length > 0) {
    return `free_shipping Discount code ${useless.map((c) => c.code).join(', ')} has a minimum_subtotal at or above free_shipping_threshold ${threshold}, so it saves nothing`;
  }
  const problems = checkDiscountCodes(codes);
  return problems.length > 0 ? problems.join('; ') : undefined;
}

export function synthCommerce(
  sc: SynthContext,
  identity: Identity,
  policies: readonly PageDraft[],
): Promise<CommerceDraft> {
  return cached(sc, 'commerce.json', commerceDraftSchema, async () => {
    const capabilities = await readJsonFile(
      path.join(sc.manualDir, 'capabilities.json'),
      z.object({ checkout: z.unknown().optional() }),
    );
    const policy = (handle: string): string =>
      policies.find((p) => p.handle === handle)?.body_html ?? '';
    return completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_commerce', {
        identity: pretty(identity),
        shipping_policy: policy('shipping-policy'),
        refund_policy: policy('refund-policy'),
        checkout_capabilities: pretty(capabilities.checkout ?? {}),
      }),
      commerceDraftSchema,
      commerceProblem,
    );
  });
}
