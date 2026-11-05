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
 * metafields (T5.2), and since v1.1 the stateful customer / order /
 * checkout domains backed by the per-episode `ShopState`.
 */

import type { SandboxShopData } from '../data/types.js';
import type { SandboxSchemaResolvers } from '../schema/index.js';
import type { ShopState } from '../state/shop_state.js';
import type { ImageUrlMode } from './builders.js';
import { type CartStore, cartResolvers } from './cart.js';
import { checkoutResolvers } from './checkout.js';
import { contentResolvers } from './content.js';
import { customerResolvers } from './customer.js';
import { metafieldResolvers } from './metafields.js';
import { orderResolvers } from './order.js';
import { productResolvers } from './product.js';
import { searchResolvers } from './search.js';
import { shopResolvers } from './shop.js';

/**
 * Per-request context passed to every resolver. `data` is the episode's view
 * of the loaded dataset (live inventory); `state` is the episode's mutable
 * `ShopState` and `carts` its cart store; `baseUrl` is the public GraphQL
 * origin exposed by the server handle.
 */
export interface ResolverContext {
  readonly data: SandboxShopData;
  readonly state: ShopState;
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
    ...customerResolvers.Query,
    ...orderResolvers.Query,
    ...checkoutResolvers.Query,
  },
  Mutation: {
    ...cartResolvers.Mutation,
    ...customerResolvers.Mutation,
    ...checkoutResolvers.Mutation,
  },
  Shop: { ...shopResolvers.Shop, ...metafieldResolvers.Shop },
  Product: { ...productResolvers.Product, ...metafieldResolvers.Product },
  Collection: { ...productResolvers.Collection, ...metafieldResolvers.Collection },
  Blog: contentResolvers.Blog,
  SearchResultItem: searchResolvers.SearchResultItem,
  Cart: cartResolvers.Cart,
  CartBuyerIdentity: cartResolvers.CartBuyerIdentity,
  BaseCartLine: cartResolvers.BaseCartLine,
  CartDiscountAllocation: cartResolvers.CartDiscountAllocation,
  Merchandise: cartResolvers.Merchandise,
  Customer: customerResolvers.Customer,
  Order: orderResolvers.Order,
};
