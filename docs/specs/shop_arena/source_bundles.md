# Source bundles (`packages/core/src/bundle`, `packages/shop-arena/src/bundle`)

Status: **Implemented** (first adapter and first marketplace shop, 2026-11-12) · Version: **0.1**
Owners: ShopArena

> Shop generation gets a second input next to the Shop Manual: a Source
> bundle. A bundle holds a catalog, its reviews, and the User events and
> User profiles of a few Modeled users, in one standard shape for every
> source dataset. `shopgym bundle` builds a bundle from Amazon Reviews
> 2023 (AR23). `shopgym gen --bundle` maps it to the Dataset of a
> SandboxShop, with one Persona for each Modeled user, the orders before
> the Cutoff, and a hidden `users/` directory. The backend and the
> Storefront template get the marketplace features that such a catalog
> needs: search facets, a department menu, a rating histogram, review
> filters and related products.

---

## 1. Overview

Before this work, Shop generation made a SandboxShop from one input, the
Shop Manual. An LLM invented the whole catalog (a few dozen products), the
Personas and their orders, and the Reviews were random and not linked to
the Personas. This gave four problems:

1. The catalog was small and not realistic. An agent could not learn or
   show search, facet and comparison skills on it.
2. The team could not use the public datasets that it knows. Each dataset
   has its own format, and ShopGym had no standard format for a catalog,
   a user profile or user behavior.
3. A Persona had no profile and no real history, so a personal Task
   ("buy what this user bought next") could not have one true answer.
4. No path existed to build a realistic marketplace shop.

This spec describes the shipped design:

- the Source bundle contract in `@shop-gym/core`: the layout, the schemas
  and the two validation levels (§5.1, §5.2);
- `shopgym bundle`: the AR23 Adapter, user-first sampling at one Cutoff,
  the complete step with its Provenance marks, the images step, and
  publish (§5.3 to §5.7);
- `shopgym gen --bundle`: the mapping of a complete bundle to a
  SandboxShop (§5.8);
- the marketplace features of the backend and the Storefront template
  (§5.9);
- the Site state graph in the SandboxShop and the `site_graph` Verifier
  (§5.10);
- brands, licenses and hidden data (§5.11, ADR 0018).

The field-level rules are in the package READMEs:
[`packages/core/README.md`](../../../packages/core/README.md),
[`packages/shop-arena/README.md`](../../../packages/shop-arena/README.md)
(the Bundle and Gen sections),
[`packages/shop_backend/README.md`](../../../packages/shop_backend/README.md)
and
[`packages/shop-arena/templates/storefront/README.md`](../../../packages/shop-arena/templates/storefront/README.md).
The first shop made with this work is the Video_Games POC shop (§8.2).

The design was drafted on 2026-11-03 and reviewed with the page
`packages/reports/pages/2026-11-03-source-bundles-review.html`. Where the
code differs from that draft, this spec describes the code, and §8.3
lists each difference.

---

## 2. Terminology

- **Source bundle** - one directory with `bundle.json`, a catalog of
  products with variants, their reviews, and the User events and User
  profiles of the Modeled users, in one format for every source dataset.
  A **raw** bundle has only the source facts. A **complete** bundle also
  has every field that Shop generation needs.
- **Adapter** - the code that reads one source dataset and writes a raw
  Source bundle. It maps fields and marks the values that it infers.
- **Modeled user** - a source user that sampling picks, with enough User
  events before the Cutoff and at least one purchase after it. Only
  Modeled users get User events, User profiles and Personas.
- **User event** - one dated action of one Modeled user, such as a
  `review` or a `purchase`, from a closed list of event types.
- **User profile** - what a Modeled user is like as of the Cutoff:
  demographics, preferences, habits and a narrative. It has no account
  fields.
- **Cutoff** - the one time of a bundle that splits history (before it)
  from hidden Task targets (at it or later).
- **Task target** - a purchase of a Modeled user at the Cutoff or later,
  which a personal Task can ask an agent to reach.
- **Clock offset** - the whole number of days that Shop generation adds
  to every bundle time, so that the Cutoff falls on the Episode clock
  start (2026-01-01, ADR 0009).
- **Complete step** - the step of `shopgym bundle` that turns a raw bundle
  into a complete one and marks each filled field.
- **Provenance** - the mark that tells where a field comes from:
  `source`, `inferred`, `synthetic` or `rewritten`. A field with no mark
  comes from the source.
- **Department** - a top-level node of the category paths of a catalog.
- **Facet** - one way to narrow a product list, with a count for each
  value: category, Brand, price and rating.
- **Rating histogram** - the count of the Reviews of one product at each
  star rating.
- **Related products** - the products that a product page shows under
  "You may also like".

