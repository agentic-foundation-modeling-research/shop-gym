# Storefront templates

`shop_arena.gen` bootstraps each generated shop by copying a storefront template from this directory into the run workspace.

The default build path expects a Hydrogen-compatible template at:

```text
packages/shop_arena/src/shop_arena/gen/templates/hydrogen/
```

You can adapt any open-source Hydrogen starter into that directory as the baseline storefront.
The pipeline then mutates the copied template during the build phase while leaving the original template unchanged.
