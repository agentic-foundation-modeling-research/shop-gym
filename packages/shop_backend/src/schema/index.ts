/**
 * GraphQL schema assembly. Each domain owns one SDL module in this directory;
 * the modules are merged at startup (graphql-tools merges the repeated
 * `Query` / `Mutation` definitions). Fields and types marked `@sandbox` are
 * ShopGym additions with no Storefront API equivalent.
 *
 * Run `pnpm --filter @shop-gym/shop-backend codegen` after editing any SDL
 * module so `src/__generated__/resolvers-types.ts` stays in sync.
 */

import type { GraphQLSchema } from 'graphql';
import { createSchema as createYogaSchema } from 'graphql-yoga';
import { sandboxResolvers } from '../resolvers/index.js';
import { cartTypeDefs } from './cart.js';
import { catalogTypeDefs } from './catalog.js';
import { checkoutTypeDefs } from './checkout.js';
import { commonTypeDefs } from './common.js';
import { contentTypeDefs } from './content.js';
import { customerTypeDefs } from './customer.js';
import { directivesTypeDefs } from './directives.js';
import { orderTypeDefs } from './order.js';
import { searchTypeDefs } from './search.js';
import { shopTypeDefs } from './shop.js';

/**
 * Resolvers parameter accepted by `createSandboxSchema`. Inferred from
 * graphql-yoga's `createSchema` signature so tests and future callers can
 * pass per-area resolver maps without depending on `@graphql-tools/schema`
 * directly.
 */
export type SandboxSchemaResolvers = NonNullable<
  Parameters<typeof createYogaSchema>[0]['resolvers']
>;

/** Every SDL module, in merge order. */
export const typeDefs: readonly string[] = [
  directivesTypeDefs,
  commonTypeDefs,
  shopTypeDefs,
  catalogTypeDefs,
  contentTypeDefs,
  searchTypeDefs,
  cartTypeDefs,
  customerTypeDefs,
  orderTypeDefs,
  checkoutTypeDefs,
];

/**
 * Builds the SandboxShop GraphQL schema.
 *
 * Defaults to the combined `sandboxResolvers` map exported from
 * `resolvers/index.ts`, so callers get a runnable schema with no extra wiring.
 * Per-area tests still pass narrower resolver maps (e.g. `shopResolvers`) to
 * isolate the surface under test.
 */
export function createSandboxSchema(
  resolvers: SandboxSchemaResolvers = sandboxResolvers,
): GraphQLSchema {
  return createYogaSchema({ typeDefs: [...typeDefs], resolvers });
}
