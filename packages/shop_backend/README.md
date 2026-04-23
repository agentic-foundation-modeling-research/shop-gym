# ShopBackend

Local GraphQL server that backs SandboxShop sandboxes. Mirrors Shopify's
Storefront/Admin API surface, serving products and collections from a SandboxShop
dataset. Used both for reliable benchmarking and as an RL environment for
shopping LLM agents.

## Status

Scaffolded. Only a "hello world" GraphQL endpoint is wired. No Shopify schema
coverage yet. See `docs/specs/` for planned design.

## Install (dev)

```bash
pnpm install
```

## Usage

```bash
pnpm --filter @shop-gym/shop-backend dev
# GraphQL playground: http://localhost:4000/graphql
```

## Build

```bash
pnpm --filter @shop-gym/shop-backend build
```
