import { createSchema as createYogaSchema } from 'graphql-yoga';

/**
 * Creates the ShopBackend GraphQL schema.
 *
 * This is a placeholder schema. The production schema will mirror Shopify's
 * Storefront/Admin API surface and resolve against SandboxShop data.
 */
export function createSchema() {
  return createYogaSchema({
    typeDefs: /* GraphQL */ `
      type Query {
        """Health check."""
        ping: String!
      }
    `,
    resolvers: {
      Query: {
        ping: () => 'pong',
      },
    },
  });
}
