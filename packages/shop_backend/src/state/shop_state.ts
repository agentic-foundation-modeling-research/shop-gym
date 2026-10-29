/**
 * Mutable per-episode shop state layered over the immutable loaded dataset.
 *
 * One `ShopState` holds everything a shopping session can change: carts,
 * customer accounts and their access-token sessions, orders, and per-variant
 * inventory. It is seeded from `customers.json`, `orders.json`, and
 * `inventory.json` and never touches the dataset it was built from, so any
 * number of episodes can be forked from one `SandboxShopData`.
 *
 * Determinism: ids come from sequential counters and timestamps from an
 * `EpisodeClock` that advances one second per mutation, so the same action
 * sequence always yields the same ids, tokens, and timestamps.
 *
 * `data` is the episode's view of the dataset: identical to the base except
 * that `inventoryByVariantId` is the live, mutable inventory map. Resolvers
 * read availability through it and see checkout decrements immediately.
 */

import type {
  Address,
  Commerce,
  InventoryEntry,
  OrderFinancialStatus,
  OrderFulfillmentStatus,
  PaymentMethod,
  SandboxShopData,
  ShippingMethod,
} from '../data/types.js';
import { type CartState, CartStore } from '../resolvers/cart.js';
import { EpisodeClock } from './episode_clock.js';
import { computeOrderTotals, priceDiscountCode, subtotalCents } from './pricing.js';

// ── Records ────────────────────────────────────────────────────────────────

/** Postal address held on a customer or an order. */
export interface AddressRecord {
  readonly id: number;
  readonly firstName: string | null;
  readonly lastName: string | null;
  readonly company: string | null;
  readonly address1: string;
  readonly address2: string | null;
  readonly city: string;
  readonly province: string | null;
  readonly provinceCode: string | null;
  readonly country: string;
  readonly countryCode: string;
  readonly zip: string;
  readonly phone: string | null;
}

/** Address fields supplied by a client before an id is allocated. */
export type NewAddress = Omit<AddressRecord, 'id'>;

/**
 * Fields that an address book edit can change; absent fields keep their
 * value. The codes are not editable: the sandbox ships to one country and
 * has no list of provinces.
 */
export type AddressChanges = Partial<Omit<NewAddress, 'provinceCode' | 'countryCode'>>;

/** Customer account. Mutable fields are rewritten in place by state methods. */
export interface CustomerRecord {
  readonly id: number;
  readonly email: string;
  readonly password: string;
  readonly firstName: string | null;
  readonly lastName: string | null;
  readonly phone: string | null;
  readonly acceptsMarketing: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly addresses: readonly AddressRecord[];
  readonly defaultAddressId: number | null;
}

/** Fields accepted by `createCustomer`. */
export interface NewCustomer {
  readonly email: string;
  readonly password: string;
  readonly firstName: string | null;
  readonly lastName: string | null;
  readonly phone: string | null;
  readonly acceptsMarketing: boolean;
}

/** A live customer access token. */
export interface SessionRecord {
  readonly accessToken: string;
  readonly customerId: number;
  readonly expiresAt: string;
}

export interface OrderLineItemRecord {
  readonly variantId: number;
  readonly title: string;
  readonly quantity: number;
  /** Unit price at order time, decimal string. */
  readonly price: string;
}

export interface OrderRecord {
  /** Also the order number shown as `#<id>`. */
  readonly id: number;
  readonly customerId: number | null;
  readonly email: string | null;
  readonly processedAt: string;
  readonly financialStatus: OrderFinancialStatus;
  readonly fulfillmentStatus: OrderFulfillmentStatus;
  readonly currencyCode: string;
  readonly lineItems: readonly OrderLineItemRecord[];
  readonly shippingAddress: AddressRecord | null;
  readonly shippingMethod: string | null;
  readonly paymentMethod: string | null;
  /** Merchandise subtotal before the discount. */
  readonly subtotalPrice: string;
  readonly totalShippingPrice: string;
  readonly totalTax: string;
  readonly totalPrice: string;
  /** Discount code applied at checkout, or `null`. */
  readonly discountCode: string | null;
  /** Merchandise discount, or the shipping charge waived by a free-shipping code. */
  readonly discountAmount: string;
}

