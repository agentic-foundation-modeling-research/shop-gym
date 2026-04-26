/**
 * Resolver-layer entry point. Exposes the typed `ResolverContext` shared by
 * every resolver module under this directory and the combined
 * `sandboxResolvers` map wired into `createSandboxSchema` by default.
 *
 * Resolver areas covered to date: shop / menu / localization (T2.3),
 * product / collection (T2.4), page / blog / article (T2.5), search
 * (T3.1 + T3.2 + T3.3 — `Query.search`, `Query.predictiveSearch`,
 * `Query.productRecommendations`). Cart (M4) and metafield (M5) maps land
 * in subsequent milestones and are merged into `sandboxResolvers` as they
 * ship.
 */

import type { SandboxShopData } from '../data/types.js';
import type { SandboxSchemaResolvers } from '../schema.js';
import { contentResolvers } from './content.js';
import { productResolvers } from './product.js';
import { searchResolvers } from './search.js';
import { shopResolvers } from './shop.js';

/**
 * Per-request context passed to every resolver. `data` is the loaded dataset
 * snapshot; `baseUrl` is the public origin (e.g. `https://shop.example`) used
 * when rewriting relative image paths into absolute URLs (see spec §5.3).
 *
 * The cart store is intentionally absent at this milestone; it lands with the
 * cart resolvers in M4.
 */
export interface ResolverContext {
  readonly data: SandboxShopData;
  readonly baseUrl: string;
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
  },
  Shop: shopResolvers.Shop,
  Product: productResolvers.Product,
  Collection: productResolvers.Collection,
  Blog: contentResolvers.Blog,
  SearchResultItem: searchResolvers.SearchResultItem,
};
