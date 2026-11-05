# ShopArena Standard Account and Checkout, and `gen --data` (`packages/shop-arena`)

Status: **Implemented** · Version: **0.1**
Owners: ShopArena

> Every SandboxShop gets account, checkout and order confirmation pages, an
> announcement bar with its Discount codes, and product Reviews. They follow
> one checked-in Standard sub-manual, which manual merge fits to the shop's
> observed notes. Shop generation can also start from the catalog of an
> existing SandboxShop with `shopgym gen --data`.

---

## 1. Overview

Storefront exploration sees a Live storefront only as a logged-out buyer. A
Shop Manual therefore never describes the account pages, a completed
checkout or the order confirmation. Before this work, no Sub-manual and no
build task owned these pages, so their labels and flows depended only on the
build agent, with no manual text to follow. Account, order and checkout
Tasks need these pages to be the same in every shop, and the browser steps
of the Verifiers and the Final eval need fixed selectors and messages.

Shop generation also always made a new catalog. An old shop on the removed
Hydrogen layout, such as `mock_clothing`, could not move onto the current
templates with its catalog, so Tasks written against that catalog could not
be reused.

This spec covers the ShopArena side of the work:

- the Standard sub-manual and Fusion, in manual merge (§5.1, §5.2);
- the prebuilt pages in the Storefront template and its browser suite (§5.3);
- the build tasks `gen_account` and `gen_checkout`, the Standard sub-manual
  sections that `gen_navigation` and `gen_product` read, and the
  `account_flow` and `discount_flow` Verifiers (§5.4);
- the new Final eval steps (§5.5);
- data synthesis of Discount codes, Personas, seeded orders and Reviews (§5.6);
- `shopgym gen --data` and the source manuals in the Shop manifest (§5.7).

The backend side (address book, password recovery mock, Discount codes,
Reviews and the StateSnapshot fields) is in
[`../shop_backend/account_discount_reviews.md`](../shop_backend/account_discount_reviews.md).
The decisions are
[ADR 0016](../../adr/0016-standard-sub-manual-for-account-and-checkout.md)
and [ADR 0017](../../adr/0017-gen-may-copy-a-sandboxshop-catalog.md).

---

## 2. Terminology

- **Standard sub-manual** - the one checked-in Sub-manual that every
  SandboxShop gets as `manual/parts/standard.md`. It describes, by the
  Shopify standard, the account, checkout and order confirmation pages, the
  announcement bar and Reviews rules, and the behavior that the backend
  supports.
- **Fusion** - the manual merge step that writes the Merged manual's
  observed Account and Checkout sections into the same sections of the
  shop's copy of the Standard sub-manual.
- **Checked label** - a label or message that a browser step looks up on
  the storefront, such as "Forgot your password?" or "Enter a valid
  discount code". Fusion and the build tasks must keep each one word for
  word.
- **Prebuilt page** - a page that the Storefront template already builds
  from the Standard sub-manual (account, checkout, thank-you). A build task
  restyles it and does not build it again.
- **Source Dataset** - the Dataset directory given to `shopgym gen --data`.
  Its products, collections and images become the new shop's catalog.
- **Source manuals** - the Shop Manual directories given to `shopgym gen`,
  recorded in the Shop manifest as `sourceManuals`.
- **Discount code**, **Review**, **Persona**, **Address book** and
  **Password reset request** are defined in `GLOSSARY.md`.

---

## 3. Current Status

Before this work:

- Manual merge cut the Merged manual into six Sub-manuals. A Shop Manual
  had no Account or Checkout section in practice, and the split had no area
  for one.
- The Storefront template had account routes and a checkout, but with no
  address edits, no password recovery, no Discount code that changed the
  price, no announcement bar with the codes and no Reviews. The old
  Hydrogen shops hard-coded their Reviews.
- The planner had no build task for account or checkout pages, and no
  Verifier drove the account or discount forms.
- Data synthesis made three Personas with one address each and seeded
  orders of one kind (paid, shipped, one address, one method, no discount).
- Shop generation always synthesized the catalog.

After this work, everything in §5 is in `packages/shop-arena` and
`packages/shop_backend`, with unit tests, the gen pipeline tests on the
scripted `LlmClient`, and the Storefront template browser suite in every
`pnpm test` and CI run. `mock_clothing_v2` was generated and verified on
2026-10-29 (§8.2).

