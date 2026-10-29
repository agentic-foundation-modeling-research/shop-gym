# Sub-Manual - Standard

Every SandboxShop gets this Sub-manual. It describes the pages that
Storefront exploration cannot observe on a Live storefront: the customer
account, the checkout and the order confirmation. It also gives the rules
for the announcement bar and for Reviews, and the list of behavior that the
shop's backend supports.

- Account pages follow Shopify classic customer accounts. The layout
  reference is the Dawn theme **v15.5.0**, the last Dawn release with
  classic account pages (v16.0.0 removed them). Labels come from its
  English locale file `locales/en.default.json`.
- Checkout follows Shopify one-page checkout, the default checkout layout.
  Order confirmation follows the Shopify thank-you page.
- Text in double quotes is an exact label or message. Use it word for word.
  Account and announcement bar labels come from the Dawn locale file. The
  discount error "Enter a valid discount code" comes from the Shopify Help
  Center, which shows it for a code that does not exist or is not active.
  The other checkout, thank-you and Reviews labels, and the use of the
  discount error for every code that does not apply, are the sandbox
  standard.
- `<...>` is a value from the Dataset or from the Episode state.
- Show only what the backend supports (see "Supported behavior"). Every
  visible control must work.

Sources, read on 2026-10-29:

- Dawn v15.5.0: `sections/main-login.liquid`, `main-register.liquid`,
  `main-account.liquid`, `main-order.liquid`, `main-addresses.liquid`,
  `announcement-bar.liquid`, `main-product.liquid` (rating block),
  `header.liquid` (account icon), `assets/customer.css`, `assets/global.js`
  (slideshow) and `locales/en.default.json`, at
  https://github.com/Shopify/dawn/tree/v15.5.0
- Dawn v16.0.0 release notes: https://github.com/Shopify/dawn/releases/tag/v16.0.0
- https://help.shopify.com/en/manual/checkout-settings/customize-checkout-configurations/one-page-checkout
- https://help.shopify.com/en/manual/fulfillment/setup/order-status-page/order-confirmation-numbers
- https://help.shopify.com/en/manual/discounts/discounts-faq
- https://help.shopify.com/en/manual/customers/customer-accounts/upgrade/compare-features

## Account

A customer signs in with an email and a password. Classic accounts have no
profile editing: the customer cannot change their name or email.

### All account pages

- The header account icon links to `/account/login` when the customer is
  logged out, and to `/account` when the customer is logged in. Its
  accessible name is "Log in" when logged out and "Account" when logged
  in.
- The login, register and addresses pages are one narrow, centered column
  (Dawn: about 330 px wide, and 480 px from 750 px wide). The fields are
  full width. The buttons are centered and at least 120 px wide, not full
  width. Each text field has a floating label with the same text as its
  placeholder.
- On login and register the headings are centered. The addresses page
  differs: see "Addresses".
- The account page and the order page use the full page width. From 990 px
  wide they have two columns: the table on the left, and a narrow column on
  the right. Below 990 px the right column goes under the table.
- Account pages other than login and register send a logged-out customer
  to `/account/login`.
- When a form fails, it shows "Please adjust the following:" above the
  form, then one line for each error from the backend.

### Login (`/account/login`)

- H1 "Login".
- Fields "Email" and "Password", then the link "Forgot your password?".
- Then the button "Sign in" and the link "Create account" to
  `/account/register`.
- A wrong email or password keeps the customer on the page and shows the
  error.
- On success the customer goes to the path in the `redirectTo` query
  parameter when the URL has one (for example `/checkout`), and else to
  `/account`. The "Create account" link keeps the `redirectTo` value.

"Forgot your password?" opens the recover form in place of the login form,
on the same page:

- H1 "Reset your password".
- Text "We will send you an email to reset your password".
- Field "Email", the button "Submit", and the link "Cancel", which goes
  back to the login form.
- After "Submit", the page shows the login form again with the message
  "We've sent you an email with a link to update your password." above it.
  The message is the same for every email, known or not.

### Register (`/account/register`)

- H1 "Create account".
- Fields "First name", "Last name", "Email" and "Password", then the
  button "Create".
- An email that is already taken, or a password that is too short, shows
  the error under the field and in the list above the form.
- On success the customer is logged in and goes to the `redirectTo` path
  when the URL has one, and else to `/account`.

### Account page (`/account`)

