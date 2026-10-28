# Generation reads only anonymized Shop Manuals, never the live store

Explore visits a real storefront and writes an anonymized Shop Manual (`manual.md`, `capabilities.json`, `stats.json`). Generation takes one or more manuals as its only input and synthesizes every product, page and customer from them; it does not read the store, the prefetched catalog or the raw evidence. This keeps real merchant data and branding out of every SandboxShop, at the cost of a less faithful copy of the reference store.

## Consequences

The manual is the only privacy boundary, so explore enforces it with a deterministic anonymization verifier. It fails any manual part that contains the store's host, its URLs, brand tokens from its title, or an email address.
