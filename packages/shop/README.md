# Generated shops

Storefront code of SandboxShops that `shopgym gen` made, kept in the repository for review.
Each folder holds only the storefront source: the Build loop output on top of the storefront
template (`packages/shop-arena/templates/storefront`). It has no shop data, no backend, no
`node_modules` and no build output.

These folders are not workspace packages. The root `pnpm` scripts do not build, test or lint them.

| Folder | Shop | How it was made |
|---|---|---|
| `mock_amazon/` | The Video_Games POC shop. Its catalog, reviews and customers come from the Amazon Reviews 2023 dataset (`amazon_reviews_2023`). | `shopgym gen ... --bundle ... --from build`, Build loop of 2026-11-13. Storefront template with PRs #75 to #88 merged (local integration commit `cf5a6c55`, recorded in `template.json`). |

`template.json` records the template commit and the hash of each template file. The storefront
`README.md` is the template README.

## Run a storefront

The storefront needs a running `shop_backend` with the shop data. To make both, generate and
host the shop (see the root README). To start only the storefront against a running backend:

```bash
cd packages/shop/mock_amazon
pnpm install --ignore-workspace --frozen-lockfile
pnpm build
PUBLIC_STORE_DOMAIN=http://127.0.0.1:<backend port> PORT=4100 pnpm start
```

The `mock_amazon` storefront uses backend features from PRs #75 to #88 (for example search
facets, the rating histogram, review filters and related products). Run it only against a
backend that has them.