`GLOSSARY.md` defines the same terms.

---

## 3. Current Status

On 2026-11-12, the code does all of §5. In short:

- `@shop-gym/core` has the bundle zod schemas, the closed `EVENT_TYPES`
  list, the page type list that it shares with the Site state graph, a
  JSONL reader, and `validateBundle(dir, 'raw' | 'complete')`.
- `@shop-gym/shop-arena` has `buildBundle` (`src/bundle/`): the AR23
  Adapter, sampling, the complete step, the images step and publish, on
  the core pipeline runner. `shopgym bundle` wraps it.
- `generateShop` takes `bundleDir`, and `shopgym gen --bundle` wraps it.
  `data_synth` maps the bundle to `data/` and `users/`, and publish
  records the bundle in `shop.json`.
- The Backend template has the marketplace Dataset fields, product
  filters and facets on search and collections, the rating histogram, the
  review filters, and related products first in
  `productRecommendations`. The Storefront template has the "Filters"
  panel, the histogram, the review filters and "You may also like".
- Shop generation copies a single manual's `site_graph.json` into the
  shop, the build planner reads it, and the `site_graph` Verifier walks
  it.
- The first shop, the Video_Games POC shop, was built and hosted on
  2026-11-12 (§8.2).

The only adapter is AR23, and one bundle reads one dataset category.

---

## 4. Desired Status

The design plans these parts, and the code does not do them yet:

1. **Every shop goes through a bundle.** A shop with no catalog input
   would use an empty bundle, and the complete step would synthesize the
   catalog from the Shop Manual (the LLM catalog synthesis of today, all
   marked `synthetic`). `shopgym bundle` would take `--manual <dir>` for
   that case, and `shopgym gen` without `--bundle` would make an empty
   bundle on the fly. Today a shop without `--bundle` (and without
   `--data`) is synthesized from the manual as before. The user put this
   path after the POC (2026-11-12).
2. **Rewrite step.** An optional bundle-to-bundle step that changes only
   identifying text and images: titles, descriptions, bullets, brand
   names (to the fake-brand allowlist), attributes that name a brand,
   review text, reviewer names and images. It keeps every id, price,
   category, attribute value, rating and User event, and marks each
   changed field `rewritten`. The `rewritten` mark is in the schema, but
   no step writes it. The user put this step after the POC (2026-11-12).
3. **Personal Tasks.** A user-first Generation method in Task generation
   reads `users/`, writes an intent from a User profile and a Task target
   that does not name the product, computes an Acceptable set by code
   (the products that meet every constraint that the intent states), and
   keeps the Task only when that set has 5 or fewer products and holds the
   target. Grading is a `state_check` on the new order, with a new match
   mode for "any one of these products". Reorder and order-history Tasks
   use the Persona's orders. This waits for Task generation, which is on
   hold.
4. **Graph weights and expected flows.** Shop generation would add
   transition weights to the Site state graph from User events that have
   a page type, and Task generation would read the graph as a list of
   expected flows for its BFS report. AR23 has no page types, so its
   events give no weights.
5. **More sources.** Adapters for WebShop, H&M, MerRec, KuaiSearch and
   OPeRA, public profile datasets, and the fill cases that AR23 does not
   need: a bundle with profiles and no events (sample events from the
   catalog), and a bundle with neither (an LLM writes the profiles, then
   events are sampled).
6. **Several categories in one bundle.** The design names three AR23
   categories for the first marketplace shop. Today `--category` takes
   one, and the POC used Video_Games only.
7. **`gen --data` as an adapter.** `--data` stays a separate path that
   copies the catalog of an existing SandboxShop. Folding it into a
   `sandbox_dataset` Adapter that keeps every id and handle is later work.

---

## 5. Proposal

This section describes the shipped design.

### 5.1 Pipeline and module placement

```text
AR23 category files                         Shop Manual
        |                                        |
  shopgym bundle (buildBundle)                   |
    sample    -> .bundle/raw       (raw bundle)  |
    complete  -> .bundle/complete  (rules + LLM) |
    images    -> catalog/images/   (download)    |
    publish   -> <bundle>/         (validate)    |
        |                                        |
  Source bundle (complete) ------> shopgym gen --bundle (generateShop)
                                     data_synth: map to data/ + users/
                                     build, final_eval, publish
                                         |
                                   SandboxShop (shop.json: sourceBundle)
```

