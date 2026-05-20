/**
 * GraphQL codegen config (T7.1).
 *
 * Reads the SDL from `src/schema.ts` (extracted from the `/* GraphQL *\/`
 * tagged template literal by `@graphql-tools/code-file-loader`) and emits
 * `src/__generated__/resolvers-types.ts` containing:
 *
 *   - SDL type aliases (`Product`, `CartInput`, `ProductSortKeys`, ...).
 *   - `*Args` types — argument shapes for every field that takes arguments.
 *     Resolver files import these instead of hand-typing duplicates, so
 *     adding/renaming/removing an SDL argument surfaces as a compile error.
 *   - `Resolvers<ContextType>` — typed resolver map keyed by SDL type, used
 *     at the seam in `resolvers/index.ts`.
 *
 * Mappers are intentionally omitted at this milestone. Per-resolver parent
 * shapes are the existing internal `*Node` types defined alongside each
 * resolver; mapping every SDL type to its `*Node` counterpart would require
 * matching every internal field 1:1 with the SDL output type, which is a
 * larger refactor than T7.1 warrants. Instead, the typed seam in
 * `resolvers/index.ts` constrains the merged map and the `*Args` imports
 * keep argument types in lockstep with the SDL.
 *
 * Run `pnpm --filter @shop-gym/shop-backend codegen` after any SDL change.
 * `pnpm --filter @shop-gym/shop-backend codegen:check` re-runs codegen and
 * fails CI if the working tree drifts from the committed output.
 */

import type { CodegenConfig } from '@graphql-codegen/cli';

const config: CodegenConfig = {
  overwrite: true,
  schema: 'src/schema.ts',
  generates: {
    'src/__generated__/resolvers-types.ts': {
      plugins: ['typescript', 'typescript-resolvers'],
      config: {
        contextType: '../resolvers/index.js#ResolverContext',
        useTypeImports: true,
        useIndexSignature: false,
        immutableTypes: true,
        enumsAsTypes: true,
        avoidOptionals: { field: true, inputValue: false, object: true },
        defaultScalarType: 'string',
        scalars: {
          ID: 'string',
          Boolean: 'boolean',
          Int: 'number',
          Float: 'number',
          String: 'string',
        },
      },
    },
  },
  hooks: {
    afterAllFileWrite: ['biome format --write --no-errors-on-unmatched'],
  },
};

export default config;
