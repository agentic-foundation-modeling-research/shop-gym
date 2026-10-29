# Account, checkout and order confirmation follow a Standard sub-manual, not the Shop Manual

Storefront exploration sees a Live storefront only as a logged-out buyer, so a Shop Manual never describes the account pages, a completed checkout or the order confirmation. SandboxShops still need these pages for account, order and checkout Tasks. Every SandboxShop therefore gets one checked-in Standard sub-manual (`manual/parts/standard.md`) that describes them by the Shopify standard: classic customer accounts with the Dawn theme v15.5.0 as the layout reference, one-page checkout, and the thank-you page. It also holds the rules for the announcement bar and for Reviews, and the list of behavior that the backend supports. The Storefront template builds these pages from it once, and the build tasks only restyle them.

## Considered Options

- Explore the logged-in side of each Live storefront: this needs an account and real orders on a merchant's store, and the evidence would carry personal data up to the anonymization boundary (ADR 0012).
- Let the build agent write these pages for each shop from nothing: labels and flows would differ from shop to shop, so the browser steps, the Verifiers and the Final eval could not rely on fixed selectors and messages.
- Take the pages from a second Live storefront that has accounts: the one candidate had no customer accounts, and one shop is a narrower standard than Shopify's own.

## Consequences

- Account, checkout and order confirmation pages have the same labels and flows in every SandboxShop; only the theme changes. Observed account or checkout notes in a Shop Manual may change the labels and the layout of one shop's copy, but never add behavior that the backend does not support.
- The Standard sub-manual is hard to change: the Storefront template, the Backend template, the browser steps and the Verifiers follow its labels and flows, so a change to it is a change to all of them.
- Dawn v16.0.0 removed classic customer accounts. The Standard sub-manual stays on v15.5.0. A move to Shopify's new customer accounts (passwordless login with a one-time code) needs a new login flow in the backend.
- Its supported behavior includes address edits, discount codes with a price effect, and product reviews. This knowingly breaks the "add zero commerce features" rule of the task generation pilot proposal (`docs/specs/shop_guru/task_generation_proposal.md`).
