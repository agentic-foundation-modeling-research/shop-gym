# Episodes share one backend process and are isolated by a request header

Parallel evaluation needs many agents on one shop without shared state. Each request may carry `x-shopgym-episode: <id>`; the backend keeps one state branch per episode, forked copy-on-write from the base dataset on first use, and a request without the header uses the `default` branch. The browser session sets the header on every request, and the storefront forwards it on every backend call it makes.

## Considered Options

- One backend and storefront process pair per episode: simple, but two processes and a Vite SSR boot per task give poor RL throughput.
- A reset endpoint only, with episodes run one at a time: blocks parallel evaluation and shared hosted shops.
- Episode id in the URL (`/episodes/<id>/graphql`): breaks Storefront-API clients that hardcode `/graphql`. A header is invisible to them.

## Consequences

The storefront makes all backend calls on the server and copies the header from the incoming request. It has no client-side GraphQL calls; every form posts to a route action, so the browser only talks to the storefront.
