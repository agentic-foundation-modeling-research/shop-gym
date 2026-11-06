/**
 * Product observation fragments: one schema-checked JSON object for each
 * product page that an executor opens on a generic-platform run, written
 * next to its part as `parts/<task_id>.product-<NN>.json`.
 *
 * A fragment holds only the price, the currency and the variant facts of
 * one product page. The schema is closed and has no field for a product
 * name, a URL, a seller or a brand. On the generic platform, `stats.json`
 * comes from these fragments, and the `product_observations` Verifier
 * fails an executor Iteration whose own fragments do not match the schema.
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import type { Verifier, VerifierResult } from '@shop-gym/harness';
import { z } from 'zod';

/** `<task_id>.product-<NN>.json`; the first group is the task id. */
const FRAGMENT_NAME = /^(.+)\.product-\d+\.json$/;

export const productObservationSchema = z
  .strictObject({
    price: z
      .number()
      .nonnegative()
      .describe(
        'The price that the page shows for the selected variant, in units of `currency`, e.g. 59.99.',
      ),
    currency: z
      .string()
      .regex(/^[A-Z]{3}$/)
      .describe('The ISO 4217 code of the price, e.g. "USD".'),
    has_variants: z
      .boolean()
      .describe('True when the page offers more than one variant to choose from.'),
    variant_axes: z
      .array(z.string().min(1))
      .describe(
        'The names of the variant axes, e.g. ["size", "color"]. Empty when `has_variants` is false.',
      ),
  })
  .refine((observation) => observation.has_variants === observation.variant_axes.length > 0, {
    message:
      'list at least one axis when has_variants is true, and no axis when has_variants is false',
    path: ['variant_axes'],
  });

export type ProductObservation = z.infer<typeof productObservationSchema>;

/** The schema rendered as JSON Schema text, for the agent constitution. */
export function productObservationJsonSchema(): string {
  return JSON.stringify(z.toJSONSchema(productObservationSchema), null, 2);
}

type FragmentCheck =
  | { readonly observation: ProductObservation }
  | { readonly file: string; readonly error: string };

/** The fragment names under `partsDir` in filename order, only those of `taskId` when given. */
function fragmentNames(partsDir: string, taskId?: string): string[] {
  if (!existsSync(partsDir)) return [];
  return readdirSync(partsDir)
    .filter((name) => {
      const match = FRAGMENT_NAME.exec(name);
      return match !== null && (taskId === undefined || match[1] === taskId);
    })
    .sort();
}

function checkFragment(partsDir: string, name: string): FragmentCheck {
  const file = `parts/${name}`;
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(join(partsDir, name), 'utf8'));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { file, error: `not valid JSON: ${message}` };
  }
  const result = productObservationSchema.safeParse(parsed);
  if (result.success) return { observation: result.data };
  const issues = result.error.issues.map((issue) =>
    issue.path.length === 0 ? issue.message : `${issue.path.join('.')}: ${issue.message}`,
  );
  return { file, error: issues.join('; ') };
}

/**
 * Reads every product observation fragment under `partsDir`, in filename
 * order. A missing directory has no fragments.
 *
 * @throws Error when a fragment is not valid JSON or does not match the schema.
 */
export function readObservations(partsDir: string): ProductObservation[] {
  return fragmentNames(partsDir).map((name) => {
    const check = checkFragment(partsDir, name);
    if ('observation' in check) return check.observation;
    throw new Error(`product observation ${check.file} is invalid: ${check.error}`);
  });
}

/**
 * The harness Verifier. After each executor Iteration it checks the
 * selected task's fragments under `<artifactDir>/parts/` and fails the
 * Iteration when one is not valid JSON or does not match the schema.
 */
export function productObservationVerifier(): Verifier {
  return {
    name: 'product_observations',
    appliesTo: () => true,
    async run(ctx): Promise<VerifierResult> {
      const partsDir = join(ctx.artifactDir, 'parts');
      const invalid = fragmentNames(partsDir, ctx.selectedTaskId)
        .map((name) => checkFragment(partsDir, name))
        .filter((check) => 'error' in check);
      if (invalid.length === 0) return { verdict: 'pass' };
      return {
        verdict: 'fail',
        feedback: [
          'Product observation check failed. These fragments do not match the product',
          'observation schema in AGENTS.md. Rewrite each one as one JSON object with only',
          'the schema fields, then mark the task done again.',
          '',
          ...invalid.map((check) => `- ${check.file}: ${check.error}`),
        ].join('\n'),
        details: { invalid: invalid.map((check) => check.file) },
      };
    },
  };
}