| Part | Package and path |
| --- | --- |
| Bundle schemas, `EVENT_TYPES`, `PAGE_TYPES`, `validateBundle` | `@shop-gym/core`, `src/bundle/`, `src/schema/site-graph.ts` |
| `buildBundle`, the AR23 Adapter, sampling, complete, images | `@shop-gym/shop-arena`, `src/bundle/` |
| The mapping to a SandboxShop | `@shop-gym/shop-arena`, `src/gen/data_synth/source_bundle/` |
| Marketplace read paths | `@shop-gym/shop-backend`, `src/resolvers/{facets,review,search}.ts` |
| Marketplace pages | `packages/shop-arena/templates/storefront` |
| `shopgym bundle`, `shopgym gen --bundle` | `@shop-gym/cli`, `src/commands/{bundle,gen}.ts` |

The schemas are in core because ShopArena reads them now and Task
generation will read `users/` later. The bundle steps run on the core
pipeline runner, so a rerun skips the complete steps, a changed input
runs its step again, and `--from <step>` forces a step and every step
after it. The work files are under `<bundle>/.bundle/`.

### 5.2 Bundle layout and validation levels

```text
<bundle>/
  bundle.json            version, name, sources[] (dataset, license, url,
                         subsets), locale, currency, cutoff, sample options
  catalog/products.jsonl one product with its variants per line
  catalog/reviews.jsonl  one review per line
  catalog/images/        the downloaded images
  users/profiles.jsonl   one User profile per Modeled user
  events/events.jsonl    one User event per line
  report.json            what each step read, dropped, filled and downloaded
```

Rules for every record:

- Records are snake_case JSON. An optional field is absent, never `null`.
- Ids are the source's own strings, unique in the bundle. Variant ids are
  unique in the whole bundle.
- One locale and one currency per bundle (AR23: `en-US`, `USD`). Every
  price is in the bundle currency.
- A product holds its variants. Optional fields: `description`, `bullets`,
  `brand`, `seller`, `category_path` (the Department first), `attributes`,
  `options`, `images` (`source_url`, `path` under `catalog/`, `alt`),
  `rating` (a source rating; never used by the shop), `related`
  (`bought_together`, `also_bought`), `source` and `provenance`.
- A review has a rating from 1 to 5, a title, a body, a time, a
  `verified_purchase` flag and `helpful_votes`. It has a `user_id` only
  when the reviewer is a Modeled user.
- A User event has a type from `EVENT_TYPES` (`page_view`,
  `product_view`, `search`, `search_result_click`, `add_to_cart`,
  `remove_from_cart`, `wishlist_add`, `checkout_start`, `purchase`,
  `review`, `return`), a `timestamp_precision` (`ms`, `second`, `day` or
  `order`), the source's `raw_type`, and optional product, variant,
  order, session, price, query and page type fields. The page types are
  the one list of the Site state graph.
- A User profile has optional demographics, preferences (price
  sensitivity `budget`, `mid` or `premium`, category interests as category
  paths, brands, focus aspects), sizes, habits and a narrative. It has no
  account fields.

`validateBundle(dir, level)` streams every file, checks each record
against the schema of the level, and checks the joins:

```text
reviews.product_id, events.product_id -> products.product_id
reviews.variant_id, events.variant_id -> a variant of that product
products.related.*                    -> products.product_id
reviews.user_id, events.user_id       -> profiles.user_id (when there are profiles)
products.images[].path                -> a file under catalog/
```

It also checks that ids are unique (variant ids in the whole bundle) and
that every price is in the bundle currency.

- `raw`: only `bundle.json` is required. Each record has its core fields
  (for a product: `product_id`, `title` and at least one variant with a
  `variant_id`), and the joins are valid. This is what an Adapter writes.
- `complete`: also at least one product; a description, a brand and a
  category path on every product; a price and an inventory on every
  variant; named options and a value for each option when a product has
  more than one variant; a variant on every review; a profile for every
  user with User events; and preferences and a narrative on every profile.
  Shop generation accepts only this level.

A failed validation throws `BundleValidationError`. Each problem names the
file, the line, the record id and the field, for example
`catalog/products.jsonl:3 (product_id "P1"): title: required`. The error
lists at most 50 problems and gives the total.

### 5.3 The AR23 Adapter

The Adapter reads one category of Amazon Reviews 2023:
`review_categories/<name>.jsonl` and `meta_categories/meta_<name>.jsonl`.

| AR23 | Bundle |
| --- | --- |
| `parent_asin` | `product_id` |
| each reviewed `asin` | one variant |
| `features` | `bullets` |
| `details.Brand` | `brand` |
| `store` | `seller` |
| `categories` | `category_path` |
| the other text `details` | `attributes` |
| the large images | `images[].source_url` |
| `price` (a number, or text such as `from 29.99`) | the price of every variant, marked `inferred` |
| `bought_together` (when not null) | `related.bought_together` |

- Reviews are catalog content. Each review of a Modeled user is also a
  `review` User event. A verified review is also an inferred `purchase`
  event at the review time, with the precision `order`. An unverified
  review gives only the `review` event. Other reviewers have no events
  and no `user_id`.
