/**
 * `cart_conformance` verifier: the storefront's cart and checkout forms
 * drive the backend correctly. Over HTTP, in a fresh episode: add a variant,
 * update its quantity, check the cart page shows the backend's totals,
 * remove the line, then place a guest order and confirm the confirmation
 * page shows the order the backend recorded. Backend state is read from the
 * sandbox control API, so the check sees what the backend stored rather
 * than what the page claims.
 */

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { StorefrontClient, bodyExcerpt, firstAvailableMerchandiseId } from './http.js';
import {
  CHECKOUT_ADDRESS,
  type StorefrontTarget,
  prepareTarget,
  readCheckoutMethods,
} from './storefront_target.js';
import { SWEEP_CAPS, readDatasetHandles, sampleProductHandles } from './task_routes.js';

export const CART_CONFORMANCE_NAME = 'cart_conformance';
const CART_TASKS = new Set(['gen_cart_search', 'gen_product', 'gen_checkout', 'visual_fix']);
const GUEST_EMAIL = 'guest.shopper@example.com';
const CART_COST_QUERY = `query CartCost($id: ID!) {
  cart(id: $id) {
    cost {
      subtotalAmount { amount currencyCode }
      totalAmount { amount currencyCode }
    }
  }
}`;

export interface CartStep {
  readonly name: string;
  readonly ok: boolean;
  readonly detail: string;
}

export interface CartConformanceOptions {
  readonly target: StorefrontTarget;
  readonly backendUrl: string;
  readonly dataDir: string;
}

interface SnapshotCart {
  readonly id: string;
  readonly lines: readonly {
    readonly id: string;
    readonly merchandiseId: string;
    readonly quantity: number;
  }[];
}

interface Snapshot {
  readonly carts: readonly SnapshotCart[];
  readonly orders: readonly {
    readonly id: string;
    readonly name: string;
    readonly email: string | null;
  }[];
}

interface Money {
  readonly amount: string;
  readonly currencyCode: string;
}

/** A step sequence that stops at the first failure, since later steps depend on it. */
class StepLog {
  readonly steps: CartStep[] = [];

  record(name: string, ok: boolean, detail: string): boolean {
    this.steps.push({ name, ok, detail });
    return ok;
  }
}

export function cartConformanceVerifier(options: CartConformanceOptions): Verifier {
  return {
    name: CART_CONFORMANCE_NAME,
    appliesTo: (taskId) => CART_TASKS.has(taskId),
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const blocked = await prepareTarget(options.target);
      if (blocked !== undefined) {
        return blocked;
      }
      const episodeId = `cart-conformance-${ctx.iterId}-${Date.now()}`;
      const log = new StepLog();
      await runCartFlow(options, episodeId, log);
      const failures = log.steps.filter((s) => !s.ok);
      const details = { episodeId, steps: log.steps };
      if (failures.length === 0) {
        return { verdict: 'pass', details };
      }
      const lines = [
        `\`cart_conformance\`: the cart flow broke at step \`${failures[0]?.name}\`.`,
        '',
      ];
      for (const step of log.steps) {
        lines.push(`- ${step.ok ? 'ok' : 'FAIL'} ${step.name}: ${step.detail}`);
      }
      return { verdict: 'fail', feedback: lines.join('\n'), details };
    },
  };
}

