/**
 * Skill `filter`: apply one filter in a collection and report how many
 * products remain.
 *
 * The filter dimension and value are drawn from the collection's own products
 * so the pair is always realizable; the expected count is the number of
 * member products carrying that value, which makes the task gradable with a
 * `string_match` on the answer.
 */

import type { Task } from '@shop-gym/core';
import type { Collection, SandboxShopData } from '@shop-gym/shop-backend';

import { type SeedContext, makeTaskId, skillRng } from './context.js';
import { collectionsWithMinProducts } from './filters.js';

export const SKILL = 'filter';
const MIN_PRODUCTS = 5;

/** Variant-option dimensions tried first, in order. */
const PRIORITY_DIMENSIONS: readonly string[] = [
  'Color',
  'Size',
  'Format',
  'Material',
  'Style',
  'Design',
];
/** Top-level product fields every storefront filter UI can render. */
const UNIVERSAL_DIMENSIONS: readonly string[] = ['Vendor', 'ProductType'];
const SKIP_VALUES: ReadonlySet<string> = new Set(['title', 'default', 'default title', '']);
const DISPLAY: Readonly<Record<string, string>> = { ProductType: 'Type', Vendor: 'Brand' };

/** `{dimension: {value: product count}}` over the collection's members. */
function optionIndex(
  collection: Collection,
  data: SandboxShopData,
): Map<string, Map<string, number>> {
  const index = new Map<string, Map<string, number>>();
  const bump = (dim: string, value: string): void => {
    const v = value.trim();
    if (v === '' || SKIP_VALUES.has(v.toLowerCase())) return;
    const values = index.get(dim) ?? new Map<string, number>();
    values.set(v, (values.get(v) ?? 0) + 1);
    index.set(dim, values);
  };
  for (const handle of collection.product_handles) {
    const product = data.productsByHandle.get(handle);
    if (product === undefined) continue;
    bump('Vendor', product.vendor);
    bump('ProductType', product.product_type);
    for (const option of product.options) {
      const name = option.name.trim();
      if (SKIP_VALUES.has(name.toLowerCase())) continue;
      // Count each product once per value even when several variants share it.
      for (const value of new Set(option.values)) bump(name, value);
    }
  }
  return index;
}

interface FilterChoice {
  readonly dimension: string;
  readonly value: string;
  readonly matching: number;
}

/** Highest-priority feasible (dimension, value); the value is the first in sort order. */
function pickFilter(collection: Collection, data: SandboxShopData): FilterChoice | undefined {
  const index = optionIndex(collection, data);
  for (const dimension of [...PRIORITY_DIMENSIONS, ...UNIVERSAL_DIMENSIONS]) {
    const values = index.get(dimension);
    if (values === undefined) continue;
    const value = [...values.keys()].sort()[0];
    if (value !== undefined) {
      return { dimension, value, matching: values.get(value) ?? 0 };
    }
  }
  return undefined;
}

export function generate(ctx: SeedContext, count: number): Task[] {
  const rng = skillRng(ctx, SKILL);
  const candidates = rng.shuffle(collectionsWithMinProducts(ctx.data.collections, MIN_PRODUCTS));
  const tasks: Task[] = [];
  for (const collection of candidates) {
    if (tasks.length >= count) break;
    const choice = pickFilter(collection, ctx.data);
    if (choice === undefined) continue;
    const display = DISPLAY[choice.dimension] ?? choice.dimension;
    tasks.push({
      id: makeTaskId(ctx.shop, SKILL, tasks.length + 1),
      shop: ctx.shop,
      skill: SKILL,
      goal:
        `Open the "${collection.title}" collection and use its ${display} filter to show only ` +
        `"${choice.value}" products. Report how many products are listed after filtering.`,
      eval: [
        { type: 'string_match', mustInclude: [String(choice.matching)] },
        { type: 'url_match', url: `/collections/${collection.handle}`, rule: 'contains' },
      ],
      source: 'seed',
      evidence: { collectionHandle: collection.handle, filter: choice },
    });
  }
  return tasks;
}
