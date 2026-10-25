/** `synth_store`: domain, description, payment settings, and brand colours. */

import { completeStructured } from '../llm.js';
import { type SynthContext, cached, pretty, synthPrompt } from './context.js';
import { type Identity, type StoreDraft, storeDraftSchema } from './schemas.js';

export function synthStore(sc: SynthContext, identity: Identity): Promise<StoreDraft> {
  return cached(sc, 'store.json', storeDraftSchema, () =>
    completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_store', { identity: pretty(identity) }),
      storeDraftSchema,
    ),
  );
}
