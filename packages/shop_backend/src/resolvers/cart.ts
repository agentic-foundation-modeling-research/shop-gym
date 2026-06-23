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
 * auto-creates). T4.3 adds the four line-management mutations
 * (`cartCreate`, `cartLinesAdd`, `cartLinesUpdate`, `cartLinesRemove`) on
 * top of the same store; each one looks up (or allocates) a cart, mutates
 * it via the `CartStore` line methods, and returns the freshly materialized
 * cart in a `CartCreatePayload`/`CartLines*Payload`-shaped envelope. T4.4
 * extends the surface with discount-code / buyer-identity / note /
 * attribute / gift-card fields stored on the cart.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

import type {
  AttributeInput,
  CartBuyerIdentityInput,
  CartInput,
  CartLineInput,
  CartLineUpdateInput,
  MutationCartAttributesUpdateArgs,
  MutationCartBuyerIdentityUpdateArgs,
  MutationCartCreateArgs,
  MutationCartDiscountCodesUpdateArgs,
  MutationCartGiftCardCodesAddArgs,
  MutationCartGiftCardCodesRemoveArgs,
  MutationCartGiftCardCodesUpdateArgs,
  MutationCartLinesAddArgs,
  MutationCartLinesRemoveArgs,
  MutationCartLinesUpdateArgs,
  MutationCartNoteUpdateArgs,
  QueryCartArgs,
} from '../__generated__/resolvers-types.js';
import type { ProductVariant, SandboxShopData, VariantLookup } from '../data/types.js';
import {
  type MoneyV2Node,
  type ProductVariantNode,
  buildMoneyV2,
  buildProductVariantNode,
  gid,
} from './builders.js';
import type { ResolverContext } from './index.js';

// Re-export the SDL-derived input types so callers in the codebase keep
// importing them from `cart.ts` without reaching into the generated module.
export type {
  AttributeInput,
  CartBuyerIdentityInput,
  CartInput,
  CartLineInput,
  CartLineUpdateInput,
} from '../__generated__/resolvers-types.js';

// ── State shapes ──────────────────────────────────────────────────────────

/** Mutable cart-line record stored inside a `CartState`. */
export interface CartLineState {
  readonly id: string;
  merchandiseId: string;
  quantity: number;
  attributes: readonly AttributeInput[];
}

/** Buyer-identity slot held on a `CartState`. `customer` always resolves to null in v0.1. */
export interface CartBuyerIdentityState {
  countryCode: string | null;
  email: string | null;
  phone: string | null;
}

/** Mutable cart record held by the store. The `id` is immutable; the rest is rewritten in place. */
export interface CartState {
  readonly id: string;
  lines: CartLineState[];
  discountCodes: string[];
  giftCardCodes: string[];
  buyerIdentity: CartBuyerIdentityState;
  note: string;
  attributes: AttributeInput[];
}

// ── Store ─────────────────────────────────────────────────────────────────

/** Construction-time options for `CartStore`. */
export interface CartStoreOptions {
  /**
   * File path to back the store with. When set, the constructor rehydrates
   * from the file (if present) and every mutation writes the full snapshot
   * back synchronously (T7.4). Omit for the default in-memory-only store.
   */
  readonly persistencePath?: string;
}

/** Wire format written to `persistencePath`. Bumped if the layout ever changes. */
const PERSISTENCE_VERSION = 1;

interface CartStoreSnapshot {
  readonly version: number;
  readonly cartCounter: number;
  readonly lineCounters: Readonly<Record<string, number>>;
  readonly carts: Readonly<Record<string, CartState>>;
}

/** Thrown when `persistencePath` exists but cannot be parsed as a valid snapshot. */
export class InvalidCartStoreFileError extends Error {
  readonly fullPath: string;
  readonly reason: string;

  constructor(fullPath: string, reason: string) {
    super(`Invalid cart store file at ${fullPath}: ${reason}`);
    this.name = 'InvalidCartStoreFileError';
    this.fullPath = fullPath;
    this.reason = reason;
  }
}

