/**
 * In-memory cart store + `Query.cart` resolver for a single SandboxShop
 * instance.
 *
 * `CartStore` implements the surface from
 * `docs/specs/shop_backend/storefront_api.md` §5.5 — a per-server `Map<cartId,
 * CartState>` plus the line-mutation methods used by the cart resolvers.
 * Replaces the module-level `Map` + `cartCounter` globals from the mock-api
 * reference so concurrent server instances (e.g. parallel tests) stay
 * isolated.
 *
 * GIDs follow the spec §5.3 / T4.1 convention `gid://shopify/Cart/cart-<n>`,
 * where `<n>` is the per-store creation counter. Cart line ids share that
 * scope (`gid://shopify/CartLine/cart-<n>-line-<m>`) so they remain readable
 * in tests and stable for the lifetime of one server.
 *
 * The state types are intentionally mutable: every method either appends to
 * or rewrites `cart.lines`, and resolvers materialize GraphQL nodes from this
 * raw state on demand.
 *
 * `cartResolvers` (T4.2) handles the read half — `Query.cart(id)` looks up a
 * cart in the store, materializes its lines through `data.variantsByGid` so
 * each line resolves to a typed `ProductVariant` merchandise node, and
 * returns `null` for unknown ids (spec §5.3 — diverges from mock-api which
 * auto-creates). T4.3 adds the cart mutations on top of this surface; T4.4
 * extends it with discount-code / buyer-identity / note / attribute /
 * gift-card fields stored on the cart.
 */

import type { ProductVariant, SandboxShopData, VariantLookup } from '../data/types.js';
import {
  type MoneyV2Node,
  type ProductVariantNode,
  buildMoneyV2,
  buildProductVariantNode,
} from './builders.js';
import type { ResolverContext } from './index.js';

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

// ── Cart node shapes ──────────────────────────────────────────────────────
// Hand-typed parent shapes for the Cart area. Types from `@graphql-codegen`
// will replace these in M7 (T7.1).

export interface AttributeNode {
  readonly key: string;
  readonly value: string;
}

export interface CartCostNode {
  readonly subtotalAmount: MoneyV2Node;
  readonly totalAmount: MoneyV2Node;
  readonly totalTaxAmount: MoneyV2Node | null;
  readonly totalDutyAmount: MoneyV2Node | null;
}

export interface CartLineCostNode {
  readonly amountPerQuantity: MoneyV2Node;
  readonly compareAtAmountPerQuantity: MoneyV2Node | null;
  readonly totalAmount: MoneyV2Node;
  readonly subtotalAmount: MoneyV2Node;
}

export interface CartLineNode {
  readonly id: string;
  readonly quantity: number;
  readonly attributes: readonly AttributeNode[];
  readonly cost: CartLineCostNode;
  readonly merchandise: ProductVariantNode;
  readonly parentRelationship: null;
}

export interface CartLineConnectionNode {
  readonly nodes: readonly CartLineNode[];
  readonly edges: readonly { readonly node: CartLineNode }[];
}

export interface CartBuyerIdentityNode {
  readonly countryCode: string | null;
  readonly customer: null;
  readonly email: string | null;
  readonly phone: string | null;
}

export interface CartNode {
  readonly id: string;
  readonly checkoutUrl: string;
  readonly totalQuantity: number;
  readonly updatedAt: string;
  readonly cost: CartCostNode;
  readonly attributes: readonly AttributeNode[];
  readonly discountCodes: readonly { readonly code: string; readonly applicable: boolean }[];
  readonly appliedGiftCards: readonly never[];
  readonly buyerIdentity: CartBuyerIdentityNode;
  readonly note: string;
  /** Internal: materialized lines used by the `Cart.lines(first)` resolver. */
  readonly lineNodes: readonly CartLineNode[];
}

// ── Resolvers ─────────────────────────────────────────────────────────────

/**
 * Resolver map for the Cart area. Covers `Query.cart(id)` (T4.2) plus the
 * `BaseCartLine` / `Merchandise` union discriminators and the `Cart.lines`
 * connection field. The cart mutations (T4.3) and the discount-code /
 * buyer-identity / note / attribute / gift-card fields (T4.4) merge into
 * this map as they ship.
 */
