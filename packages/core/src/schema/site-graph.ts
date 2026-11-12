/**
 * Site state graph contract.
 *
 * A Site state graph models how a shopper moves through one storefront,
 * like a UX prototype. Its states are pages and overlays: a page has a
 * page type and a URL pattern, and an overlay (a modal, a side sheet, a
 * popover, a dropdown or a flyout) names the page states it opens on. Its
 * transitions go from one state to another: each one has a trigger, an
 * action kind, an effect, optional params and needs, and the Plan task
 * whose part shows it. States are abstract, one per page type and URL
 * shape, with no product ids, names or site text.
 *
 * The schema is closed: an unknown field or an unknown list value fails.
 * Field names are snake_case, as in the published file `site_graph.json`.
 */

import { z } from 'zod';

/** The page types of a storefront. */
export const PAGE_TYPES = [
  'home',
  'collection',
  'product',
  'search',
  'cart',
  'page',
  'policy',
  'login',
  'register',
  'account',
  'addresses',
  'order_detail',
  'checkout',
  'checkout_confirmation',
  'other',
] as const;

/** The kinds of overlay state. */
export const OVERLAY_KINDS = ['modal', 'side_sheet', 'popover', 'dropdown', 'flyout'] as const;

/** The inputs that start a transition. */
export const TRANSITION_TRIGGERS = ['click', 'hover', 'type', 'submit', 'key'] as const;

/** What a transition changes. */
export const TRANSITION_EFFECTS = [
  'navigate',
  'open_overlay',
  'swap_overlay',
  'close_overlay',
  'update_in_place',
] as const;

export const SITE_GRAPH_VERSION = '0.1';

/** A state id, an action kind, a param or a need. */
const snakeCaseSchema = z
  .string()
  .regex(/^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/, 'expected a snake_case name');

/** A Plan task id. */
const planTaskIdSchema = z.string().regex(/^[a-z0-9_]+$/, 'expected a Plan task id');

const pageStateSchema = z.strictObject({
  id: snakeCaseSchema,
  kind: z.literal('page'),
  page_type: z.enum(PAGE_TYPES),
  /** The path of the page, with `{name}` placeholders, for example `/products/{handle}`. */
  url_pattern: z.string(),
});

const overlayStateSchema = z.strictObject({
  id: snakeCaseSchema,
  kind: z.literal('overlay'),
  overlay: z.enum(OVERLAY_KINDS),
  /** The ids of the page states that the overlay opens on. */
  on: z.array(snakeCaseSchema),
});

const stateSchema = z.discriminatedUnion('kind', [pageStateSchema, overlayStateSchema]);

const transitionSchema = z.strictObject({
  from: snakeCaseSchema,
  to: snakeCaseSchema,
  trigger: z.enum(TRANSITION_TRIGGERS),
  /** The action kind, for example `open_result` or `add_to_cart`. */
  action: snakeCaseSchema,
  effect: z.enum(TRANSITION_EFFECTS),
  /** The values that the action takes, for example `query` for a search. */
  params: z.array(snakeCaseSchema).optional(),
  /** What an earlier step must give, for example `variant` before add to cart. */
  needs: z.array(snakeCaseSchema).optional(),
  /** The Plan task whose part shows the transition. */
  source: planTaskIdSchema,
});

export const siteGraphSchema = z.strictObject({
  version: z.literal(SITE_GRAPH_VERSION),
  states: z.array(stateSchema),
  transitions: z.array(transitionSchema),
});

export type PageType = (typeof PAGE_TYPES)[number];
export type OverlayKind = (typeof OVERLAY_KINDS)[number];
export type TransitionTrigger = (typeof TRANSITION_TRIGGERS)[number];
export type TransitionEffect = (typeof TRANSITION_EFFECTS)[number];
export type SiteGraphState = z.infer<typeof stateSchema>;
export type SiteGraphTransition = z.infer<typeof transitionSchema>;
export type SiteGraph = z.infer<typeof siteGraphSchema>;

/** A Site state graph broke the schema or a graph rule. */
export class SiteGraphValidationError extends Error {
  constructor(readonly problems: readonly string[]) {
    super(
      [
        `the site state graph has ${problems.length} problem(s):`,
        ...problems.map((problem) => `- ${problem}`),
      ].join('\n'),
    );
    this.name = 'SiteGraphValidationError';
  }
}

/** `states[0].page_type` for the path `['states', 0, 'page_type']`, and `graph` for the root. */
function formatPath(path: readonly PropertyKey[]): string {
  if (path.length === 0) return 'graph';
  return path
    .map((key, index) =>
      typeof key === 'number' ? `[${key}]` : `${index === 0 ? '' : '.'}${String(key)}`,
    )
    .join('');
}

/**
 * One schema problem. A string, number or boolean that the schema refused
 * is shown, because a failed check publishes no file that would show it.
 */
function formatIssue(issue: z.core.$ZodIssue): string {
  const input: unknown = issue.input;
  const got = ['string', 'number', 'boolean'].includes(typeof input)
    ? ` (got ${JSON.stringify(input)})`
    : '';
  return `${formatPath(issue.path)}: ${issue.message}${got}`;
}

/** The graph rules that a schema cannot express: unique state ids, and no dangling transition. */
function graphProblems(graph: SiteGraph): string[] {
  const ids = new Set<string>();
  const repeated = new Set<string>();
  for (const state of graph.states) {
    (ids.has(state.id) ? repeated : ids).add(state.id);
  }
  const problems = [...repeated].map((id) => `state id ${JSON.stringify(id)} is repeated`);
  graph.transitions.forEach((transition, index) => {
    for (const end of ['from', 'to'] as const) {
      if (!ids.has(transition[end])) {
        const id = JSON.stringify(transition[end]);
        problems.push(`transitions[${index}].${end} names no state: ${id}`);
      }
    }
  });
  return problems;
}

/**
 * Checks a Site state graph against the closed schema. When the schema
 * passes, it checks that the state ids are unique and that each
 * transition goes from a state to a state.
 *
 * @throws SiteGraphValidationError that lists every schema problem, or,
 *   when the schema passes, every repeated id and dangling transition.
 */
export function parseSiteGraph(value: unknown): SiteGraph {
  const result = siteGraphSchema.safeParse(value, { reportInput: true });
  if (!result.success) {
    throw new SiteGraphValidationError(result.error.issues.map(formatIssue));
  }
  const problems = graphProblems(result.data);
  if (problems.length > 0) throw new SiteGraphValidationError(problems);
  return result.data;
}
