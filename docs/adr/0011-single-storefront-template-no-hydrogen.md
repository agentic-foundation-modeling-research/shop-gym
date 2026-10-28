# One React Router storefront template; Hydrogen is removed

v1.0 had two storefront templates: Hydrogen and a hand-written React Router 7 SSR app. We kept only the React Router app. Hydrogen's account routes talk to Shopify's hosted Customer Account API, which has no local equivalent, so the sandbox would have to emulate OAuth to keep them working; one template also halves template and prompt maintenance.

## Consequences

Shops built with Hydrogen under v1.0 cannot be hosted with `shopgym host`, which reads only the published `storefront/`, `backend/` and `shop.json` layout.