/** Inventory entry whose live quantity differs from the loaded dataset. */
export interface InventoryDelta {
  readonly variantId: number;
  readonly baseQuantityAvailable: number | null;
  readonly quantityAvailable: number | null;
}

// ── Checkout ───────────────────────────────────────────────────────────────

export interface PlaceOrderInput {
  readonly cart: CartState;
  readonly email: string | null;
  readonly shippingAddress: NewAddress;
  readonly shippingMethod: ShippingMethod;
  readonly paymentMethod: PaymentMethod;
}

/** One line that could not be fulfilled from episode inventory. */
export interface StockShortfall {
  readonly merchandiseId: string;
  readonly requested: number;
  readonly available: number;
}

export type PlaceOrderResult =
  | { readonly ok: true; readonly order: OrderRecord }
  | { readonly ok: false; readonly shortfalls: readonly StockShortfall[] };

// ── State ──────────────────────────────────────────────────────────────────

const TOKEN_TTL_MS = 14 * 24 * 60 * 60 * 1_000;

export interface ShopStateOptions {
  /** Backs this episode's `CartStore` with a JSON file (see `CartStore`). */
  readonly cartStorePath?: string;
  /** ISO 8601 instant the episode clock starts at. */
  readonly startTime?: string;
}

/** Per-episode mutable state. Construct via `new` for the base episode or `fork()` for siblings. */
export class ShopState {
  readonly episodeId: string;
  /** Dataset view whose `inventoryByVariantId` is this episode's live inventory. */
  readonly data: SandboxShopData;
  readonly carts: CartStore;
  readonly clock: EpisodeClock;

  private readonly base: SandboxShopData;
  private readonly options: ShopStateOptions;
  private readonly customers = new Map<number, CustomerRecord>();
  private readonly sessions = new Map<string, SessionRecord>();
  private readonly orders = new Map<number, OrderRecord>();
  private readonly inventory = new Map<number, InventoryEntry>();
  private readonly counters = { customer: 0, order: 0, address: 0, token: 0 };

  constructor(base: SandboxShopData, episodeId: string, options: ShopStateOptions = {}) {
    this.base = base;
    this.episodeId = episodeId;
    this.options = options;
    this.clock = new EpisodeClock(options.startTime);
    this.carts =
      options.cartStorePath === undefined
        ? new CartStore({ clock: this.clock })
        : new CartStore({ clock: this.clock, persistencePath: options.cartStorePath });
    this.data = Object.freeze({ ...base, inventoryByVariantId: this.inventory });
    this.seed();
  }

  /** New episode over the same dataset, without file-backed carts. */
  fork(episodeId: string): ShopState {
    const { cartStorePath: _ignored, ...rest } = this.options;
    return new ShopState(this.base, episodeId, rest);
  }

  // ── Customers ──────────────────────────────────────────────────────────

  getCustomer(id: number): CustomerRecord | undefined {
    return this.customers.get(id);
  }

  /** Case-insensitive email lookup. */
  findCustomerByEmail(email: string): CustomerRecord | undefined {
    const needle = email.toLowerCase();
    for (const customer of this.customers.values()) {
      if (customer.email.toLowerCase() === needle) return customer;
    }
    return undefined;
  }

  createCustomer(input: NewCustomer): CustomerRecord {
    const now = this.clock.tick();
    this.counters.customer += 1;
    const customer: CustomerRecord = {
      id: this.counters.customer,
      email: input.email,
      password: input.password,
      firstName: input.firstName,
      lastName: input.lastName,
      phone: input.phone,
      acceptsMarketing: input.acceptsMarketing,
      createdAt: now,
      updatedAt: now,
      addresses: [],
      defaultAddressId: null,
    };
    this.customers.set(customer.id, customer);
    return customer;
  }

