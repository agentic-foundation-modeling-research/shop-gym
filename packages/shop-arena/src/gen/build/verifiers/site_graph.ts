/**
 * `site_graph` verifier: walks the Site state graph of the Shop Manual on
 * the built shop, over HTTP, as a guest.
 *
 * The graph is abstract and its URL patterns come from the source shop,
 * so the walk never uses them. `PAGE_TYPE_RULES` maps each page type onto
 * a route of the built shop. A transition is checked when it navigates
 * from one routed page to another with a shopper control. To walk it, the
 * verifier loads the built page of `from`, finds a link or a form whose
 * target matches the built route of `to`, and loads that target. The
 * transition fails when the page does not load, when no control leads to
 * the route, or when the target does not load.
 *
 * Every other transition is advisory: it is listed in the details with
 * its reason, but it does not fail the verifier. A transition is advisory
 * when an end is an overlay, when its effect is not `navigate`, when its
 * trigger is `load`, or when `PAGE_TYPE_RULES` does not walk the page type
 * at one end (a member, checkout or `other` page, or a cart or `page` page
 * at the `from` end).
 *
 * Each checked transition belongs to the task that builds its `from`
 * page, and that task walks it; `visual_fix` walks them all.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import {
  type PageType,
  type SiteGraph,
  type SiteGraphState,
  type SiteGraphTransition,
  parseSiteGraph,
} from '@shop-gym/core';
import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import { exists } from '../../io.js';
import { SITE_GRAPH_FILE } from '../../manual_merge/index.js';
import { StorefrontClient, bodyExcerpt } from './http.js';
import { type StorefrontTarget, prepareTarget } from './storefront_target.js';
import {
  DEFAULT_CAPS,
  type DatasetHandles,
  readDatasetHandles,
  sampleProductHandles,
  searchToken,
} from './task_routes.js';

export const SITE_GRAPH_NAME = 'site_graph';
/** The task that walks every checked transition. */
const ALL_TRANSITIONS_TASK = 'visual_fix';

/** How the verifier treats the transitions that start or end on one page type. */
export type PageTypeRule =
  | {
      /** Transitions from and to the page type are walked. */
      readonly kind: 'checked';
      /** The built route. Each `{name}` takes a value from the Dataset. */
      readonly route: string;
      /** The build task that makes the page, and so the controls on it. */
      readonly owner: string;
    }
  | {
      /** Transitions to the page type are walked. Transitions from it are advisory. */
      readonly kind: 'target_only';
      readonly route: string;
      readonly advisory: string;
    }
  | {
      /** Transitions from or to the page type are advisory. */
      readonly kind: 'advisory';
      readonly advisory: string;
    };

const MEMBER_PAGE = 'it shows only to a logged-in customer; account_flow checks it';
const CHECKOUT_PAGE =
  'it opens only with items in the cart; cart_conformance and discount_flow check it';

/**
 * The built route of each page type. Header and footer controls are
 * transitions from `home`, so `gen_homepage` owns them: it runs after
 * `gen_navigation`, and both the shell and the home page are built when
 * it ends.
 */
export const PAGE_TYPE_RULES: Readonly<Record<PageType, PageTypeRule>> = {
  home: { kind: 'checked', route: '/', owner: 'gen_homepage' },
  collection: { kind: 'checked', route: '/collections/{collection}', owner: 'gen_collections' },
  product: { kind: 'checked', route: '/products/{product}', owner: 'gen_product' },
  search: { kind: 'checked', route: '/search?q={query}', owner: 'gen_cart_search' },
  cart: {
    kind: 'target_only',
    route: '/cart',
    advisory:
      'a guest cart is empty, so the page shows no line or checkout control; cart_conformance checks the cart',
  },
  page: {
    kind: 'target_only',
    route: '/pages/{page}',
    advisory:
      'the source shop uses this type for many kinds of page, but the built shop has only the info pages of the Dataset',
  },
  policy: { kind: 'checked', route: '/policies/{policy}', owner: 'gen_info_pages' },
  login: { kind: 'checked', route: '/account/login', owner: 'gen_account' },
  register: { kind: 'checked', route: '/account/register', owner: 'gen_account' },
  account: { kind: 'advisory', advisory: MEMBER_PAGE },
  addresses: { kind: 'advisory', advisory: MEMBER_PAGE },
  order_detail: { kind: 'advisory', advisory: MEMBER_PAGE },
  checkout: { kind: 'advisory', advisory: CHECKOUT_PAGE },
  checkout_confirmation: { kind: 'advisory', advisory: CHECKOUT_PAGE },
  other: { kind: 'advisory', advisory: 'the built shop has no route for this page type' },
};

