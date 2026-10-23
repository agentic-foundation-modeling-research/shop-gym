/**
 * The `capabilities.json` schema and the deterministic merge of the
 * per-task `parts/<task_id>.caps.json` fragments the executor writes.
 *
 * Every section is a closed object with nullable scalar fields and
 * empty-list defaults, so a fragment may carry any subset of keys. The
 * merge is pure and order-stable: fragments are read in filename order,
 * objects merge recursively, lists union (first occurrence wins), and a
 * scalar written by two fragments takes the last writer while recording a
 * `Conflict` for the manifest.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { z } from 'zod';

const nullableString = () => z.string().nullable().default(null);
const nullableBool = () => z.boolean().nullable().default(null);
const nullableInt = () => z.number().int().nullable().default(null);
const stringList = () => z.array(z.string()).default([]);

export const capabilitiesSchema = z.strictObject({
  version: z.string().default('0.2'),
  shop: z
    .strictObject({
      descriptor: nullableString(),
      category: nullableString(),
      currency: nullableString(),
      tone: stringList(),
    })
    .prefault({}),
  site_shell: z
    .strictObject({
      has_announcement_bar: nullableBool(),
      header_style: nullableString(),
      has_mega_menu: nullableBool(),
      nav_depth: nullableInt(),
      footer_groups: nullableInt(),
    })
    .prefault({}),
  homepage: z
    .strictObject({
      section_types: stringList(),
      section_count: nullableInt(),
      has_popup_modal: nullableBool(),
    })
    .prefault({}),
  collection: z
    .strictObject({
      layout: nullableString(),
      columns_desktop: nullableInt(),
      filters: stringList(),
      sort: stringList(),
      pagination: nullableString(),
    })
    .prefault({}),
  product: z
    .strictObject({
      gallery_style: nullableString(),
      variant_selectors: stringList(),
      has_quantity_selector: nullableBool(),
      description_layout: nullableString(),
      has_reviews: nullableBool(),
      has_recommendations: nullableBool(),
      has_personalization: nullableBool(),
    })
    .prefault({}),
  cart: z
    .strictObject({
      type: nullableString(),
      has_promo_input: nullableBool(),
      has_upsells: nullableBool(),
      has_shipping_estimate: nullableBool(),
    })
    .prefault({}),
  search: z
    .strictObject({
      trigger: nullableString(),
      has_predictive: nullableBool(),
      predictive_types: stringList(),
      results_layout: nullableString(),
    })
    .prefault({}),
  floating: z
    .strictObject({
      has_chat_widget: nullableBool(),
      has_age_gate: nullableBool(),
      has_cookie_banner: nullableBool(),
      has_newsletter_popup: nullableBool(),
    })
    .prefault({}),
  intl: z
    .strictObject({
      has_locale_switcher: nullableBool(),
      has_currency_switcher: nullableBool(),
    })
    .prefault({}),
  account: z
    .strictObject({
      has_login: nullableBool(),
      has_signup: nullableBool(),
      has_profile: nullableBool(),
      has_addresses: nullableBool(),
      has_order_history: nullableBool(),
    })
    .prefault({}),
  checkout: z
    .strictObject({
      has_guest_checkout: nullableBool(),
      payment_methods: stringList(),
      has_discount_code: nullableBool(),
      shipping_options: stringList(),
    })
    .prefault({}),
  info_pages_present: stringList(),
});

export type Capabilities = z.infer<typeof capabilitiesSchema>;

/** The top-level keys a fragment may carry. */
export const CAPABILITY_KEYS: readonly string[] = Object.keys(capabilitiesSchema.shape);

/** The schema rendered as JSON Schema text, for the agent constitution. */
export function capabilitiesJsonSchema(): string {
  return JSON.stringify(z.toJSONSchema(capabilitiesSchema), null, 2);
}

