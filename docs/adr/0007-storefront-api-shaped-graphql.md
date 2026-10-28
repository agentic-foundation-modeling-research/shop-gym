# The backend speaks a Storefront-API-shaped GraphQL subset

The sandbox backend copies a subset of Shopify's Storefront API on the wire: the same type and operation names, served at `/graphql` and `/api/<version>/graphql.json`. We chose this over a simpler REST or custom API because build agents and the storefront template already know the Storefront API from training data, and the SDL plus codegen gives cheap type safety. Operations with no Storefront API equivalent (for example `checkoutComplete`, `commerceSettings`, `Query.order`) carry a `@sandbox` directive, so the Shopify-compatible part stays clear.

## Consequences

- The storefront template uses one hand-written typed client (`storefrontQuery`), not a vendor SDK.
- Checkout is one sandbox mutation from cart to order. Shopify retired its Checkout API, so there is no `checkoutCreate` to copy.