- H1 "Account". Under it, "Log out" with the account icon. It looks like
  a link, but it is the button of a form that posts to `/account/logout`.
  It ends the session and goes to `/`.
- Left column: H2 "Order history" and a table with the columns "Order",
  "Date", "Payment status", "Fulfillment status" and "Total". One row for
  each order, newest first.
  - "Order" is the order name, for example `#1001`. It links to the order
    page. The link's accessible name is "Order number <order name>", for
    example "Order number #1001".
  - "Date" is the order date, for example `March 3, 2025`.
  - "Payment status" and "Fulfillment status" are short labels in sentence
    case, for example Paid, Partially refunded, Refunded, Unfulfilled,
    Partially fulfilled, Fulfilled.
  - "Total" is the order total with the currency code, for example
    `$58.00 USD`.
- With no orders, the text "You haven't placed any orders yet." replaces
  the table.
- Right column: H2 "Account details", the default address as postal lines
  (name, company, address lines, city, province and postal code, country,
  phone), and the link "View addresses (<number of addresses>)" to
  `/account/addresses`. A customer with no default address, for example a
  new customer, has no address lines, and the link is "View addresses (0)".
- Below 750 px wide, each table row becomes a block of lines, and the
  header row is hidden. Each line has the column name on the left and the
  value on the right, with no colon.
- `/account/orders` shows the same "Order history" table on its own page.

### Order page (`/account/orders/<order number>`)

- H1 "Account", then the link "Return to Account details" to `/account`.
- H2 "Order <order name>", for example "Order #1001", then
  "Placed on <date and time>", for example "Placed on March 3, 2025 at
  2:15 pm".
- A table with the columns "Product", "SKU", "Price", "Quantity" and
  "Total". Each row has the product title (a link to the product page),
  the variant title under it when the product has more than one variant,
  the SKU, the unit price, the quantity and the line total.
- Under the rows, the totals in this order:
  - "Subtotal".
  - "Discount", with the Discount code and the amount as a negative, for
    example `WELCOME10 -$5.80`. Only when the order has a Discount code. For
    a free-shipping code, the row shows the code and the text
    "Free shipping" in place of an amount, for example
    `FREESHIP Free shipping`, and the shipping row shows `$0.00`.
  - "Shipping (<shipping method title>)".
  - "Tax". Dawn adds the tax title and rate, as in "Tax (VAT 13.0%)". The
    sandbox has one tax rate with no title, so the row shows only "Tax".
  - "Total", with the currency code.
- Right column: H2 "Billing Address" with "Payment Status: <status>" and
  the billing address, then H2 "Shipping Address" with
  "Fulfillment Status: <status>" and the shipping address. The sandbox has
  no separate billing address, so the billing address is the shipping
  address.

### Addresses (`/account/addresses`)

- H1 "Addresses", centered, then the link "Return to Account details" to
  `/account`. The H2 headings of the forms and the form fields are
  left-aligned.
- The button "Add a new address" opens the add form under it:
  - H2 "Add a new address".
  - Fields "First name", "Last name", "Company", "Address 1", "Address 2",
    "City", "Country/region", "Province", "Postal/ZIP code" and "Phone".
  - From 750 px wide, "First name" and "Last name" share one row. Every
    other field is full width.
  - "Country/region" is a select with a fixed label above it. Its options
    are the countries that the backend lists. "Province" is a text field
    with a floating label, because the sandbox has no list of provinces.
  - The checkbox "Set as default address".
  - The buttons "Add address" and "Cancel". "Cancel" closes the form.
- Then one block for each saved address:
  - The centered heading "Default" above the default address only.
  - The address as postal lines.
  - The buttons "Edit" and "Delete". For the address in place <n> of the
    list, their accessible names are "Edit address <n>" and "Delete <n>",
    for example "Edit address 1" and "Delete 1".
  - "Edit" opens the edit form under the address: H2 "Edit address", the
    same fields filled with the address, the checkbox
    "Set as default address", and the buttons "Update address" and
    "Cancel".
  - "Delete" opens the browser's own confirm dialog with the text
    "Are you sure you wish to delete this address?". It is not a custom
    modal. On confirm, the address is removed.
- After add, update or delete, the page shows the new list.

## Checkout

Checkout is one page at `/checkout`. Customers enter and review their order
details, shipping information and payment details on that page. A guest can
check out. A logged-in customer can check out too.

### Layout

