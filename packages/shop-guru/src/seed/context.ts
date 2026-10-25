/**
 * What every seed generator receives, plus the helpers they share.
 */

import type { Task } from '@shop-gym/core';
import type { SandboxShopData } from '@shop-gym/shop-backend';

import { type Rng, createRng } from './rng.js';

/** Inputs to one generator call. */
export interface SeedContext {
  /** Shop slug; prefixes every task id. */
  readonly shop: string;
  readonly data: SandboxShopData;
  /** Seed string; each generator derives its own `Rng` from it. */
  readonly seed: string;
}

/** A generator: pure function from dataset to at most `count` tasks of one skill. */
export type SeedGenerator = (ctx: SeedContext, count: number) => Task[];

/** Canonical task id, stable across regenerations: `<shop>-<skill>-<n>`. */
export function makeTaskId(shop: string, skill: string, index: number): string {
  return `${shop}-${skill}-${index}`;
}

/** An `Rng` scoped to one skill so adding a generator never reshuffles another. */
export function skillRng(ctx: SeedContext, skill: string): Rng {
  return createRng(`${ctx.seed}:${skill}`);
}

/** `gid://shopify/ProductVariant/<id>` as the backend renders it. */
export function variantGid(variantId: number): string {
  return `gid://shopify/ProductVariant/${variantId}`;
}

/** `gid://shopify/Customer/<id>` as the backend renders it. */
export function customerGid(customerId: number): string {
  return `gid://shopify/Customer/${customerId}`;
}