---

## 4. Desired Status

1. Every SandboxShop has `manual/parts/standard.md`. Without observed
   account or checkout notes it is the checked-in file, byte for byte, and
   no LLM call is made.
2. Every SandboxShop has the same account, checkout and order confirmation
   flows and form selectors. Only the theme, and the labels and layout that
   observed notes change, differ from shop to shop.
3. No Review, Discount code or hint text is in the storefront code. The
   announcement bar and the Reviews section are hidden when the Dataset has
   no codes or no Reviews.
4. The Build loop restyles the prebuilt pages and cannot pass while a
   restyle breaks the account or discount forms.
5. A Dataset has enough Personas, seeded orders, stock and Discount codes
   for account, order and checkout Tasks. The same Dataset inputs and seed
   give the same Personas' orders, codes and Reviews plans.
6. `shopgym gen --data` moves an old shop's catalog onto the current
   templates without change, except that it drops empty collections.
7. `mock_clothing_v2` passes the full sign-up-to-order flow (§8.2).

---

## 5. Proposal

### 5.1 Standard sub-manual

The file is `packages/shop-arena/src/gen/manual_merge/standard_sub_manual.md`.
A person wrote it once by hand from these sources:

- the Dawn theme **v15.5.0**, the last Dawn release with classic customer
  accounts (v16.0.0 removed them): its login, register, account, order,
  addresses, announcement bar and product sections, and its English locale
  file for the exact labels;
- the Shopify Help Center pages for one-page checkout, order confirmation
  numbers, the discount FAQ, and the comparison of classic and new customer
  accounts.

Its H2 sections:

| Section | Content |
| --- | --- |
| Account | All account pages; login with the "Forgot your password?" form; register; the account page with the order history table and the default address; the order page; the address book with add, edit, delete and set default |
| Checkout | One-page layout; contact email, delivery address, shipping method and payment method from the checkout rules; the "Discount code" field; the default address prefilled for a logged-in customer; the order summary |
| Order confirmation | The Shopify thank-you page: "Confirmation #...", "Thank you, <first name>!", the order summary, the addresses and "Continue shopping" |
| Announcement bar | The Dawn announcement bar with "Previous" and "Next" arrows, one slide for each Discount code with its hint, starting at the first code and never moving by itself |
| Reviews | Stars and count near the product title, and a Reviews section with its fields and four sort orders; only fields with data are shown; no "Write a Review", photos, AI summary, topic chips, age or height filters, or helpful-vote buttons |
| Supported behavior | What the backend can do (Account; Checkout and orders; Storefront data) and a "Not supported" list (new customer accounts, social login, express payment buttons, reset-password pages, profile edits, several codes on one cart, returns, writing Reviews, and more) |

Conventions in the file: text in double quotes is an exact label or
message; `<...>` is a value from the Dataset or the Episode state; a
storefront shows only supported behavior, and every visible control works.

Manual merge writes the shop's copy to `manual/parts/standard.md`, next to
the six cut Sub-manuals. The checked-in file is an input of the
`manual_merge` step, so a change to it runs manual merge and every later
step again.

### 5.2 Fusion

`FUSED_SECTIONS` is `Account` and `Checkout`. The split routes these two
H2 sections of the Merged manual to no cut Sub-manual and does not report
them as unrouted. Fusion consumes them instead
(`manual_merge/fusion.ts`).

For each fused section with observed notes, Fusion makes one LLM call with
the prompt `manual_merge/prompts/fuse_standard_section.md`. The prompt gets
the standard section, the observed section, the "Supported behavior"
section and the section's checked labels. Its rules:

- Observed notes win on labels, layout and wording.
- Observed behavior that is not in "Supported behavior" keeps the standard
  text. Examples: passwordless login by code, social login, express
  payment buttons.
- Every checked label stays word for word, in double quotes.

Fusion refuses a reply that has a `#` or `##` heading, or that drops a
checked label. It retries a refused reply once with the reason, and a
second failure fails the step. The fused body replaces the standard
section. Fusion copies the rest of the file unchanged.

| Section | Checked labels |
| --- | --- |
| Account | "Forgot your password?"; "We've sent you an email with a link to update your password."; "Order number <order name>"; "Order <order name>"; "Add a new address"; "Add address"; "Edit address <n>"; "Update address"; "Delete <n>"; "Set as default address"; "Default" |
| Checkout | "Enter a valid discount code"; "Total" |

