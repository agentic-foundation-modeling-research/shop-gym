# Generation may copy the catalog of an existing SandboxShop Dataset

ADR 0012 makes the Shop Manual the only input of Shop generation. `shopgym gen --data <dir>` adds a second input: the products, collections and images of an existing SandboxShop Dataset, copied without change in place of a synthesized catalog. Everything else in the new Dataset is still synthesized from the manual. This lets an old shop's catalog move onto the current templates, so that Tasks and scores written against that catalog stay comparable.

## Considered Options

- Synthesize a new catalog that imitates the old one: the products, handles, ids and prices would change, so the old Tasks would no longer match the shop.
- Rebuild the old shop by hand on the new templates: every template change would need the same work again.

## Consequences

- `--data` reads only a Dataset that Shop generation made, never a Live storefront, its prefetched catalog or raw evidence, so the rule of ADR 0012 still holds for every Live storefront. The anonymization of a copied catalog is the anonymization of the shop it came from. The brand scan at assembly logs tokens outside the fake-brand allowlist in the copied catalog too, but it does not fail.
- The copied products and collections keep their ids and the fields that the backend schema does not name, so they are not checked against the synthesis rules for vendors, titles and catalog size. `data_validation` still checks them against the backend schema and for referential integrity.
- Every Shop manifest records its source Shop Manuals, with or without `--data`, so that shops that share a catalog but come from different manuals can be kept apart.
