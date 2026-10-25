/** `synth_commerce`: checkout rules consistent with the shipping and refund policies. */

import * as path from 'node:path';

import { z } from 'zod';

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
        return dupes.length > 0 ? `duplicate method handles: ${dupes.join(', ')}` : undefined;
      },
    );
  });
}
