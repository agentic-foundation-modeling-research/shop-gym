/**
 * Programmatic task validation.
 *
 * Every task must parse against the task schema and reference only things the
 * dataset has: product, collection, page, and policy handles in URLs, persona
 * ids in `setup.login`, variant ids in `setup.cart`, and variant or customer
 * gids inside `state_check` values. Duplicate goals are dropped and each skill
 * is capped. Dropped tasks are reported, never silently discarded.
 */

import { type Check, type Task, taskSchema } from '@shop-gym/core';
import type { SandboxShopData } from '@shop-gym/shop-backend';

/** Why one task was dropped. */
export interface ValidationIssue {
  readonly taskId: string;
  readonly reason: string;
}

export interface ValidationReport {
  readonly tasks: Task[];
  readonly dropped: ValidationIssue[];
}

const HANDLE_PATH = /\/(products|collections|pages|policies)\/([^/?#]+)/;
const VARIANT_GID = /^gid:\/\/shopify\/ProductVariant\/(\d+)$/;
const CUSTOMER_GID = /^gid:\/\/shopify\/Customer\/(\d+)$/;

interface Indexes {
  readonly handles: Readonly<Record<string, ReadonlySet<string>>>;
  readonly variantIds: ReadonlySet<number>;
  readonly customerIds: ReadonlySet<number>;
}

function buildIndexes(data: SandboxShopData): Indexes {
  return {
    handles: {
      products: new Set(data.products.map((p) => p.handle)),
      collections: new Set(data.collections.map((c) => c.handle)),
      pages: new Set(data.pages.map((p) => p.handle)),
      policies: new Set(data.policies.map((p) => p.handle)),
    },
    variantIds: new Set(data.products.flatMap((p) => p.variants.map((v) => v.id))),
    customerIds: new Set(data.customers.map((c) => c.id)),
  };
}

function checkUrl(url: string, indexes: Indexes): string | undefined {
  const match = HANDLE_PATH.exec(url);
  if (match === null) return undefined;
  const [, kind, handle] = match as unknown as [string, string, string];
  return indexes.handles[kind]?.has(handle) ? undefined : `unknown ${kind} handle "${handle}"`;
}

/** Every string nested anywhere in a JSON value. */
function strings(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap(strings);
  if (value !== null && typeof value === 'object') return Object.values(value).flatMap(strings);
  return [];
}

function checkGids(check: Check, indexes: Indexes): string | undefined {
  if (check.type !== 'state_check') return undefined;
  for (const text of strings(check.value)) {
    const variant = VARIANT_GID.exec(text);
    if (variant !== null && !indexes.variantIds.has(Number(variant[1]))) {
      return `unknown variant ${text}`;
    }
    const customer = CUSTOMER_GID.exec(text);
    if (customer !== null && !indexes.customerIds.has(Number(customer[1]))) {
      return `unknown customer ${text}`;
    }
  }
  return undefined;
}

/** First reference problem in `task`, or `undefined` when all references resolve. */
function findReferenceIssue(task: Task, indexes: Indexes): string | undefined {
  if (task.setup?.login !== undefined && !indexes.customerIds.has(Number(task.setup.login))) {
    return `unknown persona "${task.setup.login}"`;
  }
  for (const line of task.setup?.cart ?? []) {
    if (!indexes.variantIds.has(line.variantId)) return `unknown variant id ${line.variantId}`;
  }
  for (const check of task.eval) {
    if (check.type === 'url_match' || check.type === 'locator_probe') {
      const issue = checkUrl(check.url, indexes);
      if (issue !== undefined) return issue;
    }
    if (check.type === 'locator_probe' && check.locator.trim() === '') {
      return 'locator_probe without a selector';
    }
    const gidIssue = checkGids(check, indexes);
    if (gidIssue !== undefined) return gidIssue;
  }
  return undefined;
}

/**
 * Keep the tasks that parse, resolve against `data`, have a goal not seen
 * before, and fit under their skill's cap. Input order is preserved, so
 * earlier tasks win ties.
 */
export function validateTasks(
  candidates: readonly unknown[],
  data: SandboxShopData,
  caps: Readonly<Record<string, number>> = {},
): ValidationReport {
  const indexes = buildIndexes(data);
  const tasks: Task[] = [];
  const dropped: ValidationIssue[] = [];
  const seenGoals = new Set<string>();
  const perSkill = new Map<string, number>();

  candidates.forEach((candidate, i) => {
    const parsed = taskSchema.safeParse(candidate);
    if (!parsed.success) {
      const id = (candidate as { id?: unknown })?.id;
      dropped.push({
        taskId: typeof id === 'string' ? id : `#${i}`,
        reason: `schema: ${parsed.error.issues[0]?.message ?? 'invalid'}`,
      });
      return;
    }
    const task = parsed.data;
    const reference = findReferenceIssue(task, indexes);
    if (reference !== undefined) {
      dropped.push({ taskId: task.id, reason: reference });
      return;
    }
    const goalKey = task.goal.trim().toLowerCase();
    if (seenGoals.has(goalKey)) {
      dropped.push({ taskId: task.id, reason: 'duplicate goal' });
      return;
    }
    const used = perSkill.get(task.skill) ?? 0;
    const cap = caps[task.skill];
    if (cap !== undefined && used >= cap) {
      dropped.push({ taskId: task.id, reason: `skill "${task.skill}" cap ${cap} reached` });
      return;
    }
    seenGoals.add(goalKey);
    perSkill.set(task.skill, used + 1);
    tasks.push(task);
  });
  return { tasks, dropped };
}