  listCustomers(): readonly CustomerRecord[] {
    return [...this.customers.values()];
  }

  // ── Address book ───────────────────────────────────────────────────────
  // A customer with addresses always has a default address, as on Shopify.

  /** Append `address` to the customer's addresses; it becomes the default when there is none. */
  createAddress(customerId: number, address: NewAddress): AddressRecord {
    const customer = this.customerRecord(customerId);
    const now = this.clock.tick();
    const record = this.allocateAddress(address);
    this.customers.set(customerId, {
      ...customer,
      updatedAt: now,
      addresses: [...customer.addresses, record],
      defaultAddressId: customer.defaultAddressId ?? record.id,
    });
    return record;
  }

  /**
   * Apply `changes` to the customer's address `addressId`. A new province
   * clears the province code. `undefined` when the customer has no such
   * address.
   */
  updateAddress(
    customerId: number,
    addressId: number,
    changes: AddressChanges,
  ): AddressRecord | undefined {
    const customer = this.customerRecord(customerId);
    const current = customer.addresses.find((address) => address.id === addressId);
    if (current === undefined) return undefined;
    const now = this.clock.tick();
    const provinceKept = changes.province === undefined || changes.province === current.province;
    const updated: AddressRecord = {
      ...current,
      ...changes,
      provinceCode: provinceKept ? current.provinceCode : null,
    };
    this.customers.set(customerId, {
      ...customer,
      updatedAt: now,
      addresses: customer.addresses.map((address) =>
        address.id === addressId ? updated : address,
      ),
    });
    return updated;
  }

  /**
   * Remove the customer's address `addressId`. When it was the default, the
   * first remaining address becomes the default. `false` when the customer
   * has no such address.
   */
  deleteAddress(customerId: number, addressId: number): boolean {
    const customer = this.customerRecord(customerId);
    if (!customer.addresses.some((address) => address.id === addressId)) return false;
    const now = this.clock.tick();
    const addresses = customer.addresses.filter((address) => address.id !== addressId);
    this.customers.set(customerId, {
      ...customer,
      updatedAt: now,
      addresses,
      defaultAddressId:
        customer.defaultAddressId === addressId
          ? (addresses[0]?.id ?? null)
          : customer.defaultAddressId,
    });
    return true;
  }

  /** Make `addressId` the customer's default address; `undefined` when the customer has no such address. */
  setDefaultAddress(customerId: number, addressId: number): CustomerRecord | undefined {
    const customer = this.customerRecord(customerId);
    if (!customer.addresses.some((address) => address.id === addressId)) return undefined;
    const updated: CustomerRecord = {
      ...customer,
      updatedAt: this.clock.tick(),
      defaultAddressId: addressId,
    };
    this.customers.set(customerId, updated);
    return updated;
  }

  // ── Sessions ───────────────────────────────────────────────────────────

  createSession(customerId: number): SessionRecord {
    this.clock.tick();
    this.counters.token += 1;
    const session: SessionRecord = {
      accessToken: `sandbox-token-${this.counters.token}`,
      customerId,
      expiresAt: this.clock.offset(TOKEN_TTL_MS),
    };
    this.sessions.set(session.accessToken, session);
    return session;
  }

  /** Customer behind a live token, or `undefined` when unknown or expired. */
  resolveSession(accessToken: string): CustomerRecord | undefined {
    const session = this.sessions.get(accessToken);
    if (session === undefined) return undefined;
    if (Date.parse(session.expiresAt) <= Date.parse(this.clock.now())) return undefined;
    return this.customers.get(session.customerId);
  }

  deleteSession(accessToken: string): SessionRecord | undefined {
    const session = this.sessions.get(accessToken);
    if (session === undefined) return undefined;
    this.clock.tick();
    this.sessions.delete(accessToken);
    return session;
  }