/**
 * Per-server cart store.
 *
 * `create` allocates a new cart with a deterministic GID; `get` returns the
 * stored instance (or `undefined` for unknown ids — spec §5.3); the
 * line-mutation methods operate in place on a cart returned by `create` /
 * `get`. `clear` resets in-memory state (used on `server.close()` and in
 * tests).
 *
 * When constructed with `persistencePath`, the store rehydrates from that
 * file at construction time and writes the full snapshot back after every
 * mutation (T7.4). The persistence file is the source of truth across
 * process restarts; `clear()` does not touch it so a fresh `CartStore`
 * pointed at the same path continues to see prior carts.
 */
export class CartStore {
  private readonly carts = new Map<string, CartState>();
  private cartCounter = 0;
  private readonly lineCounters = new Map<string, number>();
  private readonly persistencePath: string | undefined;

  constructor(options?: CartStoreOptions) {
    this.persistencePath = options?.persistencePath;
    if (this.persistencePath !== undefined && fs.existsSync(this.persistencePath)) {
      this.loadSnapshot(this.persistencePath);
    }
  }

  /**
   * Allocate a new cart and register it under a fresh
   * `gid://shopify/Cart/cart-<n>` id. Initial `input.lines`, if any, are
   * inserted via `addLines` so duplicate `merchandiseId`s merge the same way
   * a follow-up `cartLinesAdd` would. Other `CartInput` fields
   * (`discountCodes`, `attributes`, `note`, `buyerIdentity`) are stored
   * verbatim so a follow-up `Query.cart(id)` reflects them.
   */
  create(input?: CartInput | null): CartState {
    this.cartCounter += 1;
    const id = `gid://shopify/Cart/cart-${this.cartCounter}`;
    const cart: CartState = {
      id,
      lines: [],
      discountCodes: [],
      giftCardCodes: [],
      buyerIdentity: { countryCode: null, email: null, phone: null },
      note: '',
      attributes: [],
    };
    this.carts.set(id, cart);
    this.lineCounters.set(id, 0);
    if (input?.lines !== undefined && input.lines !== null && input.lines.length > 0) {
      this.addLines(cart, input.lines);
    }
    if (input?.discountCodes !== undefined && input.discountCodes !== null) {
      this.setDiscountCodes(cart, input.discountCodes);
    }
    if (input?.giftCardCodes !== undefined && input.giftCardCodes !== null) {
      this.setGiftCardCodes(cart, input.giftCardCodes);
    }
    if (input?.attributes !== undefined && input.attributes !== null) {
      this.setAttributes(cart, input.attributes);
    }
    if (input?.note !== undefined && input.note !== null) {
      this.setNote(cart, input.note);
    }
    if (input?.buyerIdentity !== undefined && input.buyerIdentity !== null) {
      this.setBuyerIdentity(cart, input.buyerIdentity);
    }
    this.persist();
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
    this.persist();
  }

  /**
   * Apply a batch of line updates. An update with `quantity <= 0` removes the
   * matching line.
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
    this.persist();
  }

  /** Remove every line whose id appears in `lineIds`. Unknown ids are ignored. */
  removeLines(cart: CartState, lineIds: readonly string[]): void {
    if (lineIds.length === 0) return;
    const ids = new Set(lineIds);
    cart.lines = cart.lines.filter((l) => !ids.has(l.id));
    this.persist();
  }

  /**
   * Replace the cart's discount codes. v0.1 performs no validation — every
   * code is stored as-is and reported `applicable: true` by the resolver.
   * Passing `null` clears the list.
   */
  setDiscountCodes(cart: CartState, codes: readonly string[] | null): void {
    cart.discountCodes = codes === null ? [] : [...codes];
    this.persist();
  }

  /**
   * Replace the cart's applied gift-card codes. v0.1 performs no validation —
   * codes are stored as-is and rendered as `AppliedGiftCard` nodes (id,
   * lastCharacters, no `amountUsed`).
   */
  setGiftCardCodes(cart: CartState, codes: readonly string[]): void {
    cart.giftCardCodes = [...codes];
    this.persist();
  }

  /** Append new gift-card codes, preserving existing codes and skipping duplicates. */
  addGiftCardCodes(cart: CartState, codes: readonly string[]): void {
    for (const code of codes) {
      if (!cart.giftCardCodes.includes(code)) {
        cart.giftCardCodes.push(code);
      }
    }
    this.persist();
  }