- `related.also_bought` comes from co-purchases, marked `inferred`: the
  products that at least two users bought with this one, the most shared
  buyers first, at most ten. It counts the verified reviews before the
  Cutoff by every reviewer in the source, before the per-product review
  cap. Video_Games has no `bought_together` lists, so this is its only
  related-product signal.
- Exact duplicate reviews (same user, asin, time, rating, title and text)
  are dropped.
- The Adapter reads each source file twice and keeps only small per-row
  numbers in memory between the passes, so the source files can be far
  larger than memory.
- `bundle.json` records the source as `amazon_reviews_2023` with the
  license "No license; the authors share the data primarily for research
  purposes. Research use only." and the category in `subsets`.

### 5.4 Sampling and the Cutoff

The bundle has one global Cutoff (`--cutoff`, a date at midnight UTC or a
UTC time). Sampling starts from the users and is seeded (`--seed`):

1. Pick `--users` Modeled users at random among the users with at least
   `--min-events-before` (default 5) User events before the Cutoff and at
   least one purchase after it.
2. Keep every product in their histories, before and after the Cutoff.
3. Fill up to `--products` with other products of the same category
   paths, the most reviewed before the Cutoff first.
4. Keep the reviews of the kept products. `--reviews-per-product` keeps a
   seeded choice of at most that many reviews of each product, and always
   keeps the reviews of Modeled users.
5. Drop the products first seen after the Cutoff, unless a Modeled user
   buys them after the Cutoff (they are Task targets).

The seeded choice does not depend on the order of the source. Products
are sorted by id, reviews keep the source order, and events are sorted
by user and time, so the same options and source give the same bytes.
The bundle keeps the source times; only a shop shifts them (§5.8).

### 5.5 The complete step and Provenance marks

The complete step reads the raw bundle and writes a complete bundle in
the same layout. It fills by rules first, and by an LLM only where no rule
can. Each filled field gets a Provenance mark in the record's
`provenance`, for example `{"variants[].price": "inferred"}`:

| Field | Fill | Mark |
| --- | --- | --- |
| `category_path` | the most common top category of the catalog | `inferred` |
| `brand` | the seller, else `Generic` | `inferred`, else `synthetic` |
| `description` | the bullets, one per line, else the title | `inferred` |
| `variants[].price` | the price of another variant, else the median price of the longest category path prefix with prices, else of the catalog | `inferred` |
| `variants[].inventory` | a seeded whole number from 1 to 50 | `synthetic` |
| `options`, `variants[].option_values` | for a product with more than one variant, an LLM infers one option and a value per variant from the title, description, bullets and attributes | `synthetic` |
| `users/profiles.jsonl` | an LLM writes one User profile per Modeled user from the products that the user bought and reviewed before the Cutoff, with the catalog's top categories and price range; each category interest must be a category path of the catalog | `{"*": "synthetic"}` |

- `inferred` means that a rule derived the value from other source
  values. `synthetic` means that a model wrote it or a seeded rule made it
  up.
- Each LLM reply is checked with its zod schema and the rules above. A bad
  reply gets one repair call with the error, and a second bad reply fails
  the step.
- The checked replies are cached in `.bundle/llm_cache/`, one file per
  reply, named by the hash of the model, the prompt and the reply schema.
  No step owns the cache, so `--from` and a changed option keep it. A
  rerun with the same input makes no LLM call and writes the same bytes.
- `--model` (default `openai/gpt-5.5`) and `--concurrency` set the model
  and the parallel calls. The prompts are plain Markdown files in
  `src/bundle/complete/prompts/`.
- Reviews and User events are copied without change.

### 5.6 The images step

The images step looks at the first `--images-per-product` (default 1; 0
turns it off) images of each product, and downloads each one that has a
`source_url` and no `path`. Each distinct URL is saved once to
`catalog/images/<16 hex digits of the URL hash>.<extension>`, and its
`path` goes next to its `source_url`.

- It requests only the image URLs of the dataset: four at a time, a 30 s
  time limit, and no redirects followed.
- A network error, a time-out, a 408 or a 5xx is retried three times,
  after 1 s, 2 s and 4 s.
- It never tries to get past a block. A refusal (a 3xx, 401, 403 or 429,
  or an answer that is not `image/*`) is not retried, and 10 refusals in a
  row stop the download.
- A failed image keeps only its `source_url`, is listed in `report.json`,
  and does not fail the bundle.
- No step owns the image files, so the pipeline never deletes them. A
  file is written under a temporary name and then renamed. A rerun
  (`--from images`, or a larger `--images-per-product`) requests only the
  images that are not on disk.

### 5.7 Publish and validation

