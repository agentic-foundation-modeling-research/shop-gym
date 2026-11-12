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
 * `parseSiteGraph` also applies the graph rules: for example, a navigate
 * transition ends on a page, and an overlay opens only on page states.
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

/**
 * The inputs that start a transition. `load` is not a shopper input: the
 * site makes the change when the page loads, for example a prompt that
 * shows with no shopper action.
 */
export const TRANSITION_TRIGGERS = ['click', 'hover', 'type', 'submit', 'key', 'load'] as const;

/** What a transition changes. */
export const TRANSITION_EFFECTS = [
  'navigate',
  'open_overlay',
  'swap_overlay',
  'close_overlay',
  'update_in_place',
] as const;

export const SITE_GRAPH_VERSION = '0.1';

/** A snake_case name: a state id, an action kind, a param, a need or a URL placeholder. */
const SNAKE_CASE = '[a-z][a-z0-9]*(?:_[a-z0-9]+)*';

/** A state id, an action kind, a param or a need. */
const snakeCaseSchema = z
  .string()
  .regex(new RegExp(`^${SNAKE_CASE}$`), 'expected a snake_case name');

/** A list of params or needs, with no repeated item. */
const nameListSchema = z.array(snakeCaseSchema).superRefine((names, ctx) => {
  const seen = new Set<string>();
  const repeated = new Set<string>();
  for (const name of names) (seen.has(name) ? repeated : seen).add(name);
  for (const name of repeated) {
    ctx.addIssue({ code: 'custom', message: `${JSON.stringify(name)} is repeated` });
  }
});

/** A `{name}` placeholder of a URL pattern. */
const PLACEHOLDER_RE = new RegExp(`\\{${SNAKE_CASE}\\}`, 'g');
/** One query item of a URL pattern: a key, `=` and one placeholder. */
const QUERY_ITEM_RE = new RegExp(`^[^=&{}]+=\\{${SNAKE_CASE}\\}$`);

/** True when each item of the query of `pattern`, if it has one, is `key={name}`. */
function hasPlaceholderQueryValues(pattern: string): boolean {
  const start = pattern.indexOf('?');
  if (start === -1) return true;
  return pattern
    .slice(start + 1)
    .split('&')
    .every((item) => QUERY_ITEM_RE.test(item));
}

/**
 * The path of a page, for example `/products/{handle}` or
 * `/search?q={query}`. Each part that changes is a `{name}` placeholder.
 * Each query value is a placeholder too. Thus a URL pattern cannot hold
 * a session value or a tracking value. No `://` can come later in the
 * path, so a pattern cannot hold an absolute URL.
 */
const urlPatternSchema = z
  .string()
  .refine(
    (pattern) => /^\/(?!\/)/.test(pattern) && !pattern.includes('://'),
    'expected a path that starts with one "/", with no scheme or host',
  )
  .refine(
    (pattern) => !/[{}]/.test(pattern.replace(PLACEHOLDER_RE, '')),
    'expected snake_case {name} placeholders only',
  )
  .refine(hasPlaceholderQueryValues, 'expected a {name} placeholder for each query value');

/** A Plan task id. */
const planTaskIdSchema = z.string().regex(/^[a-z0-9_]+$/, 'expected a Plan task id');

const pageStateSchema = z.strictObject({
  id: snakeCaseSchema,
  kind: z.literal('page'),
  page_type: z.enum(PAGE_TYPES),
  url_pattern: urlPatternSchema,
});