  /** Remove applied gift cards by their Storefront API AppliedGiftCard IDs. */
  removeGiftCardCodes(cart: CartState, appliedGiftCardIds: readonly string[]): void {
    if (appliedGiftCardIds.length === 0) return;
    const ids = new Set(appliedGiftCardIds);
    cart.giftCardCodes = cart.giftCardCodes.filter(
      (code) => !ids.has(gid('AppliedGiftCard', code)),
    );
    this.persist();
  }

  /**
   * Merge a buyer-identity update into the cart. Fields explicitly set to
   * `null` in the input clear the corresponding stored value; omitted /
   * `undefined` fields are left untouched (matches the Storefront API's
   * partial-update semantics). `customerAccessToken` is accepted but ignored
   * — v0.1 has no real customer auth.
   */
  setBuyerIdentity(cart: CartState, identity: CartBuyerIdentityInput): void {
    if (identity.countryCode !== undefined) cart.buyerIdentity.countryCode = identity.countryCode;
    if (identity.email !== undefined) cart.buyerIdentity.email = identity.email;
    if (identity.phone !== undefined) cart.buyerIdentity.phone = identity.phone;
    this.persist();
  }

  /** Replace the cart's free-form note. */
  setNote(cart: CartState, note: string): void {
    cart.note = note;
    this.persist();
  }

  /** Replace the cart's custom attributes. */
  setAttributes(cart: CartState, attributes: readonly AttributeInput[]): void {
    cart.attributes = attributes.map((a) => ({ key: a.key, value: a.value }));
    this.persist();
  }

  /**
   * Reset in-memory state. The persistence file (if configured) is left in
   * place so a fresh `CartStore` pointed at the same path continues to see
   * prior carts — this is what makes T7.4 cross-process persistence work.
   */
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

  /**
   * Write the full store snapshot to `persistencePath` synchronously. No-op
   * when persistence is disabled. Writes the parent directory on first use
   * so callers can point at a path under a fresh outputs/ subtree without
   * pre-creating it.
   */
  private persist(): void {
    if (this.persistencePath === undefined) return;
    const snapshot: CartStoreSnapshot = {
      version: PERSISTENCE_VERSION,
      cartCounter: this.cartCounter,
      lineCounters: Object.fromEntries(this.lineCounters),
      carts: Object.fromEntries(this.carts),
    };
    fs.mkdirSync(path.dirname(this.persistencePath), { recursive: true });
    fs.writeFileSync(this.persistencePath, JSON.stringify(snapshot, null, 2));
  }

  /**
   * Rehydrate state from a previously-written snapshot. Throws
   * `InvalidCartStoreFileError` for malformed JSON or shape mismatches —
   * callers can recover by deleting the file before re-creating the store.
   */
  private loadSnapshot(filePath: string): void {
    let raw: string;
    try {
      raw = fs.readFileSync(filePath, 'utf-8');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      throw new InvalidCartStoreFileError(filePath, `read failed: ${message}`);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw) as unknown;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      throw new InvalidCartStoreFileError(filePath, `JSON parse error: ${message}`);
    }
    const snapshot = parseSnapshot(filePath, parsed);
    this.cartCounter = snapshot.cartCounter;
    for (const [cartId, count] of Object.entries(snapshot.lineCounters)) {
      this.lineCounters.set(cartId, count);
    }
    for (const [cartId, cart] of Object.entries(snapshot.carts)) {
      this.carts.set(cartId, cart);
    }
  }
}

// ── Snapshot validation ───────────────────────────────────────────────────

