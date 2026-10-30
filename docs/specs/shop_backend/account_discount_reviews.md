# ShopBackend Address Book, Password Recovery, Discount Codes and Reviews (`packages/shop_backend`)

Status: **Implemented** · Version: **0.1**
Owners: ShopBackend

> Adds to the Backend template the behavior that the Standard sub-manual
> lists as supported: address edits, a password-recovery mock, Discount
> codes with a real price effect and a hint list for the announcement bar,
> and read-only product Reviews. The StateSnapshot shows the results, so
> Checks can grade them.

---

## 1. Overview

The Standard sub-manual
([`../shop_arena/standard_account_checkout.md`](../shop_arena/standard_account_checkout.md),
ADR 0016) gives every SandboxShop account, checkout and order confirmation
pages, an announcement bar with the shop's Discount codes, and product
Reviews. Its "Supported behavior" list says what the backend must do.
Before this work the backend could not do four of these things:

- edit a customer's saved addresses;
- take a password reset request;
- change a price with a Discount code (codes were stored, but had no price
  effect);
- serve product Reviews (old Hydrogen shops hard-coded them in the
  storefront).

The Dataset schema and the StateSnapshot are part of the Sandbox contract,
which no generated shop may change. So these features go into the Backend
template, and every shop gets them without `--gen-backend`.

This spec adds:

- four Storefront API address book mutations (§5.2);
- `customerRecover`, which records the request and sends nothing (§5.3);
- Discount code pricing on carts and orders, and the `@sandbox` query
  `discountCodeHints` (§5.4);
- `reviews.json`, the `@sandbox` connection `Product.reviews`, and the
  rating metafields (§5.5);
- the StateSnapshot fields for all of them (§5.6).

Every new Dataset field and file is optional, so older Datasets still load.
The Control API does not change. The work follows ADR 0007 (`@sandbox`),
ADR 0008 (Episode isolation), ADR 0009 (Episode clock) and ADR 0010 (one
Backend template per shop).

---

## 2. Terminology

- **Address book** - the saved addresses of one customer in an Episode,
  with one default.
- **Password reset request** - the email and Episode clock time of one
  `customerRecover` call.
- **Discount code** - an entry in `commerce.json` `discount_codes`: a
  percent off, a fixed amount off, or free shipping, with an optional
  minimum and a hint text.
- **Merchandise subtotal** - the sum of unit price times quantity over the
  lines, before any discount, tax or shipping.
- **Applicable** - a Discount code on a cart applies when it matches a
  Dataset code in any case and the merchandise subtotal reaches its
  minimum.
- **Review** - one read-only entry of `reviews.json`.
- **`@sandbox`** - the SDL directive for operations, types and fields with
  no Storefront API equivalent (ADR 0007).

`GLOSSARY.md` defines the same domain terms.

---

## 3. Current Status

Before this work (`stateful_commerce.md` v0.1):

- `Customer.addresses` and `defaultAddress` were read-only.
- No password recovery mutation.
- `cartDiscountCodesUpdate` stored codes, and `applicable` was a
  placeholder. Cart cost, checkout and orders ignored the codes.
- No Review data and no rating metafields.
- The StateSnapshot had no discount fields and no password reset requests.

After this work, everything in §5 is in `packages/shop_backend`. The
contract suite (`tests/contract/`) pins each feature, and both template
test Datasets (the backend's and the Storefront template's) have Discount
codes, Reviews, and Personas with past orders.

---

## 4. Desired Status

1. A logged-in customer can add, edit and delete addresses and set the
   default, with the Storefront API's argument shapes, payloads and user
   errors.
2. A password reset request always succeeds, sends nothing, changes no
   password, and is visible to a grader.
3. A valid Discount code lowers the price by the exact amount of its rule,
   computed in integer cents, and the order records the code and the
   amount. An unknown or inapplicable code changes nothing.
4. The storefront can list every Discount code with its hint, and every
   product's Reviews with paging and four sort orders. Stars and count
   always agree with the list.
5. Read queries stay deterministic. The same Episode actions give the same
   ids, times and totals.
6. Old Datasets without the new files and fields still load and render.

---

## 5. Proposal

### 5.1 Dataset additions

All additions have defaults, so a Dataset without them loads as before.