  listSessions(): readonly SessionRecord[] {
    return [...this.sessions.values()];
  }

  // ── Orders ─────────────────────────────────────────────────────────────

  getOrder(id: number): OrderRecord | undefined {
    return this.orders.get(id);
  }

  ordersForCustomer(customerId: number): readonly OrderRecord[] {
    return [...this.orders.values()].filter((order) => order.customerId === customerId);
  }

  listOrders(): readonly OrderRecord[] {
    return [...this.orders.values()];
  }

  /** The cart's Discount code when it applies to the cart now, else `null`. */
  appliedDiscountCode(cart: CartState): string | null {
    // A cart holds at most one Discount code.
    const [code] = cart.discountCodes;
    if (code === undefined) return null;
    const lines = cart.lines.flatMap((line) => {
      const lookup = this.base.variantsByGid.get(line.merchandiseId);
      return lookup === undefined ? [] : [{ price: lookup.variant.price, quantity: line.quantity }];
    });
    return priceDiscountCode(code, subtotalCents(lines), this.commerce)?.discountCode.code ?? null;
  }

  /**
   * Convert a cart into an order. Checks every line against live inventory
   * first and commits nothing on a shortfall. On success the inventory is
   * decremented, the order is stored with the cart's Discount code when the
   * code applies, and the cart is removed.
   */
  placeOrder(input: PlaceOrderInput): PlaceOrderResult {
    const { cart } = input;
    const shortfalls = this.stockShortfalls(cart);
    if (shortfalls.length > 0) return { ok: false, shortfalls };

    const lineItems: OrderLineItemRecord[] = [];
    for (const line of cart.lines) {
      const lookup = this.base.variantsByGid.get(line.merchandiseId);
      if (lookup === undefined) continue;
      lineItems.push({
        variantId: lookup.variant.id,
        title: `${lookup.product.title} - ${lookup.variant.title}`,
        quantity: line.quantity,
        price: lookup.variant.price,
      });
      this.decrementInventory(lookup.variant.id, line.quantity);
    }

    const processedAt = this.clock.tick();
    this.counters.order += 1;
    const order: OrderRecord = {
      id: this.counters.order,
      customerId: cart.buyerIdentity.customerId,
      email: input.email,
      processedAt,
      financialStatus: 'PAID',
      fulfillmentStatus: 'UNFULFILLED',
      currencyCode: this.base.store.currency_code,
      lineItems,
      shippingAddress: this.allocateAddress(input.shippingAddress),
      shippingMethod: input.shippingMethod.handle,
      paymentMethod: input.paymentMethod.handle,
      // A cart holds at most one Discount code.
      ...computeOrderTotals(
        lineItems,
        input.shippingMethod,
        this.commerce,
        cart.discountCodes[0] ?? null,
      ),
    };
    this.orders.set(order.id, order);
    this.carts.delete(cart.id);
    return { ok: true, order };
  }

  // ── Inventory ──────────────────────────────────────────────────────────

  /** Entries whose live quantity differs from the loaded `inventory.json`. */
  inventoryDeltas(): readonly InventoryDelta[] {
    const deltas: InventoryDelta[] = [];
    for (const [variantId, entry] of this.inventory) {
      const baseQuantity =
        this.base.inventoryByVariantId.get(variantId)?.quantity_available ?? null;
      if (entry.quantity_available !== baseQuantity) {
        deltas.push({
          variantId,
          baseQuantityAvailable: baseQuantity,
          quantityAvailable: entry.quantity_available,
        });
      }
    }
    return deltas;
  }

  // ── Internals ──────────────────────────────────────────────────────────

  private get commerce(): Commerce {
    return this.base.commerce;
  }

  /** Callers pass ids of live sessions, and customers are never removed. */
  private customerRecord(id: number): CustomerRecord {
    const customer = this.customers.get(id);
    if (customer === undefined) throw new Error(`no customer ${id} in episode ${this.episodeId}`);
    return customer;
  }