function parseSnapshot(filePath: string, raw: unknown): CartStoreSnapshot {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new InvalidCartStoreFileError(filePath, 'expected snapshot object at root');
  }
  const obj = raw as Record<string, unknown>;
  const version = obj.version;
  if (version !== PERSISTENCE_VERSION) {
    throw new InvalidCartStoreFileError(
      filePath,
      `unsupported snapshot version (got ${typeof version === 'number' ? String(version) : typeof version}, expected ${PERSISTENCE_VERSION})`,
    );
  }
  if (typeof obj.cartCounter !== 'number' || !Number.isInteger(obj.cartCounter)) {
    throw new InvalidCartStoreFileError(filePath, 'cartCounter must be an integer');
  }
  if (typeof obj.lineCounters !== 'object' || obj.lineCounters === null) {
    throw new InvalidCartStoreFileError(filePath, 'lineCounters must be an object');
  }
  if (typeof obj.carts !== 'object' || obj.carts === null) {
    throw new InvalidCartStoreFileError(filePath, 'carts must be an object');
  }
  const lineCounters: Record<string, number> = {};
  for (const [key, value] of Object.entries(obj.lineCounters as Record<string, unknown>)) {
    if (typeof value !== 'number' || !Number.isInteger(value)) {
      throw new InvalidCartStoreFileError(filePath, `lineCounters.${key} must be an integer`);
    }
    lineCounters[key] = value;
  }
  const carts: Record<string, CartState> = {};
  for (const [cartId, value] of Object.entries(obj.carts as Record<string, unknown>)) {
    carts[cartId] = parseCartState(filePath, cartId, value);
  }
  return { version, cartCounter: obj.cartCounter, lineCounters, carts };
}

function parseCartState(filePath: string, cartId: string, raw: unknown): CartState {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new InvalidCartStoreFileError(filePath, `carts.${cartId} must be an object`);
  }
  const obj = raw as Record<string, unknown>;
  if (obj.id !== cartId) {
    throw new InvalidCartStoreFileError(
      filePath,
      `carts.${cartId}.id must match the map key (got ${typeof obj.id === 'string' ? obj.id : typeof obj.id})`,
    );
  }
  if (typeof obj.note !== 'string') {
    throw new InvalidCartStoreFileError(filePath, `carts.${cartId}.note must be a string`);
  }
  return {
    id: cartId,
    lines: parseLines(filePath, cartId, obj.lines),
    discountCodes: parseStringArray(filePath, `carts.${cartId}.discountCodes`, obj.discountCodes),
    giftCardCodes: parseStringArray(filePath, `carts.${cartId}.giftCardCodes`, obj.giftCardCodes),
    buyerIdentity: parseBuyerIdentity(filePath, cartId, obj.buyerIdentity),
    note: obj.note,
    attributes: parseAttributes(filePath, `carts.${cartId}.attributes`, obj.attributes),
  };
}

function parseLines(filePath: string, cartId: string, raw: unknown): CartLineState[] {
  if (!Array.isArray(raw)) {
    throw new InvalidCartStoreFileError(filePath, `carts.${cartId}.lines must be an array`);
  }
  return raw.map((entry, i) => {
    const ctx = `carts.${cartId}.lines[${i}]`;
    if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
      throw new InvalidCartStoreFileError(filePath, `${ctx} must be an object`);
    }
    const obj = entry as Record<string, unknown>;
    if (typeof obj.id !== 'string') {
      throw new InvalidCartStoreFileError(filePath, `${ctx}.id must be a string`);
    }
    if (typeof obj.merchandiseId !== 'string') {
      throw new InvalidCartStoreFileError(filePath, `${ctx}.merchandiseId must be a string`);
    }
    if (typeof obj.quantity !== 'number' || !Number.isInteger(obj.quantity)) {
      throw new InvalidCartStoreFileError(filePath, `${ctx}.quantity must be an integer`);
    }
    return {
      id: obj.id,
      merchandiseId: obj.merchandiseId,
      quantity: obj.quantity,
      attributes: parseAttributes(filePath, `${ctx}.attributes`, obj.attributes),
    };
  });
}

function parseAttributes(filePath: string, ctx: string, raw: unknown): AttributeInput[] {
  if (!Array.isArray(raw)) {
    throw new InvalidCartStoreFileError(filePath, `${ctx} must be an array`);
  }
  return raw.map((entry, i) => {
    if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) {
      throw new InvalidCartStoreFileError(filePath, `${ctx}[${i}] must be an object`);
    }
    const obj = entry as Record<string, unknown>;
    if (typeof obj.key !== 'string' || typeof obj.value !== 'string') {
      throw new InvalidCartStoreFileError(
        filePath,
        `${ctx}[${i}] must have string 'key' and 'value'`,
      );
    }
    return { key: obj.key, value: obj.value };
  });
}

function parseStringArray(filePath: string, ctx: string, raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    throw new InvalidCartStoreFileError(filePath, `${ctx} must be an array`);
  }
  return raw.map((entry, i) => {
    if (typeof entry !== 'string') {
      throw new InvalidCartStoreFileError(filePath, `${ctx}[${i}] must be a string`);
    }
    return entry;
  });
}