With no observed notes, Fusion makes no LLM call, and the copy is the
checked-in file.

### 5.3 Prebuilt pages in the Storefront template

The Storefront template builds these pages from the Standard sub-manual
once, so every shop reuses the same logic. The routes are unchanged:
`/account/login`, `/account/register`, `/account`, `/account/addresses`,
`/account/orders`, `/account/orders/:n`, `/account/logout`, `/checkout` and
`/checkout/confirmation/:n`.

- **Login** has the "Forgot your password?" form. After a submit it shows
  "We've sent you an email with a link to update your password." in place
  of the login form.
- **Register** takes first name, last name, email and password, and shows
  the backend's field errors.
- **Account page** shows the order history table (order number, date,
  payment status, fulfillment status, total) and the default address.
- **Order page** shows the line items, totals, the Discount code and
  amount, the addresses and the statuses.
- **Address book** adds, edits and deletes addresses and sets the default.
  The first address becomes the default. Delete asks for confirmation.
- **Checkout** has the "Discount code" field. A valid code changes the
  total. An unknown or inapplicable code shows "Enter a valid discount
  code" and keeps the price. A logged-in customer's default address is
  prefilled.
- **Thank-you page** follows the Order confirmation section.
- **Announcement bar** reads `discountCodeHints`, starts at the first code
  on each page and moves only on "Previous" and "Next".
- **Reviews** read `Product.reviews` and the `reviews.rating` and
  `reviews.rating_count` metafields. They sort by the four sort keys and
  page with "Show more reviews". A field with no data is left out.

`src/templates.browser.test.ts` protects these pages. It seeds and builds
the template, starts the backend on the template's test Dataset, and drives
real pages with the browser steps of the Final eval
(`gen/build/verifiers/browser_steps.ts`). It covers sign up, log out, log
in, "Forgot your password?", the address book, add to cart, the
announcement bar arrows, valid and unknown Discount codes, `/cart.js`,
check out, the thank-you page, order history and detail, a seeded
Persona's orders, and Reviews (paging, sorting, half stars, left-out
fields). It runs in every `pnpm test`, so CI runs it on every PR.
`storefront_template.md` lists each test.

### 5.4 Build loop

The planner's canonical list gains two build tasks after `gen_info_pages` and
before `visual_fix`, both at priority 3:

| Build task | Brief |
| --- | --- |
| `gen_account` | restyle the prebuilt account pages to the theme and the Account section of `parts/standard.md`; keep their behavior and form selectors |
| `gen_checkout` | restyle the prebuilt checkout and thank-you pages to the theme and the Checkout and Order confirmation sections of `parts/standard.md`; keep behavior and form selectors |

The executor prompt tells each build task which Standard sub-manual
sections it reads, and that its quoted labels are exact:

| Build task | Sections | Extra rule |
| --- | --- | --- |
| `gen_navigation` | Announcement bar | the codes and hints come from the backend |
| `gen_product` | Reviews | every Review element comes from backend data; an element with no data is left out |
| `gen_account` | Account | restyle only |
| `gen_checkout` | Checkout, Order confirmation | restyle only |

"Restyle only" means: keep the routes, loaders, actions, GraphQL
operations, redirects and messages; keep each form's `method` and
`action`, each input `name` and `intent` value, and the labels and
accessible names of fields and buttons.

Two Verifiers drive these forms in a real browser, in a fresh Episode,
with the same browser steps as the Final eval
(`gen/build/verifiers/browser_flow.ts`). A changed selector or a broken
page shows as the step that failed. The add-to-cart step checks the
first enabled variant radio of the product form, or submits the form as it
is when the form carries its variant in a hidden input.

| Verifier | Build tasks | Steps |
| --- | --- | --- |
| `account_flow` | `gen_account`, `visual_fix` | sign up, log out, "Forgot your password?" (the login page shows the sent message), log in, add an address, edit it |
| `discount_flow` | `gen_checkout`, `visual_fix` | add a sampled product to the cart; apply a Dataset Discount code with no minimum subtotal, a percent or fixed-amount code first (the "Total" changes); enter `NOT-A-SHOPGYM-CODE` ("Enter a valid discount code" shows, and the "Total" stays) |