/** Drive add, update, totals, remove and guest checkout; each step records into `log`. */
async function runCartFlow(
  options: CartConformanceOptions,
  episodeId: string,
  log: StepLog,
): Promise<void> {
  const handles = await readDatasetHandles(options.dataDir);
  const client = new StorefrontClient({ baseUrl: options.target.url, episodeId });
  const backend = new BackendProbe(options.backendUrl, episodeId);

  const productHandle = sampleProductHandles(handles, SWEEP_CAPS)[0];
  if (productHandle === undefined) {
    log.record('product', false, 'the dataset has no product to add to the cart');
    return;
  }
  const product = await client.get(`/products/${productHandle}`);
  const merchandiseId = firstAvailableMerchandiseId(product.body);
  if (
    !log.record(
      'product page',
      product.status === 200 && merchandiseId !== undefined,
      merchandiseId !== undefined
        ? `/products/${productHandle} offers variant ${merchandiseId}`
        : `/products/${productHandle} returned ${product.status} without an enabled merchandiseId radio; ${bodyExcerpt(product.body)}`,
    ) ||
    merchandiseId === undefined
  ) {
    return;
  }

  const added = await client.post('/cart', { intent: 'add', merchandiseId, quantity: '1' });
  let cart = (await backend.snapshot()).carts.find((c) =>
    c.lines.some((l) => l.merchandiseId === merchandiseId),
  );
  const addedLine = cart?.lines.find((l) => l.merchandiseId === merchandiseId);
  if (
    !log.record(
      'add to cart',
      added.status < 400 && addedLine !== undefined && addedLine.quantity === 1,
      addedLine !== undefined
        ? `POST /cart intent=add returned ${added.status}; backend cart ${cart?.id} has quantity ${addedLine.quantity}`
        : `POST /cart intent=add returned ${added.status}; the backend recorded no cart line for ${merchandiseId}`,
    ) ||
    cart === undefined ||
    addedLine === undefined
  ) {
    return;
  }

  const updated = await client.post('/cart', {
    intent: 'update',
    lineId: addedLine.id,
    quantity: '2',
  });
  cart = await backend.cart(cart.id);
  const updatedLine = cart?.lines.find((l) => l.id === addedLine.id);
  if (
    !log.record(
      'update quantity',
      updated.status < 400 && updatedLine?.quantity === 2,
      `POST /cart intent=update quantity=2 returned ${updated.status}; backend quantity is ${updatedLine?.quantity ?? 'missing'}`,
    ) ||
    cart === undefined
  ) {
    return;
  }

  const cost = await backend.cartCost(cart.id);
  const cartPage = await client.get('/cart');
  const expected = [formatMoney(cost.subtotal), formatMoney(cost.total)];
  const missing = expected.filter((text) => !cartPage.body.includes(text));
  if (
    !log.record(
      'cart page totals',
      cartPage.status === 200 && missing.length === 0,
      missing.length === 0
        ? `/cart shows subtotal ${expected[0]} and total ${expected[1]}`
        : `/cart returned ${cartPage.status} and does not show ${missing.join(' or ')} (backend subtotal ${cost.subtotal.amount}, total ${cost.total.amount} ${cost.total.currencyCode})`,
    )
  ) {
    return;
  }

  const removed = await client.post('/cart', { intent: 'remove', lineId: addedLine.id });
  cart = await backend.cart(cart.id);
  const emptyPage = await client.get('/cart');
  if (
    !log.record(
      'remove line',
      removed.status < 400 &&
        (cart?.lines.length ?? 0) === 0 &&
        emptyPage.body.includes('Your cart is empty'),
      `POST /cart intent=remove returned ${removed.status}; backend has ${cart?.lines.length ?? 0} line(s); /cart ${emptyPage.body.includes('Your cart is empty') ? 'shows' : 'does not show'} "Your cart is empty"`,
    )
  ) {
    return;
  }

  await client.post('/cart', { intent: 'add', merchandiseId, quantity: '1' });
  const methods = await readCheckoutMethods(options.dataDir);
  const checkout = await client.post('/checkout', {
    email: GUEST_EMAIL,
    ...CHECKOUT_ADDRESS,
    ...methods,
  });
  const confirmationMatch = /^\/checkout\/confirmation\/\d+$/.test(checkout.location);
  if (
    !log.record(
      'guest checkout',
      checkout.status === 302 && confirmationMatch,
      `POST /checkout returned ${checkout.status}${checkout.location === '' ? '' : ` -> ${checkout.location}`}${confirmationMatch ? '' : `; ${bodyExcerpt(checkout.body)}`}`,
    )
  ) {
    return;
  }
  const order = (await backend.snapshot()).orders.find((o) => o.email === GUEST_EMAIL);
  const confirmation = await client.get(checkout.location);
  log.record(
    'confirmation page',
    order !== undefined && confirmation.status === 200 && confirmation.body.includes(order.name),
    order === undefined
      ? 'the backend recorded no order for the guest checkout'
      : `${checkout.location} returned ${confirmation.status} and ${confirmation.body.includes(order.name) ? 'shows' : 'does not show'} order ${order.name}`,
  );
}

/** Reads backend state for one episode through the control API and GraphQL. */
class BackendProbe {
  constructor(
    private readonly backendUrl: string,
    private readonly episodeId: string,
  ) {}

  async snapshot(): Promise<Snapshot> {
    const response = await fetch(`${this.backendUrl}/__shopgym/episodes/${this.episodeId}/state`);
    if (!response.ok) {
      throw new Error(`control API returned ${response.status} for episode ${this.episodeId}`);
    }
    return (await response.json()) as Snapshot;
  }

  async cart(id: string): Promise<SnapshotCart | undefined> {
    return (await this.snapshot()).carts.find((c) => c.id === id);
  }

  async cartCost(id: string): Promise<{ subtotal: Money; total: Money }> {
    const response = await fetch(`${this.backendUrl}/graphql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-shopgym-episode': this.episodeId },
      body: JSON.stringify({ query: CART_COST_QUERY, variables: { id } }),
    });
    const payload = (await response.json()) as {
      data?: { cart?: { cost: { subtotalAmount: Money; totalAmount: Money } } | null };
    };
    const cost = payload.data?.cart?.cost;
    if (cost === undefined) {
      throw new Error(`backend returned no cart cost for ${id}`);
    }
    return { subtotal: cost.subtotalAmount, total: cost.totalAmount };
  }
}

/** Format like the template's `Price` component: `Intl.NumberFormat('en-US', currency)`. */
export function formatMoney(money: Money): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: money.currencyCode }).format(
    Number.parseFloat(money.amount),
  );
}
