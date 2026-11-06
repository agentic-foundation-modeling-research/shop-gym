/**
 * Product observation fragments: one schema-checked JSON object for each
 * product page that an executor records on a generic-platform run, written
 * next to its part as `parts/<task_id>.product-<key>.json`.
 *
 * A fragment holds only the price, the currency and the variant facts of
 * one product page. The schema is closed and has no field for a product
 * name, a URL, a seller or a brand. The executor does not write the file:
 * the `record_product_observation` tool writes it, and the tool, not the
 * model, takes the page key from the open page. The key is a short hash of
 * the page URL, so it tells product pages apart without naming them, and
 * the observed sample counts each product page once. On the generic
 * platform, `stats.json` comes from these fragments, and the
 * `product_observations` Verifier fails an executor Iteration whose own
 * fragments do not match the schema.
 */

import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import type { Tool, ToolResult } from '@shop-gym/agent';
import type { BrowserSession } from '@shop-gym/browser';
import type { Verifier, VerifierResult } from '@shop-gym/harness';
import { Type } from '@sinclair/typebox';
import { z } from 'zod';

/** The hex digits of the SHA-256 of the page URL that make a page key. */
const PAGE_KEY_LENGTH = 12;

/** `<task_id>.product-<key>.json`; the groups are the task id and the page key. */
const FRAGMENT_NAME = new RegExp(`^(.+)\\.product-([0-9a-f]{${PAGE_KEY_LENGTH}})\\.json$`);

/** A plan task id, as the harness plan parser accepts it. */
const TASK_ID = /^[a-z0-9_]+$/;

/** The descriptions of the observation fields, shared by the schema and the tool parameters. */
const FIELD_DOCS = {
  price:
    'The price that the page shows for the selected variant, in units of `currency`, e.g. 59.99.',
  currency: 'The ISO 4217 code of the price, e.g. "USD".',
  has_variants: 'True when the page offers more than one variant to choose from.',
  variant_axes:
    'The names of the variant axes as short generic nouns, e.g. ["size", "color"], not the ' +
    'label text of the page. Empty when `has_variants` is false.',
} as const;

export const productObservationSchema = z
  .strictObject({
    price: z.number().nonnegative().describe(FIELD_DOCS.price),
    currency: z
      .string()
      .regex(/^[A-Z]{3}$/)
      .describe(FIELD_DOCS.currency),
    has_variants: z.boolean().describe(FIELD_DOCS.has_variants),
    variant_axes: z.array(z.string().min(1)).describe(FIELD_DOCS.variant_axes),
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

/** The schema issues of `error` as one line. */
function schemaIssues(error: z.ZodError): string {
  return error.issues
    .map((issue) =>
      issue.path.length === 0 ? issue.message : `${issue.path.join('.')}: ${issue.message}`,
    )
    .join('; ');
}

/** A fragment file under `parts/` and the page key in its name. */
type Fragment = { readonly name: string; readonly pageKey: string };

type FragmentCheck =
  | { readonly pageKey: string; readonly observation: ProductObservation }
  | { readonly file: string; readonly error: string };

/** The fragments under `partsDir` in filename order, only those of `taskId` when given. */
function listFragments(partsDir: string, taskId?: string): Fragment[] {
  if (!existsSync(partsDir)) return [];
  return readdirSync(partsDir)
    .sort()
    .flatMap((name) => {
      const match = FRAGMENT_NAME.exec(name);
      if (match === null || (taskId !== undefined && match[1] !== taskId)) return [];
      // The pattern has two groups, so a match holds the page key.
      return [{ name, pageKey: match[2] as string }];
    });
}

function checkFragment(partsDir: string, { name, pageKey }: Fragment): FragmentCheck {
  const file = `parts/${name}`;
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(join(partsDir, name), 'utf8'));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { file, error: `not valid JSON: ${message}` };
  }
  const result = productObservationSchema.safeParse(parsed);
  if (!result.success) return { file, error: schemaIssues(result.error) };
  return { pageKey, observation: result.data };
}

