# Each shop owns a copy of the backend template, guarded by a sandbox contract

Shop-specific rules (loyalty, bundles, pickup, pre-orders) need real code, but agent-written backend code must not break grading. So the backend package is a complete, tested template: generation copies it into every shop, the shop is always hosted from its own `backend/`, and with `--gen-backend` the build agent may edit that copy like any other code. A small sandbox contract keeps it gradable: `src/data/schema.ts`, `src/sandbox/**` and `tests/contract/**` must stay byte-identical to the template, the contract suite must pass, and graders read only the `StateSnapshot` that `src/sandbox/` exports, validated with the schema from the pristine package.

## Considered Options

- A fixed core engine plus a typed per-shop plugin API (`extend type` SDL and an `ExtensionApi`): rejected as too complex. It needs a plugin loader, merged-schema validation and a second API to document, and gives less freedom than real code.
- One fixed backend for every shop: still the result when `--gen-backend` is off, but it cannot express shop-specific rules.

## Consequences

The agent may not change the dataset schema, so data synthesis stays independent of backend generation.
