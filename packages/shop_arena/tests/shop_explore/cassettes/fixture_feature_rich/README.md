# `fixture_feature_rich` cassette

Hand-crafted replay cassette modelling a **feature-rich** Shopify
storefront profile, used by `tests/shop_explore/test_pipeline_replay.py`
(T4.2).

The feature-rich profile is deliberately authored with a **distinct
task set** from `fixture_drawer_shop` so the parameterized replay
test exercises a different cross-section of the §5.5 capabilities
schema:

| Iter        | Selected task        | Capabilities fragment surfaces                |
| ----------- | -------------------- | ---------------------------------------------- |
| `plan`      | —                    | four tasks + one omitted area in plan.md       |
| `exec-0001` | `homepage_sections`  | `site_shell`, `homepage`, `intl` (both switchers) |
| `exec-0002` | `header_navigation`  | `site_shell.has_mega_menu=true`, `nav_depth=2` |
| `exec-0003` | `collection_filters` | `collection` (4 filters, 5 sort), `search` (predictive) |
| `exec-0004` | `cart_drawer`        | `cart` (drawer + upsells + promo), `product` (variants) |

## Provenance

This is a **synthetic placeholder cassette**, not a recording of any
live storefront. The cassette is hand-authored to advertise the
documented feature-rich profile (mega menu, faceted filters, drawer
cart with upsells, predictive search, locale + currency switchers) so
the replay pipeline test exercises the feature-rich shape end-to-end.
Refresh in place when a recorded cassette is added; the README header
in `cassettes/README.md` tracks status.

## Shape

```
fixture_feature_rich/
├── plan/
│   ├── trajectory.json
│   └── workspace_after/plan.md
├── exec-0001/                  # selects homepage_sections
├── exec-0002/                  # selects header_navigation
├── exec-0003/                  # selects collection_filters
└── exec-0004/                  # selects cart_drawer
```

Each iteration matches the harness §5.6 minimal cassette layout.
