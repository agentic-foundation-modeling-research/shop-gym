# `fixture_dawn_demo` cassette

Hand-crafted replay cassette modelling a **minimal** Shopify storefront
profile (the Dawn default-theme demo at
`https://theme-dawn-demo.myshopify.com`) used by
`tests/shop_explore/test_pipeline_replay.py` (T4.2).

The minimal profile exercises a different code path from
`fixture_drawer_shop`: the planner emits **fewer evidenced tasks** and
**more `## Omitted Areas`** entries, so the synthesis pipeline must
publish a coherent Shop Manual without the full coverage taxonomy
landing in `parts/`.

| Iter        | Selected task        | Capabilities fragment surfaces            |
| ----------- | -------------------- | ------------------------------------------ |
| `plan`      | —                    | three tasks + four omitted areas in plan.md |
| `exec-0001` | `homepage_sections`  | minimal `site_shell`, `homepage`, `floating` |
| `exec-0002` | `info_pages`         | `info_pages_present` (six pages)           |
| `exec-0003` | `cart_drawer`        | `cart` (`type=drawer`, no upsells)         |

## Provenance

This is a **synthetic placeholder cassette**, not a recording of the
live `theme-dawn-demo.myshopify.com` storefront. Live recording
remains a manual milestone gate (see `docs/impl/shop_explore_implementation.md`
T4.5 for the live e2e workflow). The cassette is hand-authored to
reflect the documented profile of the Dawn theme demo so the replay
pipeline test exercises a minimal-storefront shape end-to-end. Refresh
by re-running the live `pi` runtime under `HARNESS_RECORD=1` once the
recording infrastructure (T4.2 follow-up) lands.

## Shape

```
fixture_dawn_demo/
├── plan/
│   ├── trajectory.json
│   └── workspace_after/plan.md
├── exec-0001/                  # selects homepage_sections
├── exec-0002/                  # selects info_pages
└── exec-0003/                  # selects cart_drawer
```

Each iteration matches the harness §5.6 minimal cassette layout and the
ShopExplore §5.7 8-step executor obligation list (parts markdown +
caps fragment + at least one evidence file per task).