/** A scalar leaf written by two fragments with different values. */
export interface Conflict {
  readonly path: string;
  readonly previous_value: unknown;
  readonly previous_source: string;
  readonly new_value: unknown;
  readonly new_source: string;
}

export interface MergeResult {
  readonly capabilities: Capabilities;
  readonly conflicts: readonly Conflict[];
}

export class CapabilitiesValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CapabilitiesValidationError';
  }
}

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Validates a full capabilities document. */
export function parseCapabilities(value: unknown): Capabilities {
  const result = capabilitiesSchema.safeParse(value);
  if (!result.success) {
    throw new CapabilitiesValidationError(
      `merged capabilities failed schema validation: ${z.prettifyError(result.error)}`,
    );
  }
  return result.data;
}

function loadFragment(partsDir: string, name: string): JsonObject {
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(join(partsDir, name), 'utf8'));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new CapabilitiesValidationError(`fragment ${name} is not valid JSON: ${message}`);
  }
  if (!isObject(parsed)) {
    const kind = Array.isArray(parsed) ? 'array' : parsed === null ? 'null' : typeof parsed;
    throw new CapabilitiesValidationError(`fragment ${name} must be a JSON object, got ${kind}`);
  }
  return parsed;
}

function hashableKey(value: unknown): string {
  if (typeof value !== 'object' || value === null) return `${typeof value}:${String(value)}`;
  const sortKeys = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(sortKeys);
    if (isObject(node)) {
      return Object.fromEntries(
        Object.keys(node)
          .sort()
          .map((key) => [key, sortKeys(node[key])]),
      );
    }
    return node;
  };
  return `json:${JSON.stringify(sortKeys(value))}`;
}

function seedSources(value: unknown, path: string, source: string, sources: Map<string, string>) {
  if (isObject(value)) {
    for (const [key, child] of Object.entries(value)) {
      seedSources(child, path === '' ? key : `${path}.${key}`, source, sources);
    }
  } else if (!Array.isArray(value)) {
    sources.set(path, source);
  }
}

function deepMerge(
  target: JsonObject,
  incoming: JsonObject,
  source: string,
  path: string,
  sources: Map<string, string>,
  conflicts: Conflict[],
): void {
  for (const [key, value] of Object.entries(incoming)) {
    const childPath = path === '' ? key : `${path}.${key}`;
    if (!(key in target)) {
      target[key] = value;
      seedSources(value, childPath, source, sources);
      continue;
    }
    const existing = target[key];
    if (isObject(existing) && isObject(value)) {
      deepMerge(existing, value, source, childPath, sources, conflicts);
      continue;
    }
    if (Array.isArray(existing) && Array.isArray(value)) {
      const seen = new Set(existing.map(hashableKey));
      for (const item of value) {
        const itemKey = hashableKey(item);
        if (!seen.has(itemKey)) {
          seen.add(itemKey);
          existing.push(item);
        }
      }
      continue;
    }
    if (hashableKey(existing) !== hashableKey(value)) {
      conflicts.push({
        path: childPath,
        previous_value: existing,
        previous_source: sources.get(childPath) ?? '<unknown>',
        new_value: value,
        new_source: source,
      });
    }
    target[key] = value;
    sources.set(childPath, source);
  }
}

/**
 * Merges every `*.caps.json` under `partsDir` (filename order) into one
 * validated `Capabilities`.
 *
 * @throws Error when `partsDir` does not exist.
 * @throws CapabilitiesValidationError on a malformed fragment or an
 *   invalid merged document.
 */
export function mergeFragments(partsDir: string): MergeResult {
  const names = readdirSync(partsDir)
    .filter((name) => name.endsWith('.caps.json'))
    .sort();
  const merged: JsonObject = {};
  const sources = new Map<string, string>();
  const conflicts: Conflict[] = [];
  for (const name of names) {
    deepMerge(merged, loadFragment(partsDir, name), name, '', sources, conflicts);
  }
  return { capabilities: parseCapabilities(merged), conflicts };
}
