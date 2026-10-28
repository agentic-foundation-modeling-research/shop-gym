# Sandbox time and ids are deterministic, not wall-clock

Each episode has its own clock. It starts at `2026-01-01T00:00:00.000Z` and moves one second per account or order mutation. Cart changes read the clock for `Cart.updatedAt` but do not move it, so cart activity never shifts other timestamps. Ids, order numbers and access tokens come from sequential counters (a fresh shop's first order is `#1001`, tokens are `sandbox-token-<n>`). We chose this over wall-clock time and random ids so the same action sequence always gives the same state, and graders and seed tasks can state exact expected values.

## Consequences

- Timestamps look artificial, and access tokens never expire inside an episode, because the clock moves only on mutations.
- Ids are unique only inside one episode. For example, cart ids restart at `cart-1` in every episode.