/**
 * Reads the observed sample under `partsDir`: one observation for each
 * product page, in filename order. When more than one task recorded the
 * same page, the first fragment in filename order counts. A missing
 * directory has no fragments.
 *
 * @throws Error when a fragment is not valid JSON or does not match the schema.
 */
export function readObservations(partsDir: string): ProductObservation[] {
  const byPage = new Map<string, ProductObservation>();
  for (const fragment of listFragments(partsDir)) {
    const check = checkFragment(partsDir, fragment);
    if ('error' in check) {
      throw new Error(`product observation ${check.file} is invalid: ${check.error}`);
    }
    if (!byPage.has(check.pageKey)) byPage.set(check.pageKey, check.observation);
  }
  return [...byPage.values()];
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
      const invalid = listFragments(partsDir, ctx.selectedTaskId)
        .map((fragment) => checkFragment(partsDir, fragment))
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

/**
 * The key and the path of the product page open in `page`. The key is the
 * first `PAGE_KEY_LENGTH` hex digits of the SHA-256 of the page URL
 * without its query and fragment. The URL is the `<link rel="canonical">`
 * target when the page has a valid one, so two paths to one product page
 * give one key. Else it is the address of the page.
 */
async function keyOfOpenPage(page: BrowserSession['page']): Promise<{ key: string; path: string }> {
  const address = page.url();
  const canonical = page.locator('link[rel~="canonical"]').first();
  const href = (await canonical.count()) > 0 ? await canonical.getAttribute('href') : null;
  const url =
    href !== null && URL.canParse(href, address) ? new URL(href, address) : new URL(address);
  const key = createHash('sha256')
    .update(`${url.origin}${url.pathname}`)
    .digest('hex')
    .slice(0, PAGE_KEY_LENGTH);
  return { key, path: url.pathname };
}

function textResult(text: string): ToolResult {
  return { content: [{ type: 'text', text }] };
}

function errorResult(error: unknown): ToolResult {
  const message = error instanceof Error ? error.message : String(error);
  return { content: [{ type: 'text', text: `Error: ${message}` }], isError: true };
}

/**
 * The `record_product_observation` tool for executors on a generic site.
 * The model gives its task id and the facts of the product page that is
 * open in `session`. The tool checks the facts against the schema, takes
 * the page key from the open page, and writes the fragment to
 * `artifact/parts/<task_id>.product-<key>.json` under the run directory.
 * A second call on the same page in the same task replaces the fragment.
 */
export function productObservationTool(session: BrowserSession): Tool {
  const parameters = Type.Object({
    task_id: Type.String({
      pattern: TASK_ID.source,
      description: 'Your selected task id, e.g. "product_variants".',
    }),
    price: Type.Number({ description: FIELD_DOCS.price }),
    currency: Type.String({ description: FIELD_DOCS.currency }),
    has_variants: Type.Boolean({ description: FIELD_DOCS.has_variants }),
    variant_axes: Type.Array(Type.String(), { description: FIELD_DOCS.variant_axes }),
  });
  const tool: Tool<typeof parameters> = {
    name: 'record_product_observation',
    description:
      'Record the product page that is open now as one product observation: its price, ' +
      'currency and variant facts. Call it while the product page is open. The tool adds a ' +
      'key of the page and writes artifact/parts/<task_id>.product-<key>.json.',
    parameters,
    async execute({ task_id: taskId, ...facts }, ctx) {
      if (!TASK_ID.test(taskId)) return errorResult(`invalid task id ${JSON.stringify(taskId)}.`);
      const observation = productObservationSchema.safeParse(facts);
      if (!observation.success) {
        return errorResult(
          `the observation does not match the schema: ${schemaIssues(observation.error)}`,
        );
      }
      try {
        const { key, path } = await keyOfOpenPage(session.page);
        const name = `${taskId}.product-${key}.json`;
        const partsDir = join(ctx.cwd, 'artifact', 'parts');
        mkdirSync(partsDir, { recursive: true });
        writeFileSync(join(partsDir, name), `${JSON.stringify(observation.data, null, 2)}\n`);
        return textResult(`Recorded the product page ${path} as artifact/parts/${name}.`);
      } catch (error) {
        return errorResult(error);
      }
    },
  };
  return tool;
}
