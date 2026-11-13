# Generation also reads a Source bundle, and a given catalog keeps its real brands

ADR 0012, as extended by ADR 0017, makes the anonymized Shop Manual the input of Shop generation, plus, with `--data`, the catalog of an existing SandboxShop. `shopgym gen --bundle <dir>` adds one more input: a complete Source bundle. The team makes the bundle on purpose from a public dataset with `shopgym bundle` (first adapter: Amazon Reviews 2023). The bundle gives the catalog, the Reviews, one Persona for each Modeled user with the orders before the Cutoff, and the hidden `users/` directory. The Shop Manual still gives the identity, the store, the pages, the policies, the Commerce settings and the UX, and it stays anonymized. A bundle is data that the team chose, never the raw evidence of a Live storefront: no adapter reads a Live storefront, its prefetched catalog or the exploration evidence.

This also amends ADR 0013. A given catalog keeps its real brand and seller names. The fake-brand allowlist still names every shop (its store name), applies to every product that Shop generation synthesizes, and is planned to apply to a rewritten bundle.

## Considered Options

- Synthesize a catalog that imitates the dataset: an LLM writes about ten thousand products slowly and at a high cost, and the real reviews, ratings and shopper histories are lost, so a personal Task would have no true answer.
- Replace every brand with an allowlisted brand before Shop generation: the Brand facet, the brand preferences of User profiles and the joins back to the source would no longer agree with the source data. An optional rewrite step that changes only identifying text and images, and keeps every id, price, category and rating, stays planned for shops that must be safer to share.
- Explore the dataset as if it were a Live storefront: a dataset is files, not a site, and its catalog would then pass the Anonymization rules, which remove the very facts (brands, titles) that a marketplace catalog needs.

## Consequences

- A shop made from a bundle shows real product titles, brand and seller names, and review text from its source. It also has the license of its sources. Amazon Reviews 2023 has no license and is shared for research, so its bundles and shops are research-only and stay inside the team. `bundle.json` lists each source with its license, and the Shop manifest copies the list into `sourceBundle.sources`, with the bundle name, the Cutoff and the Clock offset.
- The store name never comes from the bundle: identity synthesis picks it from the allowlist, as for every shop. The brand scan at assembly also reads the bundle products and Reviews. It logs the capitalized tokens outside the allowlist and does not fail, so on a marketplace catalog it logs many tokens.
- The rule of ADR 0012 still holds for every Live storefront: Storefront exploration, its Anonymization verifier and its final scan do not change, and a Shop Manual is still the only thing that Shop generation reads from exploration.
- `--data` and `--bundle` cannot be used together. A shop without either one is synthesized from the Shop Manual as before.
- The User profiles and the User events at the Cutoff or later go to `users/`, next to `data/`. The backend loads only `data/`, so an agent cannot read a Task target through the shop.
