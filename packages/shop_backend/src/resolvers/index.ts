/**
 * Resolver-layer entry point. Exposes the typed `ResolverContext` shared by
 * every resolver module under this directory; T2.6 will additionally combine
 * the per-area resolver maps (`shop`, `product`, `cart`, ...) and re-export
 * the union from here.
 */

import type { SandboxShopData } from '../data/types.js';

/**
 * Per-request context passed to every resolver. `data` is the loaded dataset
 * snapshot; `baseUrl` is the public origin (e.g. `https://shop.example`) used
 * when rewriting relative image paths into absolute URLs (see spec §5.3).
 *
 * The cart store is intentionally absent at this milestone; it lands with the
 * cart resolvers in M4.
 */
export interface ResolverContext {
  readonly data: SandboxShopData;
  readonly baseUrl: string;
}
