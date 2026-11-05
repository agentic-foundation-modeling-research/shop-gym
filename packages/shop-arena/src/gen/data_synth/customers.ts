/**
 * `synth_customers`: five Personas with one to three saved addresses each;
 * email, password, and ids are assigned by code.
 */

import { completeStructured } from '../llm.js';
import { type SynthContext, cached, duplicates, pretty, synthPrompt } from './context.js';
import { type Identity, type Persona, personasSchema } from './schemas.js';

export const CUSTOMER_COUNT = 5;
/** Personas that must have two or more saved addresses. */
const MIN_MULTI_ADDRESS_PERSONAS = 2;

export function synthCustomers(sc: SynthContext, identity: Identity): Promise<Persona[]> {
  return cached(sc, 'customers.json', personasSchema, () =>
    completeStructured(
      sc.call,
      synthPrompt(sc, 'synth_customers', {
        count: String(CUSTOMER_COUNT),
        multi_address_count: String(MIN_MULTI_ADDRESS_PERSONAS),
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
        if (dupes.length > 0) return `duplicate persona names: ${dupes.join(', ')}`;
        const multi = personas.filter((p) => p.addresses.length >= 2).length;
        return multi < MIN_MULTI_ADDRESS_PERSONAS
          ? `need at least ${MIN_MULTI_ADDRESS_PERSONAS} personas with 2 or more addresses, got ${multi}`
          : undefined;
      },
    ),
  );
}