| File | Field | Shape |
| --- | --- | --- |
| `commerce.json` | `discount_codes` | list, default `[]`; each entry has `code` (matched in any case, unique ignoring case), `kind` (`percentage`, `fixed_amount` or `free_shipping`), `amount` (decimal string: the percent, or the money off; not used for free shipping), `minimum_subtotal` (decimal string or `null`, default `null`) and `hint` (short shopper-facing text) |
| `orders.json` | `discount_code` | the code in its `commerce.json` spelling, or `null` (default) |
| `orders.json` | `discount_amount` | decimal string, default `"0.00"`: the merchandise discount, or the shipping charge waived by a free-shipping code |
| `reviews.json` | (new file, optional) | list of Reviews: `id`, `product_handle`, `variant_id` (the variant bought), `rating` (1 to 5), `title`, `body`, `reviewer_name` (first name and last initial), `created_at` (ISO 8601 UTC), `verified_buyer`, `helpful_count` (0 or more) |

### 5.2 Address book

The Storefront API mutations, with its argument and payload shapes:

| Mutation | Arguments | Payload |
| --- | --- | --- |
| `customerAddressCreate` | `address: MailingAddressInput!`, `customerAccessToken` | `customerAddress`, `customerUserErrors` |
| `customerAddressUpdate` | `address`, `customerAccessToken`, `id` | `customerAddress`, `customerUserErrors` |
| `customerAddressDelete` | `customerAccessToken`, `id` | `deletedCustomerAddressId`, `customerUserErrors` |
| `customerDefaultAddressUpdate` | `addressId`, `customerAccessToken` | `customer`, `customerUserErrors` |

Rules:

- An unknown or expired token gives `UNIDENTIFIED_CUSTOMER`.
- A new address needs `address1`, `city`, `country` and `zip`. A blank
  required line gives one `BLANK` error for each line, with the field path
  `["address", <line>]`. An edit keeps the lines it leaves out.
