/** `synth_pages` and `synth_policies`: content pages and the four policy pages. */

import * as path from 'node:path';

import { z } from 'zod';

import { readJsonFile } from '../io.js';
import { completeStructured } from '../llm.js';
import { type SynthContext, cached, duplicates, pretty, synthPrompt } from './context.js';
import { type Identity, type PageDraft, pageDraftsSchema } from './schemas.js';

export const POLICY_HANDLES = [
  'privacy-policy',
  'shipping-policy',
  'terms-of-service',
  'refund-policy',
] as const;

export function synthPages(sc: SynthContext, identity: Identity): Promise<PageDraft[]> {
  return cached(sc, 'pages.json', pageDraftsSchema, async () => {
    const capabilities = await readJsonFile(
      path.join(sc.manualDir, 'capabilities.json'),
      z.unknown(),
    );
    return completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_pages', {
        identity: pretty(identity),
        capabilities: pretty(capabilities),
      }),
      pageDraftsSchema.min(1),
      (pages) => {
        const dupes = duplicates(pages.map((p) => p.handle));
        return dupes.length > 0 ? `duplicate page handles: ${dupes.join(', ')}` : undefined;
      },
    );
  });
}

export function synthPolicies(sc: SynthContext, identity: Identity): Promise<PageDraft[]> {
  return cached(sc, 'policies.json', pageDraftsSchema, () =>
    completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_policies', { identity: pretty(identity) }),
      pageDraftsSchema.min(1),
      (policies) => {
        const handles = policies.map((p) => p.handle);
        const dupes = duplicates(handles);
        if (dupes.length > 0) return `duplicate policy handles: ${dupes.join(', ')}`;
        const missing = POLICY_HANDLES.filter((h) => !handles.includes(h));
        return missing.length > 0 ? `missing policies: ${missing.join(', ')}` : undefined;
      },
    ),
  );
}
