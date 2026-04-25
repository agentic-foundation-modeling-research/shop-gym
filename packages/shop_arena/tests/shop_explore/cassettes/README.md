# `tests/shop_explore/cassettes/`

Replay cassettes that drive `shop_explore`'s pipeline tests without
any live LLM or storefront calls. Each subdirectory is one cassette
keyed by a fixture-storefront slug.

Cassettes use the harness §5.6 minimal layout:

```
<fixture>/
├── plan/
│   ├── trajectory.json
│   └── workspace_after/        # files the planner iter leaves in run_dir
├── exec-0001/
│   ├── trajectory.json
│   └── workspace_after/
├── exec-0002/
│   …
```

`workspace_after/` is the contract: it is the run_dir overlay that the
harness re-applies during replay. `trajectory.json` is a small
message-only stub; cassette correctness is judged by the workspace, not
the trajectory content.

---

## Fixture inventory

| Fixture slug          | Source storefront                         | Role          | How recorded                | Status          |
| --------------------- | ----------------------------------------- | ------------- | --------------------------- | --------------- |
| `fixture_drawer_shop` | _synthetic_ (no live source)              | feature-rich  | hand-crafted (M2)           | ✅ committed    |
| `fixture_fermliving`  | `https://fermliving.com`                  | feature-rich  | live `pi` runtime (T4.2)    | ⏳ planned      |
| `fixture_dawn_demo`   | `https://theme-dawn-demo.myshopify.com`   | minimal       | live `pi` runtime (T4.2)    | ⏳ planned      |

The **synthetic** fixture (`fixture_drawer_shop`) is the canonical
hand-crafted cassette used by `test_pipeline_replay.py` and
`test_fixture_drawer_shop_cassette.py` — it does not correspond to any
real shop and is fully checked in. See its own
[`fixture_drawer_shop/README.md`](./fixture_drawer_shop/README.md).

The two **live-recorded** fixtures below back T4.2–T4.5 of the
implementation plan and are recorded by setting `HARNESS_RECORD=1` and
running `shop-explore --runtime pi <url>` against the live storefront.

---

## Live fixture choices (T4.1)

### `fixture_fermliving` — feature-rich

- **URL:** `https://fermliving.com`
- **Platform:** Shopify (verified — `/cart.js`, `/products.json`,
  `/collections.json`, `/sitemap.xml` all return 200).
- **Why feature-rich:** the storefront exercises the long tail of the
  §5.3 coverage taxonomy in a single shop:
  - **Site shell:** announcement bar, mega menu, multi-column footer.
  - **Homepage:** hero carousel, multiple featured-collection sections,
    editorial banners, newsletter, popup modal.
  - **Collection:** grid layout with size/color/price filters and a
    multi-option sort.
  - **Product:** thumbnail-strip gallery, color/size variant selectors,
    quantity selector, recommendations.
  - **Cart:** drawer (not page).
  - **Search:** predictive panel with products + collections.
  - **Intl:** locale switcher + currency switcher.
  - **Info:** about, contact, shipping, returns, privacy, ToS, FAQ.
- **Why this exact shop:** picked in the implementation plan
  (`docs/impl/shop_explore_implementation.md` §M4) because it is a
  long-lived, large-catalog Shopify storefront whose feature footprint
  hits every coverage-taxonomy area, making it the natural target for
  the M4 live e2e gate (T4.5) and for SC5 (coverage).