const overlayStateSchema = z.strictObject({
  id: snakeCaseSchema,
  kind: z.literal('overlay'),
  overlay: z.enum(OVERLAY_KINDS),
  /** The ids of the page states that the overlay opens on. */
  on: z.array(snakeCaseSchema).min(1, 'expected one or more page state ids'),
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
  params: nameListSchema.optional(),
  /** What an earlier step must give, for example `variant` before add to cart. */
  needs: nameListSchema.optional(),
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

/** One rule on the two ends of the transitions of one effect. */
interface EffectRule {
  /** The rule as it shows in an error, for example `a navigate transition ends on a page`. */
  readonly rule: string;
  readonly holds: (from: SiteGraphState, to: SiteGraphState) => boolean;
}

/**
 * The rules on the two ends of a transition, for each effect. A host
 * page rule holds when the end that must be an overlay is a page. Then
 * the other rule of the effect fails, so the error shows one problem and
 * not two.
 */
const EFFECT_RULES: Readonly<Record<TransitionEffect, readonly EffectRule[]>> = {
  navigate: [
    { rule: 'a navigate transition ends on a page', holds: (_, to) => to.kind === 'page' },
  ],
  open_overlay: [
    {
      rule: 'an open_overlay transition ends on an overlay',
      holds: (_, to) => to.kind === 'overlay',
    },
    {
      rule: 'an open_overlay transition starts on one of the host pages of its overlay',
      holds: (from, to) => to.kind !== 'overlay' || to.on.includes(from.id),
    },
  ],
  swap_overlay: [
    {
      rule: 'a swap_overlay transition starts on an overlay',
      holds: (from) => from.kind === 'overlay',
    },
    {
      rule: 'a swap_overlay transition ends on a different overlay',
      holds: (from, to) => to.kind === 'overlay' && to.id !== from.id,
    },
  ],
  close_overlay: [
    {
      rule: 'a close_overlay transition starts on an overlay',
      holds: (from) => from.kind === 'overlay',
    },
    {
      rule: 'a close_overlay transition ends on one of the host pages of its overlay',
      holds: (from, to) => from.kind !== 'overlay' || from.on.includes(to.id),
    },
  ],
  update_in_place: [
    {
      rule: 'an update_in_place transition has the same from and to',
      holds: (from, to) => from.id === to.id,
    },
  ],
};

/**
 * The index stored for `key` in `firsts`. When `key` has no index yet, the
 * call stores `index` for it and returns undefined.
 */
function firstIndex(firsts: Map<string, number>, key: string, index: number): number | undefined {
  const first = firsts.get(key);
  if (first === undefined) firsts.set(key, index);
  return first;
}

/**
 * The state rules. Each overlay opens only on page states. No two page
 * states have one URL pattern. No two page states of one page type have
 * one path (the pattern before `?`): a query on a path, such as a filter,
 * a sort or a variant, does not make another state. Each state is the
 * `from` or `to` of a transition. Two URL patterns that differ only in
 * their placeholder names match the same URLs, so they count as one
 * pattern. Two page states of one page type with one URL pattern give
 * only the URL pattern problem.
 */
function stateProblems(graph: SiteGraph, states: ReadonlyMap<string, SiteGraphState>): string[] {
  const problems: string[] = [];
  /** The index of the first page state of each URL pattern, with no placeholder names. */
  const patterns = new Map<string, number>();
  /** The index of the first page state of each page type and path, with no placeholder names. */
  const typesAndPaths = new Map<string, number>();
  graph.states.forEach((state, index) => {
    if (state.kind === 'overlay') {
      for (const host of state.on) {
        if (states.get(host)?.kind !== 'page') {
          problems.push(`states[${index}].on names no page state: ${JSON.stringify(host)}`);
        }
      }
      return;
    }
    const pattern = state.url_pattern.replace(PLACEHOLDER_RE, '{}');
    const url = JSON.stringify(state.url_pattern);
    const samePattern = firstIndex(patterns, pattern, index);
    if (samePattern !== undefined) {
      problems.push(
        `states[${index}].url_pattern matches the same URLs as states[${samePattern}].url_pattern: ${url}`,
      );
      return;
    }
    const typeAndPath = `${state.page_type} ${pattern.replace(/\?.*/s, '')}`;
    const samePath = firstIndex(typesAndPaths, typeAndPath, index);
    if (samePath !== undefined) {
      const pageType = JSON.stringify(state.page_type);
      problems.push(
        `states[${index}].url_pattern has the same path as states[${samePath}].url_pattern, and both are ${pageType} pages: ${url}`,
      );
    }
  });
  const used = new Set(graph.transitions.flatMap((transition) => [transition.from, transition.to]));
  for (const id of states.keys()) {
    if (!used.has(id)) problems.push(`no transition starts or ends on state ${JSON.stringify(id)}`);
  }
  return problems;
}

/**
 * The transition rules: `from` and `to` name states, no two transitions
 * have the same `from`, `action` and `to`, and the two ends obey the
 * rules of the effect. The effect rules apply only when both ends name a
 * state.
 */
function transitionProblems(
  graph: SiteGraph,
  states: ReadonlyMap<string, SiteGraphState>,
): string[] {
  /** The index of the first transition of each `from`, `action` and `to`. */
  const firsts = new Map<string, number>();
  return graph.transitions.flatMap((transition, index) => {
    const problems: string[] = [];
    for (const end of ['from', 'to'] as const) {
      if (!states.has(transition[end])) {
        const id = JSON.stringify(transition[end]);
        problems.push(`transitions[${index}].${end} names no state: ${id}`);
      }
    }
    const edge = [transition.from, transition.action, transition.to];
    const first = firstIndex(firsts, JSON.stringify(edge), index);
    if (first !== undefined) {
      const names = edge.map((name) => JSON.stringify(name)).join(', ');
      problems.push(
        `transitions[${index}] has the same from, action and to as transitions[${first}]: ${names}`,
      );
    }
    const from = states.get(transition.from);
    const to = states.get(transition.to);
    if (from === undefined || to === undefined) return problems;
    for (const { rule, holds } of EFFECT_RULES[transition.effect]) {
      if (!holds(from, to)) {
        const ends = `from ${JSON.stringify(from.id)} to ${JSON.stringify(to.id)}`;
        problems.push(`transitions[${index}] goes ${ends}: ${rule}`);
      }
    }
    return problems;
  });
}

/**
 * The graph rules that a schema cannot express: unique state ids, then
 * the state rules, then the transition rules. When an id is repeated,
 * the first state with the id is the one that the rules check.
 */
function graphProblems(graph: SiteGraph): string[] {
  const states = new Map<string, SiteGraphState>();
  const repeated = new Set<string>();
  for (const state of graph.states) {
    if (states.has(state.id)) repeated.add(state.id);
    else states.set(state.id, state);
  }
  return [
    ...[...repeated].map((id) => `state id ${JSON.stringify(id)} is repeated`),
    ...stateProblems(graph, states),
    ...transitionProblems(graph, states),
  ];
}

/**
 * Checks a Site state graph in two phases.
 *
 * 1. The closed schema. It also checks single fields: the URL patterns,
 *    one or more host pages for each overlay, and no repeated params or
 *    needs.
 * 2. The graph rules. They run only when the schema passes. The state
 *    ids are unique. Each host page is a page state. No two page states
 *    have one URL pattern, and no two page states of one page type have
 *    one path. Each state is the end of a transition. Each transition
 *    goes from a state to a state, no two transitions have the same
 *    from, action and to, and each transition obeys the rules of its
 *    effect.
 *
 * @throws SiteGraphValidationError that lists every problem of the phase
 *   that fails.
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
