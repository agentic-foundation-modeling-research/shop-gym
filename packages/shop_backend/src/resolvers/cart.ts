/**
 * In-memory cart store for a single SandboxShop instance.
 *
 * Implements the `CartStore` surface from
 * `docs/specs/shop_backend/storefront_api.md` §5.5 — a per-server `Map<cartId,
 * CartState>` plus the line-mutation methods used by the cart resolvers
 * (T4.2+). Replaces the module-level `Map` + `cartCounter` globals from the
 * mock-api reference so concurrent server instances (e.g. parallel tests)
 * stay isolated.
 *
 * GIDs follow the spec §5.3 / T4.1 convention `gid://shopify/Cart/cart-<n>`,
 * where `<n>` is the per-store creation counter. Cart line ids share that
 * scope (`gid://shopify/CartLine/cart-<n>-line-<m>`) so they remain readable
 * in tests and stable for the lifetime of one server.
 *
 * The state types are intentionally mutable: every method either appends to
 * or rewrites `cart.lines`, and resolvers materialize GraphQL nodes from this
 * raw state on demand. T4.2/T4.3 wire `CartStore` into `ResolverContext` and
 * add the `Query.cart` + `cartCreate`/`cartLines*` resolvers; T4.4 extends
 * the surface with the discount-code / buyer-identity / note / attribute /
 * gift-card mutations against fields added then.
 */

// ── Input shapes ───────────────────────────────────────────────────────────
// Hand-typed until graphql-codegen lands in M7 (T7.1). Mirrors the SDL
// `CartLineInput`, `CartLineUpdateInput`, and `CartInput` inputs scoped to
// the line-management surface owned by this milestone.

export interface AttributeInput {
  readonly key: string;
  readonly value: string;
}

export interface CartLineInput {
  readonly merchandiseId: string;
  readonly quantity?: number | null;
  readonly attributes?: readonly AttributeInput[] | null;
}

export interface CartLineUpdateInput {
  readonly id: string;
  readonly quantity?: number | null;
  readonly merchandiseId?: string | null;
  readonly attributes?: readonly AttributeInput[] | null;
}

export interface CartInput {
  readonly lines?: readonly CartLineInput[] | null;
}

// ── State shapes ──────────────────────────────────────────────────────────

/** Mutable cart-line record stored inside a `CartState`. */
export interface CartLineState {
  readonly id: string;
  merchandiseId: string;
  quantity: number;
  attributes: readonly AttributeInput[];
}

/** Mutable cart record held by the store. The `id` is immutable; `lines` is rewritten in place. */
export interface CartState {
  readonly id: string;
  lines: CartLineState[];
}

// ── Store ─────────────────────────────────────────────────────────────────

/**
 * Per-server in-memory cart store.
 *
 * `create` allocates a new cart with a deterministic GID; `get` returns the
 * stored instance (or `undefined` for unknown ids — spec §5.3); the
 * line-mutation methods operate in place on a cart returned by `create` /
 * `get`. `clear` resets the store (used on `server.close()` and in tests).
 */
export class CartStore {
  private readonly carts = new Map<string, CartState>();
  private cartCounter = 0;
  private readonly lineCounters = new Map<string, number>();

  /**
   * Allocate a new cart and register it under a fresh
   * `gid://shopify/Cart/cart-<n>` id. Initial `input.lines`, if any, are
   * inserted via `addLines` so duplicate `merchandiseId`s merge the same way
   * a follow-up `cartLinesAdd` would.
   */
  create(input?: CartInput | null): CartState {
    this.cartCounter += 1;
    const id = `gid://shopify/Cart/cart-${this.cartCounter}`;
    const cart: CartState = { id, lines: [] };
    this.carts.set(id, cart);
    this.lineCounters.set(id, 0);
    if (input?.lines !== undefined && input.lines !== null && input.lines.length > 0) {
      this.addLines(cart, input.lines);
    }
    return cart;
  }

  /** Look up a cart by id. Returns `undefined` for unknown ids. */
  get(id: string): CartState | undefined {
    return this.carts.get(id);
  }

  /**
   * Append lines to `cart`. Lines whose `merchandiseId` matches an existing
   * line have their quantity summed and (when supplied) attributes
   * overwritten — matching the mock-api / live Storefront semantics. New
   * lines receive the next deterministic line id.
   */
  addLines(cart: CartState, lines: readonly CartLineInput[]): void {
    for (const line of lines) {
      const quantity = line.quantity ?? 1;
      const existing = cart.lines.find((l) => l.merchandiseId === line.merchandiseId);
      if (existing !== undefined) {
        existing.quantity += quantity;
        if (line.attributes !== undefined && line.attributes !== null) {
          existing.attributes = [...line.attributes];
        }
        continue;
      }
      cart.lines.push({
        id: this.nextLineId(cart.id),
        merchandiseId: line.merchandiseId,
        quantity,
        attributes:
          line.attributes === undefined || line.attributes === null ? [] : [...line.attributes],
      });
    }
  }

  /**
   * Apply a batch of line updates. An update with `quantity <= 0` removes the
   * matching line (Shopify behavior, exercised by the T4.3 lifecycle test).
   * Other fields (`merchandiseId`, `attributes`) are overwritten when set.
   * Updates targeting unknown line ids are skipped silently.
   */
  updateLines(cart: CartState, updates: readonly CartLineUpdateInput[]): void {
    for (const update of updates) {
      const quantity = update.quantity ?? null;
      if (quantity !== null && quantity <= 0) {
        cart.lines = cart.lines.filter((l) => l.id !== update.id);
        continue;
      }
      const line = cart.lines.find((l) => l.id === update.id);
      if (line === undefined) continue;
      if (quantity !== null) {
        line.quantity = quantity;
      }
      if (update.merchandiseId !== undefined && update.merchandiseId !== null) {
        line.merchandiseId = update.merchandiseId;
      }
      if (update.attributes !== undefined && update.attributes !== null) {
        line.attributes = [...update.attributes];
      }
    }
  }

  /** Remove every line whose id appears in `lineIds`. Unknown ids are ignored. */
  removeLines(cart: CartState, lineIds: readonly string[]): void {
    if (lineIds.length === 0) return;
    const ids = new Set(lineIds);
    cart.lines = cart.lines.filter((l) => !ids.has(l.id));
  }

  /** Reset the store. Used by `server.close()` and in tests. */
  clear(): void {
    this.carts.clear();
    this.lineCounters.clear();
    this.cartCounter = 0;
  }

  private nextLineId(cartId: string): string {
    const next = (this.lineCounters.get(cartId) ?? 0) + 1;
    this.lineCounters.set(cartId, next);
    const cartSuffix = cartId.slice(cartId.lastIndexOf('/') + 1);
    return `gid://shopify/CartLine/${cartSuffix}-line-${next}`;
  }
}
