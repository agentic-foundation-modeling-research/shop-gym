/**
 * Skills `shipping` and `returns`: find a policy page.
 *
 * The target is a `policies.json` entry with the canonical handle, or else a
 * `pages.json` entry whose title or handle matches the skill's keywords. No
 * task is emitted when the dataset has neither, so every task is grounded.
 */

import type { Task } from '@shop-gym/core';

import { type SeedContext, makeTaskId } from './context.js';
import { pagesMatching } from './filters.js';

interface PolicyKind {
  readonly skill: string;
  readonly policyHandle: string;
  readonly keywords: readonly string[];
  readonly label: string;
}

const KINDS: readonly PolicyKind[] = [
  {
    skill: 'shipping',
    policyHandle: 'shipping-policy',
    keywords: ['shipping', 'delivery', 'ship'],
    label: 'shipping policy',
  },
  {
    skill: 'returns',
    policyHandle: 'refund-policy',
    keywords: ['refund', 'return', 'exchange'],
    label: 'returns and refund policy',
  },
];

function targetPath(ctx: SeedContext, kind: PolicyKind): string | undefined {
  if (ctx.data.policies.some((p) => p.handle === kind.policyHandle)) {
    return `/policies/${kind.policyHandle}`;
  }
  const page = pagesMatching(ctx.data.pages, kind.keywords)[0];
  return page === undefined ? undefined : `/pages/${page.handle}`;
}

function generateKind(ctx: SeedContext, kind: PolicyKind): Task[] {
  const path = targetPath(ctx, kind);
  if (path === undefined) return [];
  return [
    {
      id: makeTaskId(ctx.shop, kind.skill, 1),
      shop: ctx.shop,
      skill: kind.skill,
      goal: `Find this store's ${kind.label} page (look in the footer, menus, or help links) and finish while that page is open.`,
      eval: [{ type: 'url_match', url: path, rule: 'contains' }],
      source: 'seed',
    },
  ];
}

export function generateShipping(ctx: SeedContext): Task[] {
  return generateKind(ctx, KINDS[0] as PolicyKind);
}

export function generateReturns(ctx: SeedContext): Task[] {
  return generateKind(ctx, KINDS[1] as PolicyKind);
}