`discount_flow` skips its first check when the Dataset has no code without a
minimum subtotal. `routes_200`, `cart_conformance` and `visual_judge` keep
gating these pages. The visual judge gets the Account section for the
account page bucket and the Checkout and Order confirmation sections for the
checkout bucket, from the shop's `parts/standard.md`, with their own budget
of 12,000 characters.

### 5.5 Final eval

The functional sweep adds "Forgot your password?", add an address, edit
it, and apply a Discount code with no minimum subtotal (a free-shipping
code when there is no such code). The visual sweep captures fourteen
pages. The new ones are the thank-you page of a guest order, account
register, the order list and the address book. `shop_gen.md` §5 lists the
full sweeps.

### 5.6 Data synthesis

These rules apply with and without `--data`. `shop_gen.md` §5 has the
details.

| Data | Who decides | Rules |
| --- | --- | --- |
| Discount codes (`commerce.json`) | LLM picks codes, amounts and hints, in the checkout rules step that reads the shipping and refund policies | 3 to 5 codes; at least one of each kind; one percent or fixed code with no minimum; no free-shipping minimum at or above the free-shipping threshold; codes unique when case is ignored; positive amounts; percents below 100; minimums not negative |
| Personas (`customers.json`) | LLM writes names and 1 to 3 addresses; code assigns emails, passwords and ids | 5 Personas; at least two with two or more addresses |
| Seeded orders (`orders.json`) | code, from a fixed seed | 15 orders; the last Persona has none, the others 1 to 6; dates in the 12 months before the Episode clock start (2026-01-01); the newest order is not shipped; three older orders are refunded, partly refunded and partly shipped; the rest are paid and shipped; varied shipping methods, payment methods and saved addresses; four orders use a Discount code; totals follow the backend pricing rules |
| Reviews (`reviews.json`) | code plans each Review from a fixed seed; the LLM writes only the title and text | 15% of products have none, the others 1 to 8; ratings average 4.3; reviewer first name and last initial; dates in the two years before the clock start; a variant of the product; about 80% Verified Buyer; helpful counts 0 to 29; batches of whole products with at most 20 Reviews |

`data_validation` checks that each Review names a real product and
variant, that the Discount codes follow the rules above, and that every
seeded order's totals and discount match the backend pricing rules.

### 5.7 `gen --data` and the source manuals

`shopgym gen <manual_dir>... --name <shop> --data <dir>` (config field
`sourceDataDir`) reads the catalog of an existing SandboxShop Dataset
(`data_synth/source_catalog.ts`):

- `products.json` and `collections.json` keep their JSON values, including
  the fields that the backend schema does not name. Both are checked
  against the backend schema. `images/` is copied as it is.
- `--data` drops each collection with no products, and logs one line that
  names its handle.
- The `collections` through `images` sub-steps do not run, so the catalog
  sizing options and `--image-backend` do not apply.
- The manual gives all other data: identity, store, pages, policies,
  checkout rules with Discount codes, menus, Personas, stock, seeded orders
  and Reviews. `synth_identity` gets a summary of the copied catalog (the
  product count, each collection with its product count, the 10 most
  common product types, the price range and the first 10 titles), so the
  store description fits the products. Menus link only to kept
  collections.
- The three source paths are inputs of `data_synth`, so a change to them
  runs it again.
- The brand scan logs tokens outside the fake-brand allowlist in the
  copied catalog, but does not fail.

`publish` writes `sourceManuals` (the absolute Shop Manual directories) to
`shop.json`, with or without `--data`. Older manifests without the field
still load.

The build agent runs on `openai/gpt-6-sol` unless `--build-model` is set,
also when `--model` is set. Data synthesis, manual merge, Fusion and the
judges use `--model` (default `openai/gpt-5.5`).

---

## 6. Alternatives

- **Explore the logged-in side of each Live storefront.** Rejected: it
  needs an account and real orders on a merchant's store, and the evidence
  would carry personal data up to the anonymization boundary (ADR 0012).
- **Let the build agent write the account and checkout pages for each
  shop.** Rejected: labels and flows would differ from shop to shop, so the
  browser steps could not rely on fixed selectors and messages.
- **Run Fusion on every shop, also with no observed notes.** Rejected: it
  adds an LLM call and drift to every run for no new information.
- **Synthesize a catalog that imitates the old one.** Rejected: handles,
  ids and prices would change, so the old Tasks would no longer match
  (ADR 0017).

---

## 7. Execution Table