- On a desktop screen, two columns: the form on the left, and the order
  summary on the right on a light gray background.
- On a mobile screen, the order summary is a collapsed bar at the top with
  the label "Order summary", a toggle to show it, and the total.

### Form, in this order

1. **Contact**: the field "Email". A guest also sees a "Log in" link to
   `/account/login?redirectTo=%2Fcheckout`.
2. **Delivery**: the shipping address fields "Country", "First name",
   "Last name", "Company (optional)", "Address",
   "Apartment, suite, etc. (optional)", "City", "Province / State",
   "Postal code" and "Phone (optional)".
3. **Shipping method**: one radio choice for each shipping method in the
   checkout rules, with its title and price. The first method is selected.
   Free shipping from a free-shipping code or from the free-shipping
   threshold shows the price as "Free".
4. **Payment**: one radio choice for each payment method in the checkout
   rules, with its title. The first method is selected. The sandbox takes
   no card number or other payment details, so there are no payment
   fields.
5. The button "Pay now". It places the order and goes to the thank-you
   page.

### Logged-in customer

- The "Email" field has the account email in it.
- The Delivery fields have the customer's default address in them. The
  customer can change every field before paying.

### Order summary

- One row for each line: the product image with the quantity in a small
  badge, the product title, the variant title, and the line price.
- The field "Discount code" and the button "Apply".
  - A valid code shows as a tag with the code name and a remove button
    under the field, and adds the "Discount" line to the totals. For a
    free-shipping code, the "Discount" line shows the code and the text
    "Free shipping" in place of an amount, and the shipping price shows
    "Free".
  - A cart has one code at a time. A valid code replaces the code that was
    applied before.
  - Codes match with any upper and lower case.
  - An unknown code, or a code whose minimum subtotal is not met, shows
    "Enter a valid discount code" under the field and does not change the
    price. The code is not kept, and the code that was applied before, if
    any, stays.
  - When the cart drops below the minimum of a code that was applied
    before, the tag stays, the code stops applying, and
    "Enter a valid discount code" shows under the field.
- Totals in this order: "Subtotal", "Discount" (the code name and the
  amount as a negative, or "Free shipping", only when a code applies),
  "Shipping", "Taxes",
  and "Total" in larger text with the currency code before the amount.
  Checkout follows Shopify checkout and says "Taxes". The order page
  follows Dawn and says "Tax".

## Order confirmation

The thank-you page at `/checkout/confirmation/<order number>` shows after
"Pay now". It uses the checkout layout: the details on the left and the
order summary on the right.

- A check-mark icon, then "Confirmation #<order number>" in small text,
  for example "Confirmation #1001". The sandbox uses the order number as
  the confirmation number, so it matches the order name `#1001` in the
  order history.
- The heading "Thank you, <first name>!", with the first name from the
  shipping address. Without a first name, the heading is "Thank you!".
- An "Order details" block with:
  - "Contact information": the email.
  - "Shipping address" and "Billing address": both are the shipping
    address.
  - "Shipping method": the title of the chosen method.
  - "Payment method": the title of the chosen method.
- The button "Continue shopping", which goes to `/`.
- The order summary on the right: the lines and the totals as at checkout,
  with the applied Discount code. There is no "Discount code" field on
  this page.
- An order placed while logged in also appears in the customer's
  "Order history".

## Announcement bar

The Dawn announcement bar, a full-width strip above the header, shows the
Discount codes.

- One slide for each Discount code, in Dataset order. The slide shows the
  code, then the code's hint text from the backend, for example
  `WELCOME10 - 10% off orders over $50`. The text is not a link.
- With two or more slides, a Previous arrow button on the left and a Next
  arrow button on the right of the text. They show only an arrow icon, no
  text. Their accessible names are "Previous announcement" and
  "Next announcement".
- With two or more slides, the bar is a carousel region with the
  accessible name "Announcement bar". Each slide has the accessible name
  "<n> of <total>", for example "1 of 3".
- The bar starts at the first code and never moves by itself.
  Auto-rotate is off.
- "Next" on the last slide goes to the first slide. "Previous" on the
  first slide goes to the last slide.
- With one code, the bar shows that one slide with no arrows. The bar is
  then a plain region with the accessible name "Announcement".
- With no codes, there is no announcement bar.
- Never type a code or a hint into the storefront code. They all come
  from the backend.

## Reviews

