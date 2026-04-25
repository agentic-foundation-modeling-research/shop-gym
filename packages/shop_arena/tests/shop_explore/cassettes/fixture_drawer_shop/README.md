# `fixture_drawer_shop` cassette

Hand-crafted replay cassette covering one synthetic feature-rich Shopify
storefront ("drawer shop") used by `tests/shop_explore/test_pipeline_replay.py`
(T2.6) and the deterministic structural validator
`tests/shop_explore/test_fixture_drawer_shop_cassette.py` (T2.5).

The fixture exercises the four executor task types the spec calls out
in §5.7 of `docs/specs/shop_arena/shop_explore.md`:

| Iter        | Selected task        | Capabilities fragment surfaces           |
| ----------- | -------------------- | ----------------------------------------- |
| `plan`      | —                    | writes `plan.md` with the four tasks      |
| `exec-0001` | `homepage_sections`  | `homepage`, `site_shell`                  |
| `exec-0002` | `cart_drawer`        | `cart` (`type=drawer`)                    |
| `exec-0003` | `search_predictive`  | `search` (`has_predictive=true`)          |
| `exec-0004` | `collection_filters` | `collection`, `intl`                      |

Each executor iteration's `workspace_after/artifact/` writes
`parts/<task>.md`, `parts/<task>.caps.json`, and at least one evidence
file under `evidence/<task>/`. The `parts/*.caps.json` fragments together
deep-merge into a complete §5.5 `Capabilities` document with no
conflicts.

## Shape

```
fixture_drawer_shop/
├── plan/
│   ├── trajectory.json
│   └── workspace_after/
│       └── plan.md
├── exec-0001/                  # selects homepage_sections
│   ├── trajectory.json
│   └── workspace_after/
│       ├── plan.md             # task flipped to [x]
│       └── artifact/
│           ├── parts/
│           │   ├── homepage_sections.md
│           │   └── homepage_sections.caps.json
│           └── evidence/homepage_sections/snapshot.md
├── exec-0002/                  # selects cart_drawer
├── exec-0003/                  # selects search_predictive
└── exec-0004/                  # selects collection_filters
```

Each iteration matches the harness §5.6 minimal cassette layout:
`trajectory.json`, optional `native.log` (omitted here), and
`workspace_after/` (the evolving workspace surface the iteration leaves
behind). The trajectories are small message-only stubs: the published
contract of this cassette is the *workspace overlay*, not the trajectory
content. `prompt_sha256` is a placeholder; the harness loop normalises
it against the actual prompt at replay time.

## Refreshing

This cassette is hand-crafted, not recorded. Edit the relevant
`workspace_after/` files to extend coverage and update the
`*.caps.json` fragments accordingly. Rerun
`pytest packages/shop_arena/tests/shop_explore/test_fixture_drawer_shop_cassette.py`
to confirm the cassette still validates.
