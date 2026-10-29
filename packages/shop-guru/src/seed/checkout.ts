/**
 * Skill `checkout`: complete a purchase for a pre-filled cart.
 *
 * The persona is logged in and one variant is placed in the cart by `setup`.
 * The expected order must contain that variant, belong to the persona, and
 * ship to the persona's default address. Variants the persona has already
 * ordered in `orders.json` are avoided so a seeded order cannot satisfy the
 * check.
 */

import type { Task } from '@shop-gym/core';
import type { Customer, SandboxShopData } from '@shop-gym/shop-backend';

import {
  type SeedContext,
  customerGid,
  makeTaskId,
  personaName,
  skillRng,
  variantGid,
} from './context.js';
import { isTaskCandidate } from './filters.js';

export const SKILL = 'checkout';

interface Target {
  readonly variantId: number;
  readonly productTitle: string;
  readonly variantTitle: string;
}

function previouslyOrdered(customer: Customer, data: SandboxShopData): Set<number> {
  const ids = new Set<number>();
  for (const order of data.orders) {
    if (order.customer_id !== customer.id) continue;
    for (const line of order.line_items) ids.add(line.variant_id);
  }
  return ids;
}

function pickTarget(
  customer: Customer,
  data: SandboxShopData,
  shuffled: readonly SandboxShopData['products'][number][],
): Target | undefined {
  const exclude = previouslyOrdered(customer, data);
  for (const product of shuffled) {
    const variant = product.variants.find((v) => v.available && !exclude.has(v.id));
    if (variant !== undefined) {
      return { variantId: variant.id, productTitle: product.title, variantTitle: variant.title };
    }
  }
  return undefined;
}

export function generate(ctx: SeedContext, count: number): Task[] {
  const rng = skillRng(ctx, SKILL);
  const personas = rng.shuffle(ctx.data.customers.filter((c) => c.default_address_id !== null));
  const products = rng.shuffle(ctx.data.products.filter(isTaskCandidate));
  const tasks: Task[] = [];
  for (const customer of personas) {
    if (tasks.length >= count) break;
    const address = customer.addresses.find((a) => a.id === customer.default_address_id);
    const target = pickTarget(customer, ctx.data, products);
    if (address === undefined || target === undefined) continue;
    const variantNote = target.variantTitle === 'Default Title' ? '' : ` (${target.variantTitle})`;
    tasks.push({
      id: makeTaskId(ctx.shop, SKILL, tasks.length + 1),
      shop: ctx.shop,
      skill: SKILL,
      goal: `You are signed in as ${personaName(customer)} and your cart already holds one "${target.productTitle}"${variantNote}. Check out and place the order, shipping to your default address. Do not change the cart contents.`,
      setup: { login: String(customer.id), cart: [{ variantId: target.variantId, quantity: 1 }] },
      eval: [
        {
          type: 'state_check',
          path: '/orders',
          match: 'some',
          value: {
            customerId: customerGid(customer.id),
            lineItems: [{ variantId: variantGid(target.variantId), quantity: 1 }],
            shippingAddress: { address1: address.address1, city: address.city, zip: address.zip },
          },
        },
      ],
      source: 'seed',
      evidence: { customerId: customer.id, variantId: target.variantId },
    });
  }
  return tasks;
}