Publish copies `bundle.json`, the reviews, `users/` and `events/` from the
complete bundle, and the products with their local image paths from the
images step. Then it validates the bundle in place at the `complete`
level, so each image `path` must name a file on disk. It writes
`report.json`: what the Adapter read, dropped and kept, what the complete
step filled, the image download, and the validation counts.

`bundle.json` has no creation time, so the same options and source give
the same bytes in every file of the bundle except `report.json`, whose
image counters describe the last run of the images step (§8.4).

### 5.8 Mapping to a SandboxShop

`shopgym gen <manual dir> --name <name> --bundle <bundle dir>` (config
`bundleDir`) makes the Dataset from the bundle. It cannot be used with
`--data`, and the catalog and image options do not apply.
`data_synth` first runs `validateBundle(dir, 'complete')`. It does not
run the catalog, navigation, customer and review sub-steps. `identity`
(with the bundle currency and the country of the bundle locale), `store`,
`pages`, `policies` and `commerce` run on the Shop Manual as usual. All of
the mapping is code from a fixed seed, so the same bundle and the same LLM
replies give the same bytes.

- **Clock.** The Clock offset is the whole days from the Cutoff to the
  Episode clock start (2026-01-01), rounded down. Every bundle time moves
  by it. A product or a customer is created when it first shows in the
  shop history, else at the shifted Cutoff.
- **Catalog.** Products are sorted by bundle id and numbered from 1, and
  so are their variants and images. The handle is the slug of the title
  (at most 60 characters), with `-2`, `-3` for repeats. `vendor` is the
  seller, else the brand. `product_type` is the leaf of `category_path`,
  `tags` is the whole path, and `sku` is the bundle variant id. `brand`,
  `category_path`, `attributes`, `source` and `provenance` are copied, and
  `related` names product handles. A product with no options gets
  `Title` / `Default Title`; more than three options fail the step.
- **Images.** Each local PNG or JPEG is copied to
  `data/images/<handle>-<n>.<ext>` with its pixel size. Other formats are
  left out and logged. A `source_url` with no local copy is not used, so
  the shop needs no network. A product with no image gets one 800x800
  placeholder.
- **Collections and menus.** Each node of a category path is one
  collection that lists every product under it. The main menu links each
  Department and the nodes one level below it. The footer links every
  page and policy.
- **Reviews.** Only the Reviews before the Cutoff go into `reviews.json`.
  `verified_buyer` comes from `verified_purchase` and `helpful_count` from
  `helpful_votes`. A review by a Modeled user names that Persona (first
  name and last initial) and sets `customer_id`. Every other reviewer gets
  a seeded first name and last initial. The backend computes the product
  ratings from these Reviews, so a source rating and a future review never
  show in the shop.
- **Personas and orders.** Each Modeled user is one Persona, with a seeded
  name pair that no other Persona has (at most 1,200 users), one or two
  saved addresses, and an email and a password that code makes.
  The purchase events before the Cutoff become paid and fulfilled orders,
  one for each user and `order_id` (else `session_id`, else time), at the
  event price or the variant price.
- **Hidden `users/`.** Next to `data/`, so the backend never loads it:
  `profiles.jsonl` (the bundle profiles as they are), `persona_map.json`
  (bundle user id to customer id) and `future_events.jsonl` (the User
  events at the Cutoff or later, each with a `shop` block of the shifted
  time, the customer id, and the product id, handle and variant id).
- **Shop manifest.** Publish writes `sourceBundle` into `shop.json`: the
  bundle directory, its name and Cutoff, `clockOffsetDays` and the sources
  with their licenses.

`data_validation` also checks that each `related` handle names a product
and that each Review `customer_id` names a customer. A change to
`bundle.json`, `catalog/`, `users/` or `events/` runs `data_synth` again;
the `.bundle/` work files and `report.json` do not.

### 5.9 Marketplace storefront features

All Dataset additions are optional, so a Dataset without them loads as
before. `products.json` may have `brand`, `category_path`, `attributes`,
`related` (`bought_together` and `also_bought` handles), `source` and
`provenance`, and `reviews.json` may have `customer_id`.

| Feature | Backend | Storefront template |
| --- | --- | --- |
| Search facets | `ProductFilter` takes `brand`, `categoryPath` and `rating` (`@sandbox`) next to the Storefront filters; `search` returns `productFilters` and `Collection.products` returns `filters` | The "Filters" panel on search and collection pages: "Category", "Brand" and "Rating" links with counts, and a "Price" form; the URL holds `filter.<key>=<JSON>` |
| Department menu | collections from category paths (§5.8) | the main menu |
| Rating histogram | `Product.ratingHistogram` (`@sandbox`) | bars near the product title; each bar with Reviews links to the Reviews of that rating |
| Review filters | `Product.reviews(rating, verifiedBuyer)` (`@sandbox`) | "Rating" and "Verified Buyers only" controls next to "Sort by" |
| Related products | `productRecommendations` puts `related` first | "You may also like", up to four product cards |

