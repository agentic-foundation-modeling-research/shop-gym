# Example shops

This directory contains checked-in SandboxShop examples that can be used without running the full shop-generation pipeline.

Each shop directory follows the same layout produced by `shop-gen`.
To host an example shop locally, copy it into `outputs/shops/` and install the storefront dependencies if needed:

```bash
mkdir -p outputs/shops
cp -R examples/shops/mock_clothing outputs/shops/
(cd outputs/shops/mock_clothing/runs/build/artifact/hydrogen && pnpm install)
pnpm shop:host start mock_clothing
```

Replace `mock_clothing` with another example shop name as needed.