function parseBuyerIdentity(
  filePath: string,
  cartId: string,
  raw: unknown,
): CartBuyerIdentityState {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new InvalidCartStoreFileError(
      filePath,
      `carts.${cartId}.buyerIdentity must be an object`,
    );
  }
  const obj = raw as Record<string, unknown>;
  return {
    countryCode: parseStringOrNull(
      filePath,
      `carts.${cartId}.buyerIdentity.countryCode`,
      obj.countryCode,
    ),
    email: parseStringOrNull(filePath, `carts.${cartId}.buyerIdentity.email`, obj.email),
    phone: parseStringOrNull(filePath, `carts.${cartId}.buyerIdentity.phone`, obj.phone),
  };
}

function parseStringOrNull(filePath: string, ctx: string, raw: unknown): string | null {
  if (raw === null) return null;
  if (typeof raw !== 'string') {
    throw new InvalidCartStoreFileError(filePath, `${ctx} must be a string or null`);
  }
  return raw;
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

export interface CartDiscountCodeNode {
  readonly code: string;
  readonly applicable: boolean;
}

export interface AppliedGiftCardNode {
  readonly id: string;
  readonly lastCharacters: string | null;
  readonly amountUsed: MoneyV2Node | null;
}

export interface CartNode {
  readonly id: string;
  readonly checkoutUrl: string;
  readonly totalQuantity: number;
  readonly updatedAt: string;
  readonly cost: CartCostNode;
  readonly attributes: readonly AttributeNode[];
  readonly discountCodes: readonly CartDiscountCodeNode[];
  readonly appliedGiftCards: readonly AppliedGiftCardNode[];
  readonly buyerIdentity: CartBuyerIdentityNode;
  readonly note: string;
  /** Internal: materialized lines used by the `Cart.lines(first)` resolver. */
  readonly lineNodes: readonly CartLineNode[];
}

// ── Mutation payload shapes ───────────────────────────────────────────────

/**
 * One entry in the `userErrors` array on every cart-mutation payload. The SDL
 * permits `code` and `field` to be null (e.g. when the error is not bound to
 * a specific input field); `message` is always present.
 */
export interface CartUserErrorNode {
  readonly code: string | null;
  readonly field: readonly string[] | null;
  readonly message: string;
}

/** One entry in the `warnings` array. v0.1 never emits warnings. */
export interface CartWarningNode {
  readonly code: string;
  readonly message: string;
  readonly target: string | null;
}

/**
 * Shared payload shape for every cart mutation. The SDL declares one named
 * payload type per mutation (`CartCreatePayload`, `CartLinesAddPayload`, ...)
 * but they are structurally identical; resolvers all produce this shape.
 */
export interface CartMutationPayloadNode {
  readonly cart: CartNode | null;
  readonly userErrors: readonly CartUserErrorNode[];
  readonly warnings: readonly CartWarningNode[];
}

// ── Resolvers ─────────────────────────────────────────────────────────────

/**
 * Resolver map for the Cart area. Covers `Query.cart(id)` (T4.2), the four
 * line-management mutations (`cartCreate`, `cartLinesAdd`, `cartLinesUpdate`,
 * `cartLinesRemove`, T4.3), the discount-code / buyer-identity / note /
 * attribute / gift-card mutations (T4.4), plus the `BaseCartLine` /
 * `Merchandise` union discriminators and the `Cart.lines` connection field.
 */
export const cartResolvers = {
  Query: {
    cart: (_parent: unknown, args: QueryCartArgs, ctx: ResolverContext): CartNode | null => {
      const state = ctx.carts.get(args.id);
      if (state === undefined) return null;
      return buildCartNode(state, ctx.data, ctx.baseUrl);
    },
  },

  Mutation: {
    cartCreate: (
      _parent: unknown,
      args: MutationCartCreateArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.create(args.input);
      return successPayload(state, ctx);
    },

    cartLinesAdd: (
      _parent: unknown,
      args: MutationCartLinesAddArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      // Stale cartId (e.g. client cookie outlived an in-memory store): bootstrap
      // a fresh cart with the requested lines so the client can refresh its id
      // from the response.
      const existing = ctx.carts.get(args.cartId);
      if (existing === undefined) {
        return successPayload(ctx.carts.create({ lines: args.lines }), ctx);
      }
      ctx.carts.addLines(existing, args.lines);
      return successPayload(existing, ctx);
    },

    cartLinesUpdate: (
      _parent: unknown,
      args: MutationCartLinesUpdateArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.updateLines(state, args.lines);
      return successPayload(state, ctx);
    },

    cartLinesRemove: (
      _parent: unknown,
      args: MutationCartLinesRemoveArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.removeLines(state, args.lineIds);
      return successPayload(state, ctx);
    },

    cartDiscountCodesUpdate: (
      _parent: unknown,
      args: MutationCartDiscountCodesUpdateArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.setDiscountCodes(state, args.discountCodes ?? null);
      return successPayload(state, ctx);
    },

    cartBuyerIdentityUpdate: (
      _parent: unknown,
      args: MutationCartBuyerIdentityUpdateArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.setBuyerIdentity(state, args.buyerIdentity);
      return successPayload(state, ctx);
    },

    cartNoteUpdate: (
      _parent: unknown,
      args: MutationCartNoteUpdateArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.setNote(state, args.note);
      return successPayload(state, ctx);
    },

    cartAttributesUpdate: (
      _parent: unknown,
      args: MutationCartAttributesUpdateArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.setAttributes(state, args.attributes);
      return successPayload(state, ctx);
    },

    cartGiftCardCodesUpdate: (
      _parent: unknown,
      args: MutationCartGiftCardCodesUpdateArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.setGiftCardCodes(state, args.giftCardCodes);
      return successPayload(state, ctx);
    },

    cartGiftCardCodesAdd: (
      _parent: unknown,
      args: MutationCartGiftCardCodesAddArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.addGiftCardCodes(state, args.giftCardCodes);
      return successPayload(state, ctx);
    },

    cartGiftCardCodesRemove: (
      _parent: unknown,
      args: MutationCartGiftCardCodesRemoveArgs,
      ctx: ResolverContext,
    ): CartMutationPayloadNode => {
      const state = ctx.carts.get(args.cartId);
      if (state === undefined) return cartNotFoundPayload();
      ctx.carts.removeGiftCardCodes(state, args.appliedGiftCardIds);
      return successPayload(state, ctx);
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

// ── Mutation payload helpers ──────────────────────────────────────────────

function successPayload(state: CartState, ctx: ResolverContext): CartMutationPayloadNode {
  return {
    cart: buildCartNode(state, ctx.data, ctx.baseUrl),
    userErrors: [],
    warnings: [],
  };
}

/**
 * Payload returned by `cartLinesAdd` / `cartLinesUpdate` / `cartLinesRemove`
 * when `cartId` does not match a cart in the store.
 */
function cartNotFoundPayload(): CartMutationPayloadNode {
  return {
    cart: null,
    userErrors: [{ code: 'INVALID', field: ['cartId'], message: 'Cart not found' }],
    warnings: [],
  };
}

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
    attributes: state.attributes.map((a) => ({ key: a.key, value: a.value })),
    discountCodes: state.discountCodes.map((code) => ({ code, applicable: true })),
    appliedGiftCards: state.giftCardCodes.map(buildAppliedGiftCardNode),
    buyerIdentity: {
      countryCode: state.buyerIdentity.countryCode,
      customer: null,
      email: state.buyerIdentity.email,
      phone: state.buyerIdentity.phone,
    },
    note: state.note,
    lineNodes,
  };
}

/**
 * Materialize a stored gift-card code into an `AppliedGiftCard` node. v0.1
 * performs no real validation, so `amountUsed` is always null and
 * `lastCharacters` is the last four characters of the code (or the whole
 * code if shorter). The id is a deterministic GID hashed from the code so
 * the same value yields the same id across server restarts.
 */
function buildAppliedGiftCardNode(code: string): AppliedGiftCardNode {
  return {
    id: gid('AppliedGiftCard', code),
    lastCharacters: code.length === 0 ? null : code.slice(-4),
    amountUsed: null,
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
  const merchandise = buildProductVariantNode(
    lookup.product,
    lookup.variant,
    data.store,
    baseUrl,
    data.inventoryByVariantId,
  );
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
