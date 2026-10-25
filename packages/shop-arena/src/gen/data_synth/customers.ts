/** `synth_customers`: three seeded personas; email, password, and ids are assigned by code. */

import { completeStructured } from '../llm.js';
import { type SynthContext, cached, duplicates, pretty, synthPrompt } from './context.js';
import { type Identity, type Persona, personasSchema } from './schemas.js';

export const CUSTOMER_COUNT = 3;

export function synthCustomers(sc: SynthContext, identity: Identity): Promise<Persona[]> {
  return cached(sc, 'customers.json', personasSchema, () =>
    completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_customers', {
        count: String(CUSTOMER_COUNT),
        identity: pretty(identity),
        country: identity.country,
      }),
      personasSchema,
      (personas) => {
        if (personas.length !== CUSTOMER_COUNT)
          return `expected ${CUSTOMER_COUNT} personas, got ${personas.length}`;
        const dupes = duplicates(
          personas.map((p) => `${p.first_name} ${p.last_name}`.toLowerCase()),
        );
        return dupes.length > 0 ? `duplicate persona names: ${dupes.join(', ')}` : undefined;
      },
    ),
  );
}
