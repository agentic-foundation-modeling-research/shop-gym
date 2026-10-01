/**
 * Benchmark task contract.
 *
 * A task is one benchmark item: a natural-language `goal`, an optional
 * `setup` applied before the agent starts, and a list of `eval` checks a
 * grader runs afterwards. Every check is gradable by code except
 * `llm_judge`, which is explicit and opt-in per task.
 *
 * Field names in this contract are camelCase; the check `type` tags are
 * snake_case identifiers.
 */

import { z } from 'zod';

/** Lower-case identifier used for task ids, shop names, skills, and personas. */
const identifierSchema = z
  .string()
  .regex(/^[a-z0-9][a-z0-9_-]*$/, 'expected a lower-case identifier');

/** JSON value, used where a check carries an arbitrary expected value. */
const jsonValueSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([
    z.string(),
    z.number(),
    z.boolean(),
    z.null(),
    z.array(jsonValueSchema),
    z.record(z.string(), jsonValueSchema),
  ]),
);

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/** Compares the agent's final answer against reference strings. */
const stringMatchCheckSchema = z
  .object({
    type: z.literal('string_match'),
    /** Every listed string must appear in the answer (case-insensitive). */
    mustInclude: z.array(z.string().min(1)).min(1).optional(),
    /** The answer must match this string exactly after trimming. */
    exactMatch: z.string().min(1).optional(),
    /** The answer must be factually equivalent to this string; paraphrase allowed. */
    fuzzyMatch: z.string().min(1).optional(),
  })
  .refine(
    (c) => c.mustInclude !== undefined || c.exactMatch !== undefined || c.fuzzyMatch !== undefined,
    'string_match needs at least one of mustInclude, exactMatch, fuzzyMatch',
  );

/** Compares the URL the agent finished on against a reference URL. */
const urlMatchCheckSchema = z.object({
  type: z.literal('url_match'),
  /** Reference URL or path; a path is resolved against the shop's base URL. */
  url: z.string().min(1),
  /** How the final URL must relate to `url`. */
  rule: z.enum(['exact', 'prefix', 'contains']),
});

/**
 * Queries elements on a page with a Playwright selector and compares their
 * text against reference strings.
 *
 * `exactMatch` passes when one matched element's trimmed inner text equals
 * it; `mustInclude` passes when the matched elements' combined inner text
 * contains every listed string (case-insensitive).
 */
const locatorProbeCheckSchema = z.object({
  type: z.literal('locator_probe'),
  /** Page to probe: `"last"` for the page the agent finished on, otherwise a URL or path. */
  url: z.string().min(1),
  /** Playwright selector (CSS, `text=`, `role=`, ...), e.g. `.cart-line .title`. */
  locator: z.string().min(1),
  required: z
    .object({
      exactMatch: z.string().optional(),
      mustInclude: z.array(z.string().min(1)).min(1).optional(),
    })
    .refine(
      (r) => r.exactMatch !== undefined || r.mustInclude !== undefined,
      'locator_probe.required needs exactMatch or mustInclude',
    ),
});

/**
 * Compares the episode's backend state (the sandbox `StateSnapshot`) against
 * an expected value.
 *
 * `path` is an RFC 6901 JSON pointer into the snapshot. `match` selects the
 * comparison: `equals` is deep equality, `subset` requires `value` to be a
 * deep partial of the resolved object, and `some` requires the resolved
 * array to contain an element of which `value` is a deep partial.
 */
const stateCheckSchema = z.object({
  type: z.literal('state_check'),
  path: z.string().regex(/^(\/[^/]*)*$/, 'expected an RFC 6901 JSON pointer'),
  match: z.enum(['equals', 'subset', 'some']),
  value: jsonValueSchema,
});

/** Delegates the verdict to an LLM judge with a task-specific rubric. */
const llmJudgeCheckSchema = z.object({
  type: z.literal('llm_judge'),
  rubric: z.string().min(1),
});

export const checkSchema = z.discriminatedUnion('type', [
  stringMatchCheckSchema,
  urlMatchCheckSchema,
  locatorProbeCheckSchema,
  stateCheckSchema,
  llmJudgeCheckSchema,
]);

/** State applied through the sandbox control API before the agent starts. */
const taskSetupSchema = z.object({
  /** Persona id from the dataset's `customers.json` to log in as. */
  login: identifierSchema.optional(),
  /** Lines pre-filled into the episode's cart. */
  cart: z
    .array(
      z.object({
        variantId: z.number().int().positive(),
        quantity: z.number().int().positive(),
      }),
    )
    .min(1)
    .optional(),
});

export const taskSchema = z.object({
  id: identifierSchema,
  shop: identifierSchema,
  /** Skill category used for aggregation, e.g. `exact_product`, `checkout`. */
  skill: identifierSchema,
  goal: z.string().min(1),
  setup: taskSetupSchema.optional(),
  eval: z.array(checkSchema).min(1),
  /** `seed` tasks come from deterministic generators; `explore` tasks from an agent. */
  source: z.enum(['seed', 'explore']),
  /** Free-form provenance (reference answer, screenshots, explorer notes). */
  evidence: z.record(z.string(), z.unknown()).optional(),
});

export type StringMatchCheck = z.infer<typeof stringMatchCheckSchema>;
export type UrlMatchCheck = z.infer<typeof urlMatchCheckSchema>;
export type LocatorProbeCheck = z.infer<typeof locatorProbeCheckSchema>;
export type StateCheck = z.infer<typeof stateCheckSchema>;
export type LlmJudgeCheck = z.infer<typeof llmJudgeCheckSchema>;
export type Check = z.infer<typeof checkSchema>;
export type TaskSetup = z.infer<typeof taskSetupSchema>;
export type Task = z.infer<typeof taskSchema>;