/** The result for one transition of the graph. */
export interface TransitionCheck {
  readonly from: string;
  readonly to: string;
  readonly action: string;
  readonly status: 'pass' | 'fail' | 'advisory';
  /** Why the transition is advisory, or what failed. */
  readonly reason?: string;
  /** The built page of `from` that the walk loaded. */
  readonly url?: string;
  /** The target of the control that the walk followed. */
  readonly target?: string;
}

export interface SiteGraphVerifierOptions {
  readonly target: StorefrontTarget;
  /** The Dataset that fills the `{name}` parts of the built routes. */
  readonly dataDir: string;
  readonly graph: SiteGraph;
}

/** A transition that the verifier walks. */
interface Walk {
  readonly transition: SiteGraphTransition;
  readonly owner: string;
  readonly fromRoute: string;
  readonly toRoute: string;
  readonly toType: PageType;
}

type Plan = Walk | { readonly transition: SiteGraphTransition; readonly advisory: string };

/** The Site state graph in `manualDir`, or `undefined` when the manual has none. */
export async function readSiteGraph(manualDir: string): Promise<SiteGraph | undefined> {
  const file = path.join(manualDir, SITE_GRAPH_FILE);
  if (!(await exists(file))) {
    return undefined;
  }
  return parseSiteGraph(JSON.parse(await fs.readFile(file, 'utf-8')));
}

export function siteGraphVerifier(options: SiteGraphVerifierOptions): Verifier {
  const plans = planTransitions(options.graph);
  const owners = new Set(plans.flatMap((plan) => ('owner' in plan ? [plan.owner] : [])));
  return {
    name: SITE_GRAPH_NAME,
    appliesTo: (taskId) => taskId === ALL_TRANSITIONS_TASK || owners.has(taskId),
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const blocked = await prepareTarget(options.target);
      if (blocked !== undefined) {
        return blocked;
      }
      const values = placeholderValues(await readDatasetHandles(options.dataDir));
      const client = new StorefrontClient({
        baseUrl: options.target.url,
        episodeId: `site-graph-${ctx.iterId}`,
      });
      const transitions: TransitionCheck[] = [];
      for (const plan of plans) {
        if (!('owner' in plan)) {
          transitions.push(record(plan.transition, 'advisory', { reason: plan.advisory }));
        } else if (
          ctx.selectedTaskId === ALL_TRANSITIONS_TASK ||
          ctx.selectedTaskId === plan.owner
        ) {
          transitions.push(await walk(client, plan, values));
        }
      }
      const failures = transitions.filter((check) => check.status === 'fail');
      const details = { transitions };
      if (failures.length === 0) {
        return { verdict: 'pass', details };
      }
      return { verdict: 'fail', feedback: renderFailures(failures), details };
    },
  };
}

/** Each transition of `graph`, in graph order, as a walk or with its advisory reason. */
function planTransitions(graph: SiteGraph): Plan[] {
  const states = new Map(graph.states.map((state) => [state.id, state]));
  const stateOf = (id: string): SiteGraphState => {
    const state = states.get(id);
    if (state === undefined) {
      throw new Error(`site graph transition names no state: ${id}`);
    }
    return state;
  };
  return graph.transitions.map((transition): Plan => {
    const advisory = (reason: string): Plan => ({ transition, advisory: reason });
    const from = stateOf(transition.from);
    const to = stateOf(transition.to);
    if (from.kind === 'overlay' || to.kind === 'overlay') {
      return advisory(
        'an overlay names only its kind and host pages, so its control on the built shop is not known',
      );
    }
    if (transition.effect !== 'navigate') {
      return advisory(`the \`${transition.effect}\` effect does not go to another page`);
    }
    if (transition.trigger === 'load') {
      return advisory('a load transition has no shopper control to follow');
    }
    const fromRule = PAGE_TYPE_RULES[from.page_type];
    if (fromRule.kind !== 'checked') {
      return advisory(`\`${from.page_type}\` page: ${fromRule.advisory}`);
    }
    const toRule = PAGE_TYPE_RULES[to.page_type];
    if (toRule.kind === 'advisory') {
      return advisory(`\`${to.page_type}\` page: ${toRule.advisory}`);
    }
    return {
      transition,
      owner: fromRule.owner,
      fromRoute: fromRule.route,
      toRoute: toRule.route,
      toType: to.page_type,
    };
  });
}

/** The Dataset value of each `{name}` of a walked `from` route; `undefined` when it has none. */
function placeholderValues(handles: DatasetHandles): Readonly<Record<string, string | undefined>> {
  const collection =
    handles.collections.find((entry) => entry.productHandles.length > 0) ?? handles.collections[0];
  return {
    collection: collection?.handle,
    product: sampleProductHandles(handles, DEFAULT_CAPS)[0],
    query: searchToken(handles),
    policy: handles.policies[0],
  };
}