Rules:

- **Facets.** Filters with the same key match when any of them matches,
  and different keys must all match. `categoryPath` matches the products
  in that category or below it. `rating` matches the mean Review rating,
  rounded to one decimal, and a product with no Reviews never matches.
  The facets are category, brand, price and rating, in that order. A
  value counts the products that pass every filter except the filters of
  its own facet, so it tells what choosing that value would give. A facet
  lists only values with products, plus the chosen values. The facets are
  empty when no product of the Dataset has a brand or a category path,
  and then the storefront shows no panel. A brand link adds or removes
  its brand; a category or rating link replaces the current one.
- **Rating histogram.** Five `{ rating, count }` entries, from 5 stars
  down to 1 star, from the same Reviews as the rating metafields. A
  rating with no Reviews has the count 0 and no link.
- **Review filters.** `rating` (1 to 5) and `verifiedBuyer` keep only the
  matching Reviews, before the sort and the paging. The storefront keeps
  them in `?reviews_rating=<n>` and `?reviews_verified=true`, keeps the
  sort and the filters across pages, and shows "No reviews match these
  filters." when no Review matches.
- **Related products.** `productRecommendations(productId)` returns up to
  four other products: the bought-together ones, then the also-bought
  ones, then a ranking (the same `productType`, then more shared tags,
  then Dataset order). A product with no `related` list gets the ranking
  only. With no recommendations the page shows no block.

`docs/specs/shop_backend/account_discount_reviews.md` §5.5 has the
Review rules in full.

### 5.10 Site state graph in the shop

The Site state graph comes from the Shop Manual, not from the bundle.
When a single manual has `site_graph.json`, `manual_merge` checks it with
`parseSiteGraph` and copies it into the shop's `manual/`. The build
planner reads it as a list of flows to make. The `site_graph` Verifier
walks each `navigate` transition between two routed pages on the built
shop, as a guest. It maps each page type onto a built route
(`PAGE_TYPE_RULES`), never onto the source URL patterns, and fails, naming
the transition, when the `from` page does not load, no link or form leads
to the route of `to`, or that target does not load. A transition is
advisory, and does not fail the Verifier, when an end is an overlay, its
effect is not `navigate`, its trigger is `load`, an end is a member,
checkout or `other` page, or it starts on a cart or `page` page. Each
checked transition belongs to the build task of its `from` page, and
`visual_fix` walks them all. See `shop_gen.md` §3.3.

### 5.11 Brands, licenses and hidden data

ADR 0018 records the decision:

- Shop generation reads the anonymized Shop Manual and, with `--bundle`,
  a complete Source bundle. The bundle is data that the team gave on
  purpose, never the raw evidence of a Live storefront.
- A bundle product keeps its real brand and seller. The store name still
  comes from the fake-brand allowlist (ADR 0013), and the brand scan at
  assembly only logs.
- `bundle.json` and `shop.json` record each source and its license. AR23
  has no license and is for research only, so its bundles and shops stay
  inside the team.
- The User profiles and the Task targets stay in `users/`, which the
  backend never loads.

### 5.12 Tests

Tests check behavior at the seams, with scripted LLM fakes and tiny
hand-written fixtures in the AR23 format, with fake brand names:

- `packages/core/src/bundle/validate.test.ts`: both levels, the joins,
  the image paths and the error text.
- `packages/shop-arena/src/bundle/pipeline.test.ts` (`buildBundle`):
  user-first sampling, the field map, events only for Modeled users,
  inferred purchases, the review cap, the same bytes for the same options
  and seed, the pipeline runner, the complete rules and marks,
  co-purchases, the LLM options and profiles, repair, the LLM cache, and
  the image download rules.
- `packages/shop-arena/src/gen/data_synth/source_bundle/source_bundle.test.ts`
  (`generateShop` with a bundle): every step, the catalog numbering, the
  images, the collections and department menu, ratings from the Reviews
  before the Cutoff, Personas with orders, `users/`, nothing served from
  `users/`, `shop.json`, an incomplete bundle, `--data` with `--bundle`,
  and the same bytes on a rerun.
- `packages/shop_backend/src/resolvers/facets.test.ts`, `search.test.ts`
  and `tests/contract/reviews.test.ts`: facets, related products, review
  filters and the histogram.
- `packages/shop-arena/src/templates.browser.test.ts`: the "Filters"
  panel, the histogram links, the review filters and "You may also like"
  in Chromium.
