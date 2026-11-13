/**
 * The shop history of a Source bundle: one Persona per modeled user, the
 * orders of the purchase events before the cutoff, and the Reviews
 * created before the cutoff. Every time is shifted by the bundle clock.
 * The User events at the cutoff or later stay hidden: they become the
 * future events of `users/`, with the shop ids and handles next to the
 * bundle ids.
 *
 * Code makes every Persona field from a fixed seed: a name pair that no
 * other Persona has, one or two saved addresses, and the account fields
 * that `buildCustomer` derives from the name. A reviewer who is not a
 * modeled user gets a seeded first name and last initial.
 */

import type { UserEvent } from '@shop-gym/core';
import {
  type Commerce,
  type Customer,
  type Order,
  computeOrderTotals,
} from '@shop-gym/shop-backend';

import { SynthError } from '../../llm.js';
import { buildCustomer } from '../assemble.js';
import { pick, seededRandom, takeRandom } from '../ids.js';
import { FIRST_ORDER_ID } from '../orders.js';
import { FIRST_NAMES, LAST_INITIALS, type Review } from '../reviews.js';
import type { Identity, Persona } from '../schemas.js';
import { type BundleCatalog, compareIds } from './catalog.js';
import { firstSeen, isBeforeCutoff, shiftTime } from './clock.js';
import type { SourceBundle } from './read.js';

const PERSONA_SEED = 'bundle-personas';
const ORDER_SEED = 'bundle-orders';
const LAST_NAMES = [
  'Abbott',
  'Bishop',
  'Carver',
  'Dalton',
  'Ellison',
  'Fletcher',
  'Garner',
  'Hollis',
  'Ingram',
  'Jarvis',
  'Keller',
  'Lowell',
  'Mercer',
  'Nolan',
  'Osborne',
  'Prescott',
  'Quinlan',
  'Rowe',
  'Sutton',
  'Thorne',
  'Underwood',
  'Vance',
  'Whitlock',
  'Yates',
  'Ashby',
  'Brennan',
  'Calloway',
  'Doyle',
  'Everly',
  'Finch',
  'Greer',
  'Hayward',
  'Kendall',
  'Lambert',
  'Marlow',
  'Pryor',
  'Radley',
  'Sheridan',
  'Talbot',
  'Winslow',
];
const STREETS = [
  'Alder Street',
  'Birch Lane',
  'Cedar Avenue',
  'Linden Road',
  'Maple Court',
  'Orchard Way',
  'Quarry Lane',
  'Willow Drive',
];
const TOWNS = ['Ashmere', 'Brindleford', 'Corrowick', 'Dunmore Vale', 'Elmsby', 'Fernhollow'];
const MAX_ADDRESSES = 2;
const FIRST_STREET_NUMBER = 10;
const STREET_NUMBERS = 990;
const FIRST_ZIP = 10_000;
const ZIP_CODES = 90_000;
/** The status of an order in the history: paid and shipped. */
const SHIPPED = { financial_status: 'PAID', fulfillment_status: 'FULFILLED' } as const;

/** A User event at the cutoff or later, with the shop ids and handles it names. */
export type FutureEvent = UserEvent & {
  readonly shop: {
    /** The shifted time. */
    readonly timestamp: string;
    readonly customer_id: number;
    readonly product_id?: number;
    readonly product_handle?: string;
    readonly variant_id?: number;
  };
};

export interface BundleHistory {
  /** One Persona per modeled user, in user id order. */
  readonly customers: readonly Customer[];
  readonly orders: readonly Order[];
  readonly reviews: readonly Review[];
  /** The customer id of each modeled user. */
  readonly personaMap: Readonly<Record<string, number>>;
  /** The User events at the cutoff or later, in bundle order. */
  readonly futureEvents: readonly FutureEvent[];
}

function lookup<K, V>(map: ReadonlyMap<K, V>, key: K, what: string): V {
  const value = map.get(key);
  if (value === undefined) throw new SynthError(`no shop ${what} for bundle id ${String(key)}`);
  return value;
}

