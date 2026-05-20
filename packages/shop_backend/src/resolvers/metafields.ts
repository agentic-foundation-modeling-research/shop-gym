/**
 * Resolvers for the Product / Collection / Shop metafield surface
 * (T5.1 + T5.2).
 *
 * Reads from the optional `metafields.json` file (`data.metafields`,
 * spec §8.1.2). When the file is absent the loader defaults the field to
 * `{ shop: [], products: {}, collections: {} }`, so every resolver here
 * gracefully returns `null` (or a same-length array of `null`s) on miss.
 *
 * Resolver shapes:
 *   - `Product.metafield(namespace, key): Metafield` — first match in the
 *     parent's metafield list, or `null`.
 *   - `Product.metafields(identifiers: [...]): [Metafield]!` — preserves
 *     the request order, with `null` for unmatched identifiers.
 *   - `Collection.metafield` / `Collection.metafields` — same shape, keyed
 *     by collection handle.
 *   - `Shop.metafield` / `Shop.metafields` — same shape against
 *     `data.metafields.shop`, keyed by `store.shop_id` for stable GIDs.
 *
 * `Metafield.id` is a deterministic GID derived from the owner scope/handle
 * plus `namespace:key` so identical inputs produce identical ids across
 * server reloads (per the GID hashing rule in spec §5.3). `parentResource`
 * and `reference` are unsurfaced for v0.1 — both resolve to `null` until a
 * future milestone adds the union shapes (see spec §5.2 deferral list).
 */

import type {
  CollectionMetafieldArgs,
  CollectionMetafieldsArgs,
  HasMetafieldsIdentifier,
  ProductMetafieldArgs,
  ProductMetafieldsArgs,
  ShopMetafieldArgs,
  ShopMetafieldsArgs,
} from '../__generated__/resolvers-types.js';
import type { Metafield } from '../data/types.js';
import type { CollectionNode, ProductNode } from './builders.js';
import { gid } from './builders.js';
import type { ResolverContext } from './index.js';
import type { ShopParentNode } from './shop.js';

// ── Node shape ─────────────────────────────────────────────────────────────
// Argument types are imported from the generated resolver module above; the
// hand-typed `MetafieldNode` parent shape stays because codegen mappers are
// deferred (see `codegen.ts`).

export interface MetafieldNode {
  readonly id: string;
  readonly namespace: string;
  readonly key: string;
  readonly value: string;
  readonly type: string;
  /** Deferred to a later milestone — `MetafieldParentResource` is unused in v0.1. */
  readonly parentResource: null;
  /** Deferred to a later milestone — `MetafieldReference` is unused in v0.1. */
  readonly reference: null;
}

// ── Internal helper types ─────────────────────────────────────────────────

type OwnerScope = 'Product' | 'Collection' | 'Shop';

// ── Resolvers ─────────────────────────────────────────────────────────────

/**
 * Resolver map for `Product.metafield(s)` and `Collection.metafield(s)`.
 * Merged into the combined `Product` / `Collection` resolver maps in
 * `resolvers/index.ts` alongside the existing nested resolvers.
 */
export const metafieldResolvers = {
  Product: {
    metafield: (
      parent: ProductNode,
      args: ProductMetafieldArgs,
      ctx: ResolverContext,
    ): MetafieldNode | null =>
      lookupMetafield('Product', parent.handle, productMetafields(ctx, parent.handle), args),

    metafields: (
      parent: ProductNode,
      args: ProductMetafieldsArgs,
      ctx: ResolverContext,
    ): readonly (MetafieldNode | null)[] =>
      lookupMetafields(
        'Product',
        parent.handle,
        productMetafields(ctx, parent.handle),
        args.identifiers,
      ),
  },

  Collection: {
    metafield: (
      parent: CollectionNode,
      args: CollectionMetafieldArgs,
      ctx: ResolverContext,
    ): MetafieldNode | null =>
      lookupMetafield('Collection', parent.handle, collectionMetafields(ctx, parent.handle), args),

    metafields: (
      parent: CollectionNode,
      args: CollectionMetafieldsArgs,
      ctx: ResolverContext,
    ): readonly (MetafieldNode | null)[] =>
      lookupMetafields(
        'Collection',
        parent.handle,
        collectionMetafields(ctx, parent.handle),
        args.identifiers,
      ),
  },

  Shop: {
    metafield: (
      _parent: ShopParentNode,
      args: ShopMetafieldArgs,
      ctx: ResolverContext,
    ): MetafieldNode | null =>
      lookupMetafield('Shop', shopOwnerHandle(ctx), shopMetafields(ctx), args),

    metafields: (
      _parent: ShopParentNode,
      args: ShopMetafieldsArgs,
      ctx: ResolverContext,
    ): readonly (MetafieldNode | null)[] =>
      lookupMetafields('Shop', shopOwnerHandle(ctx), shopMetafields(ctx), args.identifiers),
  },
};

// ── Helpers ────────────────────────────────────────────────────────────────

function productMetafields(ctx: ResolverContext, handle: string): readonly Metafield[] {
  return ctx.data.metafields.products[handle] ?? [];
}

function collectionMetafields(ctx: ResolverContext, handle: string): readonly Metafield[] {
  return ctx.data.metafields.collections[handle] ?? [];
}

function shopMetafields(ctx: ResolverContext): readonly Metafield[] {
  return ctx.data.metafields.shop;
}

/** Stable owner handle for shop-scoped metafield GIDs. */
function shopOwnerHandle(ctx: ResolverContext): string {
  return String(ctx.data.store.shop_id);
}

function lookupMetafield(
  scope: OwnerScope,
  ownerHandle: string,
  list: readonly Metafield[],
  identifier: HasMetafieldsIdentifier,
): MetafieldNode | null {
  const match = findMetafield(list, identifier);
  return match === null ? null : buildMetafieldNode(scope, ownerHandle, match);
}

function lookupMetafields(
  scope: OwnerScope,
  ownerHandle: string,
  list: readonly Metafield[],
  identifiers: readonly HasMetafieldsIdentifier[],
): readonly (MetafieldNode | null)[] {
  return identifiers.map((id) => lookupMetafield(scope, ownerHandle, list, id));
}

function findMetafield(
  list: readonly Metafield[],
  identifier: HasMetafieldsIdentifier,
): Metafield | null {
  for (const m of list) {
    if (m.namespace === identifier.namespace && m.key === identifier.key) return m;
  }
  return null;
}

function buildMetafieldNode(
  scope: OwnerScope,
  ownerHandle: string,
  metafield: Metafield,
): MetafieldNode {
  return {
    id: gid('Metafield', `${scope}:${ownerHandle}:${metafield.namespace}:${metafield.key}`),
    namespace: metafield.namespace,
    key: metafield.key,
    value: metafield.value,
    type: metafield.type,
    parentResource: null,
    reference: null,
  };
}