- `packages/shop-arena/src/gen/build/verifiers/site_graph.test.ts`: the
  graph walk.
- `packages/cli/src/commands/bundle.test.ts` and `gen.test.ts`: the
  options.

---

## 6. Alternatives

- **An LLM writes a large catalog.** Rejected: about ten thousand
  products cost much time and money, and the result has no real reviews,
  ratings or shopper histories.
- **One record per variant (flat rows).** Rejected: AR23 and WebShop
  have one record per parent product, so a nested product maps almost one
  to one. An Adapter for flat rows (H&M) groups them into products.
- **Copy the source rating.** Rejected: it counts reviews after the
  Cutoff. The backend computes the rating from the Reviews in the shop.
- **Use the source times as the Episode clock.** Rejected: ADR 0009
  fixes the clock start. One whole-day Clock offset keeps the order and
  the weekdays of the history, and the bundle keeps the source times.
- **LLM shoppers browse a hosted shop to make history.** Rejected: slow,
  costly and not repeatable. Missing data is filled offline, from a seed.
- **Serve `users/` behind a flag.** Rejected: an agent could then read a
  Task target through the shop.
- **Download every image.** Not chosen for now: about 50,000 images and a
  few GB per shop. `--images-per-product` defaults to 1.

---

## 7. Execution Table

The POC tickets, each with one pull request to `v2-main`. On 2026-11-12
all of them were open and waiting for review.

| # | Item | PR | Status |
| --- | --- | --- | --- |
| K1 | Source bundle schemas and validator in core; AR23 Adapter, sampling and `buildBundle`; `shopgym bundle` | #79 | done |
| K2 | Complete step: rule fills, LLM variant options and User profiles, Provenance marks, LLM cache | #83 | done |
| K3 | Images step: download the large images of kept products; image paths in validation | #81 | done |
| K4 | Marketplace Dataset fields; product filters and facets in the backend; the "Filters" panel | #78 | done |
| K5 | Rating histogram and review filters, backend and product page | #75 | done |
| K6 | Related products: `productRecommendations` puts `related` first; "You may also like" | #80 | done |
| K7 | `shopgym gen --bundle`: catalog, Personas with orders, Reviews, Clock offset, `users/`, `sourceBundle` | #84 | done |
| K8 | Site state graph in the SandboxShop, the build planner, and the `site_graph` Verifier | #76 | done |
| K9 | The POC run (§8.2), and its fix: the build `visual_judge` also judges the order page of the first seeded order of the Persona that it logs in with | #85 | done |
| K10 | Lasting docs: this spec, ADR 0018, `GLOSSARY.md` terms, README | #86 | done |
| K11 | Storefront exploration run 2 findings: unknown stats, Run notes, the Read budget, currency | #82 | done |
| - | Empty-bundle path, rewrite step, personal Tasks, graph weights, more adapters (§4) | - | planned |

---

## 8. Appendix

### 8.1 File map

```
packages/core/src/bundle/
  schema.ts                 bundle schemas, EVENT_TYPES, COMPLETE_SCHEMAS
  validate.ts               validateBundle, BundleValidationError
  jsonl.ts                  JSONL line reader
packages/core/src/schema/site-graph.ts   PAGE_TYPES and the Site state graph
packages/shop-arena/src/bundle/
  pipeline.ts               buildBundle and the four steps
  options.ts                BUNDLE_ADAPTERS, BUNDLE_STEPS, the options
  ar23/                     the AR23 Adapter and its row schemas
  sample.ts                 user-first sampling
  co_purchase.ts            related.also_bought
  complete/                 rules, variant options, profiles, LLM cache, prompts
  images.ts                 the image download
packages/shop-arena/src/gen/data_synth/source_bundle/
  read.ts, clock.ts         bundle input and the Clock offset
  catalog.ts                products, images, collections, department menu
  history.ts                Personas, orders, Reviews, future events
packages/shop-arena/src/gen/pipeline.ts          publish step: sourceBundle from bundle.json
packages/shop-arena/src/gen/publish/publish.ts   the sourceBundle schema of shop.json
packages/shop-arena/src/gen/build/verifiers/site_graph.ts
packages/shop_backend/src/resolvers/
  facets.ts                 product filters and facets
  review.ts                 review filters, rating histogram, rating metafields
  search.ts                 search facets, productRecommendations
packages/shop-arena/templates/storefront/app/
  components/facets.tsx, lib/facets.ts      the "Filters" panel
  components/reviews.tsx, lib/reviews.ts    histogram and review filters
  routes/product.tsx                        "You may also like"
packages/cli/src/commands/bundle.ts, gen.ts
```

### 8.2 The Video_Games POC shop

