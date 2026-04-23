# ShopArena

Environment Factory that generates deterministic, self-contained sandbox shops
(**SandboxShops**) from any live storefront using modern web development stacks.

The `shop-arena` distribution ships two top-level modules:

- **`shop_gen`** — main SandboxShop generation pipeline.
- **`shop_explore`** — (scaffold) exploration of live storefronts to feed the pipeline.

## Status

Scaffolded. No features implemented yet. See `docs/specs/` for planned design.

## Install (dev)

```bash
uv sync
```

## Usage

```bash
uv run shop-gen --help
uv run shop-explore --help
```
