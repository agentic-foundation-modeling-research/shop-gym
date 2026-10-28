# Brand names come from a fixed list of invented brands

A blocklist of real brands can never be complete, so generated shops use an allowlist instead. The shop name and every product vendor must be one of the invented brands in `gen/brands/fake_brands.json` (for example `Shopliseum`, `AisleArena`): `synth_identity` picks the shop name from the list by a hash, and product details with any other vendor fail validation.

## Consequences

- Many generated shops share the same few names.
- Free prose (titles, descriptions, pages) is only scanned and logged, not rejected.