| # | Item | Status |
| --- | --- | --- |
| 1 | Standard sub-manual, copied to every shop as `parts/standard.md` | done |
| 2 | Fusion of observed Account and Checkout notes, with checked labels | done |
| 3 | Storefront template: account pages, address book, "Forgot your password?" | done |
| 4 | Storefront template: checkout "Discount code" field, thank-you page | done |
| 5 | Storefront template: announcement bar, product Reviews | done |
| 6 | Storefront template browser suite in every `pnpm test` and CI | done |
| 7 | Data synthesis: Discount codes, five Personas, fifteen seeded orders, Reviews; data validation checks | done |
| 8 | `gen_account` and `gen_checkout`; Standard sub-manual sections for `gen_navigation` and `gen_product` | done |
| 9 | `account_flow` and `discount_flow` Verifiers; visual judge reads the Standard sub-manual | done |
| 10 | Final eval: new functional steps and visual pages | done |
| 11 | `gen --data`; `sourceManuals` in the Shop manifest | done |
| 12 | Build agent default `openai/gpt-6-sol` | done |
| 13 | Generate and verify `mock_clothing_v2` (§8.2) | done (2026-10-29) |

---

## 8. Appendix

### 8.1 File map

```
packages/shop-arena/
  src/gen/manual_merge/
    standard_sub_manual.md        the checked-in Standard sub-manual
    standard_sub_manual.ts        path, file name, FUSED_SECTIONS
    fusion.ts                     Fusion and the checked labels
    prompts/fuse_standard_section.md
  src/gen/data_synth/
    commerce.ts                   checkout rules and Discount codes
    customers.ts                  Personas
    orders.ts                     seeded orders
    reviews.ts                    Review plan and text
    source_catalog.ts             gen --data
  src/gen/build/prompts/          planner, executor and verifier tables
  src/gen/build/verifiers/
    account_flow.ts, discount_flow.ts, browser_flow.ts, browser_steps.ts
    page_judge.ts                 Standard sub-manual excerpt for the judge
  src/gen/final_eval/             functional and visual sweeps
  src/templates.browser.test.ts   Storefront template browser suite
  templates/storefront/           prebuilt pages
```

### 8.2 `mock_clothing_v2`

The pilot needs an apparel SandboxShop with account and order Tasks. The
recipe rebuilds the old `mock_clothing` catalog on the current templates,
from the apparel Shop Manual of the Live storefront that `mock_clothing`
came from:

```bash
shopgym gen outputs/shop_manuals/<host>/<run_id>/artifact \
  --name mock_clothing_v2 --data outputs/shops/mock_clothing/data
```

- A manual directory must hold `manual.md` directly. This Shop Manual has
  the older explore layout, so its manual directory is `<run_id>/artifact`.
- This Shop Manual has no Account or Checkout section, so Fusion makes no
  LLM call, and `parts/standard.md` is the checked-in file.
- The old `mock_clothing` catalog loads as it is (157 products, 60
  collections). `--data` drops its 6 empty collections:
  `wide-leg-pairings`, `rider-short-pairings`, `zip-front-hoodies`,
  `high-collar-pairings`, `pair-it-up` and `match-your-pick`.
- The old `mock_clothing` stays unchanged, and `outputs/` is not committed.

The shop is verified when all of these are true:

1. The Build loop ends `completed`, with every Verifier passing, including
   `account_flow` and `discount_flow`.
2. The Final eval functional sweep passes every step, and the visual sweep
   covers register, the order list, the address book and the thank-you
   page.
3. `shopgym host` runs the shop, and a real browser walks the full
   sign-up-to-order flow.
4. The shop has enough Personas, orders, stock and Discount codes for
   about 10 account and order Tasks and 10 checkout Tasks.

All four were true on 2026-10-29, with the default models. The pull
request of that run records the counts and the screenshots.

### 8.3 Known limitations

- Fusion relies on an LLM. Code checks only the headings and the checked
  labels of a fused section, not the rest of its wording.
- The Standard sub-manual follows Dawn v15.5.0. A move to Shopify's new
  customer accounts needs a new login flow in the backend.
- A copied catalog keeps the anonymization of the shop it came from.
- This work adds commerce features (address edits, Discount codes with a
  price effect, Reviews), which breaks the "add zero commerce features"
  rule of `../shop_guru/task_generation_proposal.md`.