- **License / fair-use stance:** we record cassettes against the public
  storefront. The repo commits **only**:
  - the cassette `workspace_after/` overlay (anonymized
    `parts/<task>.md` + `parts/<task>.caps.json` + `evidence/<task>/`
    snapshots/screenshots), and
  - the synthesized Shop Manual (`manual.md` + `capabilities.json` +
    `stats.json` + `manifest.json`).

  Anonymization (per spec §5.10 and `prompts/agents.md`) strips brand
  names, store names, and product titles at executor write-time;
  `tests/shop_explore/test_anonymization.py` enforces this with a
  regex scan over the synthesized artefacts before commit. Raw
  prefetch responses (`prefetch/index.html`, `prefetch/products.json`,
  …) and trajectory `native.log` lines are **not** committed for
  live-recorded fixtures — they are gitignored under
  `cassettes/fixture_fermliving/_raw/` if generated.

  We do **not** redistribute Ferm Living's product imagery, copy, or
  brand assets. Screenshots committed under `evidence/` are evaluated
  case-by-case during cassette refresh (T4.2) and removed if they
  contain identifying brand artwork.

### `fixture_dawn_demo` — minimal

- **URL:** `https://theme-dawn-demo.myshopify.com`
- **Platform:** Shopify (verified — `/cart.js`, `/products.json`,
  `/sitemap.xml` all return 200; `x-storefront-renderer-rendered: 1`).
- **Why minimal:** this is Shopify's own **Dawn theme preview store**
  — the unmodified default theme installed against a demo catalog. It
  exercises the *floor* of the coverage taxonomy:
  - **Site shell:** simple horizontal header, no mega menu,
    single-column footer.
  - **Homepage:** hero + 1–2 featured sections, no popup, no
    announcement bar.
  - **Collection:** grid, default sort options, no faceted filters
    (Dawn ships sort but no out-of-the-box filter chips).
  - **Product:** simple gallery, basic variant pickers (when present),
    no reviews, no recommendations carousel.
  - **Cart:** drawer or notification (theme default).
  - **Search:** modal trigger; predictive results minimal.
  - **Intl:** locale + currency form (default Dawn includes both).
  - **Info:** policy pages only.
- **Why this exact shop:** the spec's M4 plan calls for "one feature-
  rich and one minimal" fixture so SC5 (coverage) and the
  `omitted_areas` reporting in `manifest.json` are exercised on a
  storefront that *legitimately omits* most taxonomy areas. The
  Shopify-owned Dawn demo is the canonical reference for what a
  newly-installed Shopify store looks like, and it is unlikely to be
  taken offline or radically restyled.
- **License / fair-use stance:** the storefront is owned and operated
  by Shopify Inc. as a public theme preview. The catalog (sample
  products, sample copy, sample imagery) is Shopify's own demo
  content. We treat it the same as `fixture_fermliving` for repo
  hygiene: only anonymized cassette overlays are committed; raw
  prefetch and trajectory logs are gitignored.

---

## Recording / refreshing live cassettes (T4.2)

Live cassettes are recorded by the harness, not authored by hand.

```bash
# Feature-rich fixture
HARNESS_RECORD=1 \
  uv run shop-explore https://fermliving.com \
  --runtime pi \
  --out packages/shop_arena/tests/shop_explore/cassettes/fixture_fermliving

# Minimal fixture
HARNESS_RECORD=1 \
  uv run shop-explore https://theme-dawn-demo.myshopify.com \
  --runtime pi \
  --out packages/shop_arena/tests/shop_explore/cassettes/fixture_dawn_demo
```

After recording:

1. Run `pytest packages/shop_arena/tests/shop_explore/test_anonymization.py`
   against the new cassette. **Must be green** — no leaks of source
   domain, store name, or first 20 product titles.
2. Hand-review `evidence/<task_id>/screenshots/*.png` for
   brand-identifying imagery; remove or redact as needed.
3. Strip `iters/*/native.log` of any API keys before committing
   (the harness writes these by default — they are not safe for
   public repos as-is).
4. Commit only the cassette overlay (`plan/`, `exec-*/`,
   `workspace_after/artifact/parts/`, `workspace_after/artifact/
   evidence/`) plus a per-fixture `README.md` mirroring
   `fixture_drawer_shop/README.md`.

`_raw/` and `**/native.log` for live-recorded fixtures are gitignored.