- An id that the customer does not own gives `NOT_FOUND` ("Address does
  not exist").
- The first address becomes the default. When the default is deleted, the
  first remaining address becomes the default. A customer with addresses
  always has a default.
- Every change goes through the Episode state and moves the Episode clock.
  Checkout saves addresses the same way as the address book.

### 5.3 Password-recovery mock

`customerRecover(email: String!)` returns an empty `customerUserErrors`
for every email, known or not, as Shopify does so that it does not reveal
which emails exist. It sends no email and changes no password. It records
a Password reset request (the trimmed email and the Episode clock time) in
the Episode state. Reset pages, reset links, `customerReset` and account
activation are not added.

### 5.4 Discount codes

Pricing rules (`state/pricing.ts`):

- A cart holds at most one code. A second code gives the user error
  `INVALID` on `discountCodes`: "A cart can hold only one discount code".
- Codes match in any case. A known code is stored in its `commerce.json`
  spelling, and an unknown code as typed.
- The minimum is checked against the merchandise subtotal before the
  discount.
- A percent or fixed code lowers the merchandise subtotal, never below
  zero. Tax is the flat rate on the subtotal after the discount.
- A free-shipping code waives the shipping charge. The free-shipping
  threshold is checked against the subtotal before the discount.
- All amounts are computed in integer cents.

On the cart:

- `cartCreate` and `cartDiscountCodesUpdate` store the code. An empty list
  removes it.
- `Cart.discountCodes` reports `applicable` for the stored code.
  `applicable`, `Cart.cost` and `Cart.discountAllocations` are computed on
  each read. A code that the cart drops below the minimum stays on the
  cart but stops applying, and applies again above it.
- `Cart.cost.subtotalAmount` is the merchandise subtotal before the
  discount. `totalAmount` is the subtotal after the discount plus tax.
- `Cart.discountAllocations` holds one `CartCodeDiscountAllocation` while
  the code applies: the code, the merchandise amount taken off (0 for free
  shipping), and the target type (`LINE_ITEM` or `SHIPPING_LINE`).
- An unknown or inapplicable code is reported as not applicable and does
  not change the price. The storefront shows "Enter a valid discount code".

At checkout, `checkoutComplete` applies the cart's applicable code. The
order records it as `Order.discountCode` (`@sandbox`): the code, the target
type, and the amount (the merchandise discount, or the shipping charge
that a free-shipping code removed; 0 when shipping was already free).

`discountCodeHints` (`@sandbox`) lists every Discount code with its hint,
in `commerce.json` order, for the storefront's announcement bar. The
Storefront API has no such query, because a Shopify merchant types the
announcement text into the theme.

### 5.5 Reviews

- `Product.reviews(first, after, sortKey = MOST_RECENT)` (`@sandbox`)
  returns a `ReviewConnection` with `nodes`, `edges` and `pageInfo`. The
  Storefront API has no Review type, because shops show Reviews through a
  review app.
- `ReviewSortKeys`: `MOST_RECENT`, `HIGHEST_RATING`, `LOWEST_RATING`,
  `MOST_HELPFUL`. Ties put the more recent Review first, then keep the
  `reviews.json` order, so every read gives the same list.
- A `Review` has `id`, `rating`, `title`, `body`, `reviewerName`,
  `createdAt`, `verifiedBuyer`, `helpfulCount` and `variant` (`null` when
  the product no longer has that variant).
- The standard product metafields `reviews.rating` (type `rating`, the mean
  rounded half up to one decimal, scale 1.0 to 5.0) and
  `reviews.rating_count` are computed from the same Reviews. A product with
  no Reviews has neither metafield.
- Reviews are read-only. There are no Review mutations.

### 5.6 StateSnapshot fields

| Path | Meaning |
| --- | --- |
| `passwordResetRequests[]` | `{ email, requestedAt }` of each request in the Episode, in request order; the email need not belong to a customer |
| `carts[].discountCodes` | the stored codes; at most one |
| `carts[].appliedDiscountCode` | the stored code when it applies to the cart now, else `null` |
| `orders[].discountCode` | the code applied at checkout, or `null` |
| `orders[].discountAmount` | the merchandise discount, or the shipping charge waived by a free-shipping code |
| `customers[].addresses`, `customers[].defaultAddressId` | already present; they now show the address book changes |

Seeded orders carry their `discount_code` and `discount_amount` into the
same order fields.

### 5.7 Tests

- Contract suite (`tests/contract/`), over HTTP on the backend test
  Dataset with the `x-shopgym-episode` header and the Control API:
  `addresses.test.ts`, `password_recovery.test.ts`, `discount.test.ts`
  (each kind, minimums, case, one code per cart, inapplicable codes, the
  code on orders, the hint query) and `reviews.test.ts` (list, paging,
  sorting, rating metafields). A generated shop may not change these
  tests.
- Unit tests next to the resolvers, the pricing rules and the snapshot.
- The Storefront template browser suite drives the same features through
  real pages (`../shop_arena/standard_account_checkout.md` §5.3).

---

## 6. Alternatives

- **Real password reset (email, link, reset page, `customerReset`).**
  Rejected: the sandbox has no mail, and a request record is enough to
  grade "request a password reset" Tasks.
- **Product- or collection-scoped codes, one use per customer, date
  windows, several codes on one cart.** Rejected for now: one code with a
  clear rule gives each "use the code that saves the most" Task one
  correct answer.
- **Hint texts in the storefront code.** Rejected: the storefront must not
  hard-code Dataset content, and a Check must be able to read every code
  and hint from the Dataset.
- **Stored rating metafields in `products.json`.** Rejected: computed
  values always agree with the Review list.
- **Review mutations.** Out of scope: writing Reviews, photos and helpful
  votes are not in the Standard sub-manual's supported behavior.

---

## 7. Execution Table

| # | Item | Status |
| --- | --- | --- |
| 1 | `commerce.json` `discount_codes`; `orders.json` `discount_code` and `discount_amount`; optional `reviews.json` | done |
| 2 | Discount code pricing on carts, `checkoutComplete`, `Order.discountCode` | done |
| 3 | `discountCodeHints` | done |
| 4 | Address book mutations | done |
| 5 | `customerRecover` and `passwordResetRequests` | done |
| 6 | `Product.reviews` and the rating metafields | done |
| 7 | StateSnapshot fields; contract tests; both test Datasets | done |
| 8 | Profile edits (`customerUpdate`) and account activation | not planned (classic accounts have no profile edits) |

---

## 8. Appendix

### 8.1 File map

```
packages/shop_backend/
  src/data/schema.ts              Dataset schemas (discount codes, orders, reviews.json)
  src/schema/customer.ts          address book, customerRecover
  src/schema/cart.ts              cart discount fields
  src/schema/checkout.ts          discountCodeHints, checkoutComplete
  src/schema/order.ts             Order.discountCode
  src/schema/catalog.ts           Product.reviews, Review types
  src/state/pricing.ts            Discount code pricing rules
  src/state/shop_state.ts         address book and password reset requests in the Episode
  src/resolvers/review.ts         Review list and rating metafields
  src/sandbox/snapshot.ts         StateSnapshot fields
  tests/contract/                 addresses, password_recovery, discount, reviews
```

### 8.2 Pricing example

A cart with merchandise subtotal 80.00, tax rate 0.10, code `WELCOME10`
(percent, 10, no minimum): discount 8.00, subtotal after discount 72.00,
tax 7.20, cart `totalAmount` 79.20. At checkout with a 5.00 shipping
method and no free-shipping threshold, the order total is 84.20, with
`discountCode` `WELCOME10` and `discountAmount` 8.00. Typed as
`welcome10`, the code gives the same result.