The first marketplace shop is the Video_Games POC shop. It was built on
2026-11-12 from the Video Games Shop Manual (`shop_explore.md` §8.4) and
this bundle. Its outputs and the run report are in the gitignored
`outputs/`.

```bash
shopgym bundle amazon_reviews_2023 outputs/sources/amazon_reviews_2023/raw \
  --category Video_Games --out outputs/bundles/<bundle> --cutoff 2022-07-16 \
  --products 10000 --users 200 --seed 7 --reviews-per-product 50
shopgym gen <Video Games Shop Manual dir> --name <shop> --bundle outputs/bundles/<bundle>
shopgym host start <shop> <port>
```

Bundle:

- 10,000 products, 24,165 variants, 488,390 reviews, 200 User profiles
  and 3,106 User events, from the Video_Games category. Cutoff
  2022-07-16, seed 7, at most 50 reviews per product.
- Step times: sample 24 s, complete 547 s (3,825 LLM calls, USD 13.46),
  images 437 s (9,894 of 9,896 images downloaded), publish 2 s.
- A rerun with the same options gave the same bytes in all 9,900 files
  and made no LLM call. A new build from the same LLM cache also made no
  LLM call, and only the run counters in `report.json` changed.

Shop:

- The Clock offset is 1,265 days.
- The Build loop completed in 13 Iterations, and all 11 Verifiers passed
  on the last one. Final eval: 24 passed, 0 failed, 1 skipped
  (`requestReturn`, which the backend does not support).
- One `gen` run used about USD 3 to 4 of LLM calls. The POC used USD 20.48
  of LLM calls in all.
- `gen` on 10,000 products needs a larger Node heap
  (`node --max-old-space-size=16384`).
- The hosted shop served search facets, the rating histogram, review
  filters and related products. A Persona logged in and saw its orders
  from before the Cutoff on shifted dates. The backend served nothing
  from `users/`, and `shop.json` recorded the bundle, the Cutoff, the
  Clock offset and the research-only license.

### 8.3 Differences from the design draft

| Design draft (2026-11-03) | Code (2026-11-12) |
| --- | --- |
| `shopgym bundle <adapter> <src> --out --cutoff --products --users --seed [--manual <dir>]` | Adds `--category` (one dataset category), `--min-events-before`, `--reviews-per-product`, `--images-per-product`, `--model`, `--concurrency` and `--from`; no `--manual` (§4 item 1) |
| `shopgym gen --manual <dir> --bundle <dir>` | The manual is a positional argument: `shopgym gen <manual dir> --name <name> --bundle <dir>` |
| Every shop goes through a bundle; no catalog input gives an empty bundle | Only `--bundle` shops use a bundle (§4 item 1) |
| Optional rewrite step | Not built (§4 item 2) |
| `bundle.json` has `created_at` | No creation time, so a rerun gives the same bytes |
| `related` comes from co-purchases in the User events, plus `bought_together` | Co-purchases count the verified reviews before the Cutoff of every reviewer in the source, before the review cap, not only the events of Modeled users |
| Profiles inferred from history are marked `inferred` | They are marked `{"*": "synthetic"}`, because an LLM writes them |
| Download the large images of kept products | Only the first `--images-per-product` (default 1) images of each product |
| Sampling keeps all reviews of kept products | `--reviews-per-product` caps them (50 in the POC), and always keeps the reviews of Modeled users; exact duplicate reviews are dropped |
| Shop generation adds Site state graph weights from User events | Not built (§4 item 4) |
| First marketplace shop on three AR23 categories | One category, Video_Games (§4 item 6) |
| Page types with spaces (`order detail`) | snake_case (`order_detail`), shared with the Site state graph |

### 8.4 Open decisions

The POC run left these questions for the user to decide:

- **Invented variant values.** AR23 has no variant attributes, so for a
  product with many variants the LLM invents the option values. Whether
  to keep them, cap them, or use another rule is open.
- **Image counters in `report.json`.** The counters describe the last run
  of the images step, not the bundle as a whole, so a rerun changes them.
- **Dropped images in `gen --bundle`.** The POC shop left out 7 images
  that are not PNG or JPEG (WebP files with a `.jpg` name, and GIF files).
- **Build and Final eval pages.** The build `visual_judge` does not judge
  every page that the Final eval judges.
- **LLM cost.** `shopgym bundle` and `shopgym gen` do not record the cost
  of their LLM calls.
- **Brand scan.** On a marketplace catalog, the brand scan at assembly
  logs many real brand tokens, so its log is noise.
- **SKUs.** A product SKU is the raw dataset id of the variant.
- **Histogram and the Capability.** The product page always shows the
  rating histogram when a product has Reviews. Whether it must follow the
  `has_rating_histogram` Capability of the Shop Manual is open.
