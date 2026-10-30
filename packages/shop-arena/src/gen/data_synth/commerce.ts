/**
 * `synth_commerce`: checkout rules consistent with the shipping and refund
 * policies, with three to five Discount codes and at least one of each
 * kind. The LLM picks the codes, amounts and hint texts; code checks them.
 */

import * as path from 'node:path';

import { datasetSchema } from '@shop-gym/shop-backend';
import { z } from 'zod';

import { checkDiscountCodes } from '../data_validation/schema_check.js';
import { readJsonFile } from '../io.js';
import { completeStructured } from '../llm.js';
import { type SynthContext, cached, duplicates, pretty, synthPrompt } from './context.js';
import {
  type CommerceDraft,
  type Identity,
  type PageDraft,
  commerceDraftSchema,
} from './schemas.js';

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
      (commerce) => {
        const dupes = duplicates([
          ...commerce.shipping_methods.map((m) => m.handle),
          ...commerce.payment_methods.map((m) => m.handle),
        ]);
        if (dupes.length > 0) return `duplicate method handles: ${dupes.join(', ')}`;
        const missing = datasetSchema.discountCodeKindSchema.options.filter(
          (kind) => !commerce.discount_codes.some((c) => c.kind === kind),
        );
        if (missing.length > 0) return `no Discount code of kind ${missing.join(', ')}`;
        const problems = checkDiscountCodes(commerce.discount_codes);
        return problems.length > 0 ? problems.join('; ') : undefined;
      },
    );
  });
}
