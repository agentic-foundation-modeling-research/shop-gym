# @shop-gym/core

Shared contracts and utilities with no ShopGym-internal dependencies.

- `schema/task.ts` - benchmark task contract: `goal` + optional `setup` +
  `eval` checks (`string_match`, `url_match`, `locator_probe`,
  `state_check`, `llm_judge`).
- `schema/result.ts` - per-episode result and aggregate report contracts,
  including token usage and cost.
- `pipeline/` - a file-based step pipeline. Steps declare input and output
  paths; completion is derived from the filesystem (outputs exist and the
  recorded input fingerprint still matches), so re-running a pipeline only
  executes stale steps.
- `env.ts` - explicit, one-shot loading of provider credentials from the
  project `.env` with shell values taking precedence.

Dataset schemas are not here: they are owned by `@shop-gym/shop-backend`
so the backend template stays standalone.