/** `count` Personas whose name pairs are all different. */
function personas(count: number): Persona[] {
  const names = FIRST_NAMES.flatMap((first) => LAST_NAMES.map((last) => [first, last] as const));
  if (count > names.length) {
    throw new SynthError(
      `the bundle has ${count} modeled users; Persona names allow at most ${names.length}`,
    );
  }
  const rng = seededRandom(PERSONA_SEED);
  return Array.from({ length: count }, () => {
    // `names` has at least `count` pairs, so a pair is left to take.
    const [first, last] = takeRandom(rng, names) as readonly [string, string];
    return {
      first_name: first,
      last_name: last,
      phone: null,
      accepts_marketing: rng() < 0.5,
      addresses: Array.from({ length: 1 + Math.floor(rng() * MAX_ADDRESSES) }, () => ({
        address1: `${FIRST_STREET_NUMBER + Math.floor(rng() * STREET_NUMBERS)} ${pick(rng, STREETS)}`,
        address2: null,
        city: pick(rng, TOWNS),
        province: null,
        province_code: null,
        zip: String(FIRST_ZIP + Math.floor(rng() * ZIP_CODES)),
      })),
    };
  });
}

/**
 * The purchase events before the cutoff, grouped into orders: by user and
 * by order id, else by session id, else by time.
 */
function purchaseGroups(bundle: SourceBundle): { key: string; events: UserEvent[] }[] {
  const groups = new Map<string, UserEvent[]>();
  for (const event of bundle.events) {
    if (event.event_type !== 'purchase' || !isBeforeCutoff(bundle.clock, event.timestamp)) continue;
    const key = `${event.user_id}\0${event.order_id ?? event.session_id ?? event.timestamp}`;
    const group = groups.get(key) ?? [];
    group.push(event);
    groups.set(key, group);
  }
  return [...groups].map(([key, events]) => ({ key, events }));
}

function mapOrders(
  bundle: SourceBundle,
  catalog: BundleCatalog,
  customerOf: ReadonlyMap<string, Customer>,
  commerce: Commerce,
  currencyCode: string,
  log: (line: string) => void,
): Order[] {
  let skipped = 0;
  const drafts = purchaseGroups(bundle).flatMap(({ key, events }) => {
    const lines = new Map<number, Order['line_items'][number]>();
    for (const event of events) {
      if (event.product_id === undefined) {
        skipped += 1;
        continue;
      }
      const product = lookup(catalog.productOf, event.product_id, 'product');
      const variant =
        event.variant_id === undefined
          ? product.variants[0]
          : lookup(catalog.variantOf, event.variant_id, 'variant').variant;
      if (variant === undefined) continue;
      const line = lines.get(variant.id);
      lines.set(variant.id, {
        variant_id: variant.id,
        title: `${product.title} - ${variant.title}`,
        quantity: (line?.quantity ?? 0) + (event.quantity ?? 1),
        price: line?.price ?? event.price?.amount.toFixed(2) ?? variant.price,
      });
    }
    if (lines.size === 0) return [];
    const user = events[0]?.user_id ?? '';
    const time = Math.max(...events.map((event) => Date.parse(event.timestamp)));
    return [
      { key, time, customer: lookup(customerOf, user, 'customer'), lineItems: [...lines.values()] },
    ];
  });
  if (skipped > 0) log(`[data_synth] bundle orders: ${skipped} purchase events name no product`);
  drafts.sort((a, b) => a.time - b.time || compareIds(a.key, b.key));
  const rng = seededRandom(ORDER_SEED);
  return drafts.map((draft, i) => {
    const method = pick(rng, commerce.shipping_methods);
    const payment =
      commerce.payment_methods.length === 0 ? null : pick(rng, commerce.payment_methods);
    const address =
      draft.customer.addresses.length === 0 ? null : pick(rng, draft.customer.addresses);
    const totals = computeOrderTotals(draft.lineItems, method, commerce, null);
    return {
      id: FIRST_ORDER_ID + i,
      ...SHIPPED,
      customer_id: draft.customer.id,
      email: draft.customer.email,
      processed_at: shiftTime(bundle.clock, new Date(draft.time).toISOString()),
      currency_code: currencyCode,
      line_items: draft.lineItems,
      shipping_address: address,
      shipping_method: method.handle,
      payment_method: payment?.handle ?? null,
      subtotal_price: totals.subtotalPrice,
      total_shipping_price: totals.totalShippingPrice,
      total_tax: totals.totalTax,
      total_price: totals.totalPrice,
      discount_code: totals.discountCode,
      discount_amount: totals.discountAmount,
    };
  });
}