const PLACEHOLDER_RE = /\{([a-z_]+)\}/g;

/** `route` with each `{name}` filled from `values`; `undefined` when a value is missing. */
function fillRoute(
  route: string,
  values: Readonly<Record<string, string | undefined>>,
): string | undefined {
  let missing = false;
  const url = route.replace(PLACEHOLDER_RE, (_, name: string) => {
    const value = values[name];
    if (value === undefined || value === '') {
      missing = true;
      return '';
    }
    return encodeURIComponent(value);
  });
  return missing ? undefined : url;
}

/** The path of `route` (no query), as a pattern in which each `{name}` is one path segment. */
function routePattern(route: string): RegExp {
  const routePath = route.replace(/\?.*$/, '');
  const parts = routePath.split(PLACEHOLDER_RE).filter((_, index) => index % 2 === 0);
  return new RegExp(`^${parts.map(escapeRegExp).join('[^/]+')}$`);
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Any origin: the walk keeps only targets on the origin of the page. */
const PAGE_ORIGIN = 'http://storefront.invalid';
const CONTROL_RE = /<(a|form)\b([^>]*)>/gi;

/**
 * The same-origin targets (path and query) of the links and forms of a
 * page, in page order. A form with no `action` targets its own page.
 */
function controlTargets(html: string, pageUrl: string): string[] {
  const base = new URL(pageUrl, PAGE_ORIGIN);
  const targets: string[] = [];
  for (const [, tag = '', attrs = ''] of html.matchAll(CONTROL_RE)) {
    const isLink = tag.toLowerCase() === 'a';
    const value = new RegExp(`\\s${isLink ? 'href' : 'action'}="([^"]*)"`, 'i').exec(attrs)?.[1];
    if (value === undefined && isLink) {
      continue;
    }
    const href = (value ?? '').replaceAll('&amp;', '&');
    if (!URL.canParse(href, base)) {
      continue;
    }
    const resolved = new URL(href, base);
    if (resolved.origin === base.origin) {
      targets.push(`${resolved.pathname}${resolved.search}`);
    }
  }
  return targets;
}

/**
 * Loads the built page of `from`, finds the first control that leads to
 * the built route of `to`, and loads its target. A control back to the
 * same URL counts only when the route of `to` has no `{name}` part: then
 * the type has one page, and a link to itself goes to that page (the
 * logo on the home page). Otherwise it does not go to another page of the
 * type.
 */
async function walk(
  client: StorefrontClient,
  plan: Walk,
  values: Readonly<Record<string, string | undefined>>,
): Promise<TransitionCheck> {
  const url = fillRoute(plan.fromRoute, values);
  if (url === undefined) {
    return record(plan.transition, 'advisory', {
      reason: `the Dataset has no value for \`${plan.fromRoute}\``,
    });
  }
  const page = await client.get(url);
  if (page.status !== 200) {
    return record(plan.transition, 'fail', {
      url,
      reason: `\`${url}\` returned ${page.status}.\n  body: ${bodyExcerpt(page.body)}`,
    });
  }
  const pattern = routePattern(plan.toRoute);
  const onePage = !plan.toRoute.includes('{');
  const target = controlTargets(page.body, url).find(
    (candidate) => (onePage || candidate !== url) && pattern.test(candidate.replace(/\?.*$/, '')),
  );
  if (target === undefined) {
    const route = plan.toRoute.replace(/\?.*$/, '');
    return record(plan.transition, 'fail', {
      url,
      reason: `no link or form on \`${url}\` leads to a ${plan.toType} page (\`${route}\`).`,
    });
  }
  const landed = await client.get(target);
  if (landed.status !== 200) {
    return record(plan.transition, 'fail', {
      url,
      target,
      reason: `\`${target}\`, linked from \`${url}\`, returned ${landed.status}.\n  body: ${bodyExcerpt(landed.body)}`,
    });
  }
  return record(plan.transition, 'pass', { url, target });
}

function record(
  transition: SiteGraphTransition,
  status: TransitionCheck['status'],
  fields: Pick<TransitionCheck, 'reason' | 'url' | 'target'>,
): TransitionCheck {
  return { from: transition.from, to: transition.to, action: transition.action, status, ...fields };
}

function renderFailures(failures: readonly TransitionCheck[]): string {
  return [
    `\`site_graph\`: ${failures.length} transition(s) of the Site state graph do not work on the built shop.`,
    'Each one is a move that a shopper makes on the source shop. Give the first page a link or a form whose target is a page of the second type, and make sure that the target answers 200.',
    '',
    ...failures.map(
      (failure) =>
        `- \`${failure.from}\` -> \`${failure.to}\` (\`${failure.action}\`): ${failure.reason ?? ''}`,
    ),
  ].join('\n');
}