Reviews are read-only data from the backend.

### Near the product title

- Stars and a count, from the product metafields `reviews.rating` and
  `reviews.rating_count`.
- Dawn's rating block: the stars, then the text `<rating> / <scale max>`,
  for example `4.3 / 5.0`, then the count in parentheses, for example
  `(12)`.
- The stars round to the nearest half star: a decimal part from 0.3 to 0.7
  shows a half star, and a decimal part above 0.7 shows a full star.
- The accessible name is "<rating> out of <scale max> stars".
- A product with no Reviews shows no stars and no count.

### Reviews section

- A "Reviews" section below the product details, with the average rating,
  the stars and the number of Reviews at the top.
- A sort control with the options "Most recent", "Highest rating",
  "Lowest rating" and "Most helpful". The default is "Most recent".
- One block for each Review, with:
  - the stars for its rating (1 to 5);
  - its title and text;
  - the reviewer name (first name and last initial);
  - the date;
  - a "Verified Buyer" badge, only when the Review has the flag;
  - the variant bought, for example `Size: M / Color: Black`;
  - the helpful count as plain text: "1 person found this helpful", or
    "<count> people found this helpful" for a larger count, for example
    "12 people found this helpful". It is not a button. A count of 0 shows
    no text.
- A "Show more reviews" button loads the next page of Reviews. It is
  hidden when there are no more Reviews.
- Show only the fields that have data. Leave out an element that has no
  data.
- A product with no Reviews has no Reviews section.
- Never put Review content into the storefront code. Everything comes
  from the backend.
- Do not show: "Write a Review", Review photos, an AI summary, topic
  chips, age or height filters, or helpful-vote buttons.

## Supported behavior

The shop's backend supports only the behavior in this list. When a Shop
Manual describes account or checkout behavior that is not in this list,
keep the standard text above.

### Account

- Register with first name, last name, email and password. An email can
  register only once.
- Log in with email and password. Log out.
- Request a password reset with "Forgot your password?". The request always
  succeeds and the backend records it. It sends no email and changes no
  password.
- Read the order history and each order of the logged-in customer.
- Add, edit and delete addresses, and set the default address.

### Checkout and orders

- Guest checkout and logged-in checkout.
- One contact email and one shipping address for each order. The billing
  address is the shipping address.
- One shipping method and one payment method for each order, from the
  checkout rules. No payment details.
- One tax rate from the checkout rules on the subtotal after discount, and
  an optional free-shipping threshold. The sandbox checks the threshold
  against the merchandise subtotal before the discount.
- One Discount code for each cart, with one of three kinds: a percent off
  the merchandise subtotal, a fixed amount off the merchandise subtotal,
  or free shipping. Codes match with any upper and lower case. A code can
  have a minimum merchandise subtotal, which is checked before the
  discount. A discount never makes the subtotal negative.
- A code stays on the cart when the cart drops below the minimum, but it
  stops applying.
- The order records the Discount code and the discount amount. For a
  free-shipping code, the amount is the shipping charge that the code
  removed. When shipping is already free, a free-shipping code still
  applies, and its amount is 0.
- An order placed while logged in goes into the customer's order history.
- Seeded orders can have the payment statuses paid, partially refunded and
  refunded, and the fulfillment statuses unfulfilled, partially fulfilled
  and fulfilled.

### Storefront data

- The list of Discount codes with their hint texts, in Dataset order, for
  the announcement bar.
- Reviews for each product, with paging and the four sort orders, and the
  rating and count metafields.

### Not supported

Keep the standard text, and show no control, for:

- New customer accounts: passwordless login with a one-time code, the
  Customer Account API, and OAuth.
- Social login, "Sign in with Shop", Shop Pay, and express payment buttons
  (Shop Pay, PayPal, Apple Pay, Google Pay buttons above the form).
- A reset-password link, a reset-password page, and account activation.
- Profile edits (name, email), store credit, wishlists.
- Local pickup, delivery instructions, tips, gift cards, gift messages,
  "Save this information for next time", and marketing opt-in checkboxes.
- A separate billing address.
- Several codes on one cart, codes for some products or collections only,
  codes for one use per customer, and codes with start or end dates.
- A separate offers page, and code hints on product pages.
- Returns, exchanges, cancellations, refund lines, and shipment tracking.
- Writing Reviews, Review photos, helpful votes, AI summaries, topic
  chips, and age or height filters.
