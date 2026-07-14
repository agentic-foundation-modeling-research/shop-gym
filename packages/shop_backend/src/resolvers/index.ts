/**
 * Resolver-layer entry point. Exposes the typed `ResolverContext` shared by
 * every resolver module under this directory and the combined
 * `sandboxResolvers` map wired into `createSandboxSchema` by default.
 *
 * Resolver areas covered to date: shop / menu / localization (T2.3),
 * product / collection (T2.4), page / blog / article (T2.5), search
 * (T3.1 + T3.2 + T3.3), cart-read (T4.2 — `Query.cart` + the
 * `BaseCartLine` / `Merchandise` discriminators), cart line mutations
 * (T4.3 — `cartCreate` / `cartLinesAdd` / `cartLinesUpdate` /
 * `cartLinesRemove`), product / collection metafields (T5.1), shop
 * metafields (T5.2).
 */

import type { SandboxShopData } from '../data/types.js';
import type { SandboxSchemaResolvers } from '../schema.js';
import type { ImageUrlMode } from './builders.js';
import { type CartStore, cartResolvers } from './cart.js';
import { contentResolvers } from './content.js';
import { metafieldResolvers } from './metafields.js';
import { productResolvers } from './product.js';
import { searchResolvers } from './search.js';
import { shopResolvers } from './shop.js';

/**
 * Per-request context passed to every resolver. `data` is the loaded dataset
 * snapshot; `carts` is the per-server in-memory cart store (spec §5.5);
 * `baseUrl` is the public GraphQL origin exposed by the server handle.
 */
export interface ResolverContext {
  readonly data: SandboxShopData;
  readonly carts: CartStore;
  readonly baseUrl: string;
  readonly imageUrlMode?: ImageUrlMode;
}

/**
 * Combined resolver map for every area implemented to date. Each per-area
 * map owns its own `Query` slice; we merge the slices here into a single
 * `Query` map so graphql-yoga sees one resolver per top-level field.
 *
 * Type-level note: the per-area maps are deliberately untyped against
 * `SandboxSchemaResolvers` to keep their argument types narrow. The merged
 * shape is checked here, at the seam, so any drift between a per-area map
 * and the SDL surfaces as a type error on this assignment.
 */
export const sandboxResolvers: SandboxSchemaResolvers = {
  Query: {
    ...shopResolvers.Query,
    ...productResolvers.Query,
    ...contentResolvers.Query,
    ...searchResolvers.Query,
    ...cartResolvers.Query,
  },
  Mutation: {
    ...cartResolvers.Mutation,
  },
  Shop: { ...shopResolvers.Shop, ...metafieldResolvers.Shop },
  Product: { ...productResolvers.Product, ...metafieldResolvers.Product },
  Collection: { ...productResolvers.Collection, ...metafieldResolvers.Collection },
  Blog: contentResolvers.Blog,
  SearchResultItem: searchResolvers.SearchResultItem,
  Cart: cartResolvers.Cart,
  BaseCartLine: cartResolvers.BaseCartLine,
  Merchandise: cartResolvers.Merchandise,
};