function mapReviews(
  bundle: SourceBundle,
  catalog: BundleCatalog,
  customerOf: ReadonlyMap<string, Customer>,
): Review[] {
  return [...bundle.reviews]
    .sort((a, b) => compareIds(a.review_id, b.review_id))
    .map((review, i) => {
      const { product, variant } = lookup(catalog.variantOf, review.variant_id, 'variant');
      const customer = review.user_id === undefined ? undefined : customerOf.get(review.user_id);
      const rng = seededRandom(`reviewer\0${review.review_id}`);
      return {
        id: i + 1,
        product_handle: product.handle,
        variant_id: variant.id,
        rating: review.rating,
        title: review.title,
        body: review.body,
        reviewer_name:
          customer === undefined
            ? `${pick(rng, FIRST_NAMES)} ${pick(rng, LAST_INITIALS)}.`
            : `${customer.first_name} ${customer.last_name?.slice(0, 1) ?? ''}.`,
        created_at: shiftTime(bundle.clock, review.created_at),
        verified_buyer: review.verified_purchase,
        helpful_count: review.helpful_votes,
        ...(customer === undefined ? {} : { customer_id: customer.id }),
      };
    });
}

function futureEvents(
  bundle: SourceBundle,
  catalog: BundleCatalog,
  customerOf: ReadonlyMap<string, Customer>,
): FutureEvent[] {
  return bundle.events
    .filter((event) => !isBeforeCutoff(bundle.clock, event.timestamp))
    .map((event) => {
      const product =
        event.product_id === undefined
          ? undefined
          : lookup(catalog.productOf, event.product_id, 'product');
      const variant =
        event.variant_id === undefined
          ? undefined
          : lookup(catalog.variantOf, event.variant_id, 'variant').variant;
      return {
        ...event,
        shop: {
          timestamp: shiftTime(bundle.clock, event.timestamp),
          customer_id: lookup(customerOf, event.user_id, 'customer').id,
          ...(product === undefined
            ? {}
            : { product_id: product.id, product_handle: product.handle }),
          ...(variant === undefined ? {} : { variant_id: variant.id }),
        },
      };
    });
}

/**
 * Maps the modeled users, the reviews and the User events of `bundle`
 * onto the shop catalog.
 *
 * @throws SynthError when the bundle has more modeled users than Persona
 *   name pairs.
 */
export function mapBundleHistory(
  bundle: SourceBundle,
  catalog: BundleCatalog,
  identity: Identity,
  commerce: Commerce,
  log: (line: string) => void,
): BundleHistory {
  const profiles = [...bundle.profiles].sort((a, b) => compareIds(a.user_id, b.user_id));
  const createdAt = firstSeen(bundle, 'user_id');
  const people = personas(profiles.length);
  const customerOf = new Map(
    profiles.map((profile, i) => {
      // `people` has one Persona per profile.
      const persona = people[i] as Persona;
      const customer = buildCustomer(persona, identity.country);
      return [profile.user_id, { ...customer, created_at: createdAt(profile.user_id) }];
    }),
  );
  return {
    customers: [...customerOf.values()],
    orders: mapOrders(bundle, catalog, customerOf, commerce, identity.currency, log),
    reviews: mapReviews(bundle, catalog, customerOf),
    personaMap: Object.fromEntries([...customerOf].map(([userId, c]) => [userId, c.id])),
    futureEvents: futureEvents(bundle, catalog, customerOf),
  };
}