export const cartResolvers = {
  Query: {
    cart: (
      _parent: unknown,
      args: { readonly id: string },
      ctx: ResolverContext,
    ): CartNode | null => {
      const state = ctx.carts.get(args.id);
      if (state === undefined) return null;
      return buildCartNode(state, ctx.data, ctx.baseUrl);
    },
  },

  Cart: {
    lines: (parent: CartNode, args: { readonly first?: number | null }): CartLineConnectionNode => {
      const all = parent.lineNodes;
      const first = args.first ?? null;
      const slice = first === null || first < 0 ? all : all.slice(0, Math.min(first, all.length));
      return {
        nodes: slice,
        edges: slice.map((node) => ({ node })),
      };
    },
  },

  BaseCartLine: {
    __resolveType: (): 'CartLine' => 'CartLine',
  },

  Merchandise: {
    __resolveType: (): 'ProductVariant' => 'ProductVariant',
  },
};

// ── Cart materialization ──────────────────────────────────────────────────

/**
 * Materialize a `CartState` into the `CartNode` shape consumed by the
 * GraphQL Cart type. Each stored line is resolved against
 * `data.variantsByGid` so the `merchandise` field carries a fully-populated
 * `ProductVariant` node. Lines whose `merchandiseId` is no longer in the
 * dataset (e.g. seeded with a fake id) are skipped — they are invisible to
 * the schema rather than 500-ing the query.
 *
 * `updatedAt` reflects materialization time. Per-cart timestamp tracking
 * lands with the mutations + extra-field milestones (T4.3 / T4.4); v0.1
 * Cart consumers that read `updatedAt` get the resolution timestamp.
 */
function buildCartNode(state: CartState, data: SandboxShopData, baseUrl: string): CartNode {
  const lineNodes = materializeLines(state, data, baseUrl);
  const totalQuantity = lineNodes.reduce((sum, line) => sum + line.quantity, 0);
  const subtotalCents = lineNodes.reduce(
    (sum, line) => sum + parsePriceCents(line.merchandise.price.amount) * line.quantity,
    0,
  );
  const subtotal = buildMoneyV2(centsToAmount(subtotalCents), data.store.currency_code);
  return {
    id: state.id,
    checkoutUrl: '#',
    totalQuantity,
    updatedAt: new Date().toISOString(),
    cost: {
      subtotalAmount: subtotal,
      totalAmount: subtotal,
      totalTaxAmount: null,
      totalDutyAmount: null,
    },
    attributes: [],
    discountCodes: [],
    appliedGiftCards: [],
    buyerIdentity: { countryCode: null, customer: null, email: null, phone: null },
    note: '',
    lineNodes,
  };
}

function materializeLines(
  state: CartState,
  data: SandboxShopData,
  baseUrl: string,
): readonly CartLineNode[] {
  const nodes: CartLineNode[] = [];
  for (const line of state.lines) {
    const lookup = data.variantsByGid.get(line.merchandiseId);
    if (lookup === undefined) continue;
    nodes.push(buildCartLineNode(line, lookup, data, baseUrl));
  }
  return nodes;
}

function buildCartLineNode(
  line: CartLineState,
  lookup: VariantLookup,
  data: SandboxShopData,
  baseUrl: string,
): CartLineNode {
  const merchandise = buildProductVariantNode(lookup.product, lookup.variant, data.store, baseUrl);
  return {
    id: line.id,
    quantity: line.quantity,
    attributes: line.attributes.map((a) => ({ key: a.key, value: a.value })),
    cost: buildCartLineCost(merchandise.price, lookup.variant, line.quantity, data),
    merchandise,
    parentRelationship: null,
  };
}

function buildCartLineCost(
  price: MoneyV2Node,
  variant: ProductVariant,
  quantity: number,
  data: SandboxShopData,
): CartLineCostNode {
  const lineTotalCents = parsePriceCents(price.amount) * quantity;
  const totalAmount = buildMoneyV2(centsToAmount(lineTotalCents), data.store.currency_code);
  return {
    amountPerQuantity: price,
    compareAtAmountPerQuantity:
      variant.compare_at_price === null
        ? null
        : buildMoneyV2(variant.compare_at_price, data.store.currency_code),
    totalAmount,
    subtotalAmount: totalAmount,
  };
}

/** Parse a fixed-decimal money string (e.g. "12.99") into integer cents. */
function parsePriceCents(amount: string): number {
  const value = Number.parseFloat(amount);
  if (!Number.isFinite(value)) return 0;
  return Math.round(value * 100);
}

function centsToAmount(cents: number): string {
  return (cents / 100).toFixed(2);
}
