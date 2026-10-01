/** `synth_identity`: descriptor, tone, currency, country from the manual; name from the allowlist. */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { z } from 'zod';

import { pickBrandName } from '../brands/allowlist.js';
import { readJsonFile, readJsonIfExists, writeJsonFile } from '../io.js';
import { completeStructured } from '../llm.js';
import { IDENTITY_FILE, type SynthContext, pretty, synthPrompt } from './context.js';
import { type Identity, identityDraftSchema, identitySchema } from './schemas.js';

export async function synthIdentity(sc: SynthContext): Promise<Identity> {
  const file = path.join(sc.shopDir, IDENTITY_FILE);
  const existing = await readJsonIfExists(file, identitySchema);
  if (existing !== undefined) {
    sc.log('[data_synth] identity.json: cached');
    return existing;
  }
  const capabilities = await readJsonFile(
    path.join(sc.manualDir, 'capabilities.json'),
    z.unknown(),
  );
  const manual = await fs.readFile(path.join(sc.manualDir, 'manual.md'), 'utf-8');
  const draft = await completeStructured(
    sc.call,
    synthPrompt(sc, 'synth_identity', {
      capabilities: pretty(capabilities),
      manual: manual.trimEnd(),
    }),
    identityDraftSchema,
  );
  const identity: Identity = {
    name: pickBrandName(`${sc.config.name}\0${draft.descriptor}`, sc.allowlist),
    descriptor: draft.descriptor.trim(),
    tone: draft.tone.map((t) => t.trim()),
    currency: draft.currency.toUpperCase(),
    country: draft.country.toUpperCase(),
  };
  await writeJsonFile(file, identity);
  return identity;
}
