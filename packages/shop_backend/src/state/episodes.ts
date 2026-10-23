/**
 * Registry of per-episode `ShopState` branches inside one server process.
 *
 * Episodes are created lazily on first use by forking the base state, so a
 * request carrying a new `x-shopgym-episode` id always finds a fresh, fully
 * seeded shop. The `default` episode is the one requests without the header
 * use; it is the only episode whose carts may be file-backed.
 */

import type { SandboxShopData } from '../data/types.js';
import { ShopState, type ShopStateOptions } from './shop_state.js';

/** Episode selected when a request carries no `x-shopgym-episode` header. */
export const DEFAULT_EPISODE_ID = 'default';

export class EpisodeStore {
  private readonly episodes = new Map<string, ShopState>();
  private readonly data: SandboxShopData;
  private readonly options: ShopStateOptions;

  constructor(data: SandboxShopData, options: ShopStateOptions = {}) {
    this.data = data;
    this.options = options;
  }

  /** Episode state for `id`, forked from the base dataset on first use. */
  get(id: string): ShopState {
    const existing = this.episodes.get(id);
    if (existing !== undefined) return existing;
    const created = this.create(id);
    this.episodes.set(id, created);
    return created;
  }

  /** Whether `id` has been materialized by a request or a reset. */
  has(id: string): boolean {
    return this.episodes.has(id);
  }

  /** Discard `id` and re-seed it. Also wipes a file-backed cart store. */
  reset(id: string): ShopState {
    const fresh = this.create(id);
    fresh.carts.purge();
    this.episodes.set(id, fresh);
    return fresh;
  }

  /** Forget `id`. Returns whether it existed. The next `get` re-seeds it. */
  delete(id: string): boolean {
    return this.episodes.delete(id);
  }

  /** Drop every episode without touching persistence files. */
  clear(): void {
    this.episodes.clear();
  }

  private create(id: string): ShopState {
    if (id === DEFAULT_EPISODE_ID) return new ShopState(this.data, id, this.options);
    const { cartStorePath: _ignored, ...rest } = this.options;
    return new ShopState(this.data, id, rest);
  }
}