  private seed(): void {
    for (const [variantId, entry] of this.base.inventoryByVariantId) {
      this.inventory.set(variantId, { quantity_available: entry.quantity_available });
    }
    for (const customer of this.base.customers) {
      const addresses = customer.addresses.map(toAddressRecord);
      this.customers.set(customer.id, {
        id: customer.id,
        email: customer.email,
        password: customer.password,
        firstName: customer.first_name,
        lastName: customer.last_name,
        phone: customer.phone,
        acceptsMarketing: customer.accepts_marketing,
        createdAt: customer.created_at,
        updatedAt: customer.created_at,
        addresses,
        defaultAddressId: customer.default_address_id,
      });
      this.counters.customer = Math.max(this.counters.customer, customer.id);
      for (const address of addresses) {
        this.counters.address = Math.max(this.counters.address, address.id);
      }
    }
    for (const order of this.base.orders) {
      const shippingAddress =
        order.shipping_address === null ? null : toAddressRecord(order.shipping_address);
      this.orders.set(order.id, {
        id: order.id,
        customerId: order.customer_id,
        email: order.email,
        processedAt: order.processed_at,
        financialStatus: order.financial_status,
        fulfillmentStatus: order.fulfillment_status,
        currencyCode: order.currency_code,
        lineItems: order.line_items.map((line) => ({
          variantId: line.variant_id,
          title: line.title,
          quantity: line.quantity,
          price: line.price,
        })),
        shippingAddress,
        shippingMethod: order.shipping_method,
        paymentMethod: order.payment_method,
        subtotalPrice: order.subtotal_price,
        totalShippingPrice: order.total_shipping_price,
        totalTax: order.total_tax,
        totalPrice: order.total_price,
        discountCode: order.discount_code,
        discountAmount: order.discount_amount,
      });
      this.counters.order = Math.max(this.counters.order, order.id);
      if (shippingAddress !== null) {
        this.counters.address = Math.max(this.counters.address, shippingAddress.id);
      }
    }
    // New orders start at #1001 like a fresh Shopify store.
    this.counters.order = Math.max(this.counters.order, 1000);
  }

  private stockShortfalls(cart: CartState): readonly StockShortfall[] {
    const shortfalls: StockShortfall[] = [];
    for (const line of cart.lines) {
      const lookup = this.base.variantsByGid.get(line.merchandiseId);
      if (lookup === undefined) continue;
      const entry = this.inventory.get(lookup.variant.id);
      if (entry === undefined || entry.quantity_available === null) {
        // Untracked (or tracked-but-unknown) stock: honor the catalog flag.
        if (!lookup.variant.available) {
          shortfalls.push({
            merchandiseId: line.merchandiseId,
            requested: line.quantity,
            available: 0,
          });
        }
        continue;
      }
      if (entry.quantity_available < line.quantity) {
        shortfalls.push({
          merchandiseId: line.merchandiseId,
          requested: line.quantity,
          available: entry.quantity_available,
        });
      }
    }
    return shortfalls;
  }

  private decrementInventory(variantId: number, quantity: number): void {
    const entry = this.inventory.get(variantId);
    if (entry === undefined || entry.quantity_available === null) return;
    this.inventory.set(variantId, { quantity_available: entry.quantity_available - quantity });
  }

  private allocateAddress(address: NewAddress): AddressRecord {
    this.counters.address += 1;
    return { id: this.counters.address, ...address };
  }
}

function toAddressRecord(address: Address): AddressRecord {
  return {
    id: address.id,
    firstName: address.first_name,
    lastName: address.last_name,
    company: address.company,
    address1: address.address1,
    address2: address.address2,
    city: address.city,
    province: address.province,
    provinceCode: address.province_code,
    country: address.country,
    countryCode: address.country_code,
    zip: address.zip,
    phone: address.phone,
  };
}
