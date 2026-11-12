import { describe, expect, it } from 'vitest';

import {
  OVERLAY_KINDS,
  PAGE_TYPES,
  SiteGraphValidationError,
  TRANSITION_EFFECTS,
  TRANSITION_TRIGGERS,
  parseSiteGraph,
} from './site-graph.js';

/** A small graph with page and overlay states and one transition of each effect. */
const GRAPH = {
  version: '0.1',
  states: [
    { id: 'home', kind: 'page', page_type: 'home', url_pattern: '/' },
    { id: 'search', kind: 'page', page_type: 'search', url_pattern: '/search?q={query}' },
    { id: 'product', kind: 'page', page_type: 'product', url_pattern: '/products/{handle}' },
    { id: 'cart_drawer', kind: 'overlay', overlay: 'side_sheet', on: ['product'] },
    { id: 'sign_in_modal', kind: 'overlay', overlay: 'modal', on: ['home'] },
    { id: 'register_modal', kind: 'overlay', overlay: 'modal', on: ['home'] },
  ],
  transitions: [
    {
      from: 'home',
      to: 'search',
      trigger: 'submit',
      action: 'search',
      effect: 'navigate',
      params: ['query'],
      source: 'search_results',
    },
    {
      from: 'search',
      to: 'product',
      trigger: 'click',
      action: 'open_result',
      effect: 'navigate',
      source: 'search_results',
    },
    {
      from: 'product',
      to: 'product',
      trigger: 'click',
      action: 'choose_variant',
      effect: 'update_in_place',
      source: 'product_variants',
    },
    {
      from: 'product',
      to: 'cart_drawer',
      trigger: 'click',
      action: 'add_to_cart',
      effect: 'open_overlay',
      needs: ['variant'],
      source: 'cart_drawer',
    },
    {
      from: 'home',
      to: 'sign_in_modal',
      trigger: 'click',
      action: 'open_sign_in',
      effect: 'open_overlay',
      source: 'account_pages',
    },
    {
      from: 'sign_in_modal',
      to: 'register_modal',
      trigger: 'click',
      action: 'switch_to_register',
      effect: 'swap_overlay',
      source: 'account_pages',
    },
    {
      from: 'register_modal',
      to: 'home',
      trigger: 'key',
      action: 'close_modal',
      effect: 'close_overlay',
      source: 'account_pages',
    },
  ],
};

/** `GRAPH` with its state at `index` changed by `edit`. */
function withState(index: number, edit: Record<string, unknown>): unknown {
  return { ...GRAPH, states: GRAPH.states.map((s, i) => (i === index ? { ...s, ...edit } : s)) };
}

/** `GRAPH` with its transition at `index` changed by `edit`. */
function withTransition(index: number, edit: Record<string, unknown>): unknown {
  return {
    ...GRAPH,
    transitions: GRAPH.transitions.map((t, i) => (i === index ? { ...t, ...edit } : t)),
  };
}

/** The error that `parseSiteGraph(value)` throws. */
function validationError(value: unknown): SiteGraphValidationError {
  try {
    parseSiteGraph(value);
  } catch (error) {
    expect(error).toBeInstanceOf(SiteGraphValidationError);
    return error as SiteGraphValidationError;
  }
  throw new Error('parseSiteGraph accepted the graph');
}

/** The message of the error that `parseSiteGraph(value)` throws. */
function problemsOf(value: unknown): string {
  return validationError(value).message;
}

describe('the closed lists', () => {
  it.each([
    [
      'page types',
      PAGE_TYPES,
      [
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
      ],
    ],
    ['overlay kinds', OVERLAY_KINDS, ['modal', 'side_sheet', 'popover', 'dropdown', 'flyout']],
    ['triggers', TRANSITION_TRIGGERS, ['click', 'hover', 'type', 'submit', 'key']],
    [
      'effects',
      TRANSITION_EFFECTS,
      ['navigate', 'open_overlay', 'swap_overlay', 'close_overlay', 'update_in_place'],
    ],
  ])('lists the %s', (_name, list, expected) => {
    expect(list).toEqual(expected);
  });

  it.each(PAGE_TYPES)('accepts the page type %s', (pageType) => {
    expect(() => parseSiteGraph(withState(0, { page_type: pageType }))).not.toThrow();
  });

  it.each(OVERLAY_KINDS)('accepts the overlay kind %s', (overlay) => {
    expect(() => parseSiteGraph(withState(3, { overlay }))).not.toThrow();
  });

  it.each(TRANSITION_TRIGGERS)('accepts the trigger %s', (trigger) => {
    expect(() => parseSiteGraph(withTransition(0, { trigger }))).not.toThrow();
  });

  it.each([
    ['an unknown page type', withState(0, { page_type: 'department' }), 'states[0].page_type'],
    ['an unknown overlay kind', withState(3, { overlay: 'toast' }), 'states[3].overlay'],
    ['an unknown state kind', withState(0, { kind: 'section' }), 'states[0].kind'],
    ['an unknown trigger', withTransition(0, { trigger: 'scroll' }), 'transitions[0].trigger'],
    ['an unknown effect', withTransition(0, { effect: 'reload' }), 'transitions[0].effect'],
  ])('rejects %s and names the field', (_name, graph, path) => {
    expect(problemsOf(graph)).toContain(`${path}:`);
  });

  it('shows the value that is not in the list', () => {
    expect(problemsOf(withState(0, { page_type: 'department' }))).toMatch(
      /states\[0\]\.page_type: .* \(got "department"\)$/m,
    );
  });
});

describe('the closed schema', () => {
  it.each([
    ['the graph', { ...GRAPH, weights: {} }, 'graph: Unrecognized key: "weights"'],
    ['a page state', withState(0, { name: 'Home' }), 'states[0]: Unrecognized key: "name"'],
    ['an overlay state', withState(3, { url_pattern: '/' }), 'states[3]: Unrecognized key'],
    ['a transition', withTransition(0, { label: 'Go' }), 'transitions[0]: Unrecognized key'],
  ])('rejects an unknown field of %s', (_name, graph, problem) => {
    expect(problemsOf(graph)).toContain(problem);
  });

  it('rejects another version', () => {
    expect(problemsOf({ ...GRAPH, version: '0.2' })).toContain('version:');
  });

  it('rejects a state id that is not snake_case', () => {
    expect(problemsOf(withState(0, { id: 'Home Page' }))).toContain(
      'states[0].id: expected a snake_case name',
    );
  });
});

describe('parseSiteGraph', () => {
  it('accepts a graph with page and overlay states and one transition of each effect', () => {
    expect(parseSiteGraph(GRAPH)).toEqual(GRAPH);
  });

  it('rejects a repeated state id', () => {
    expect(problemsOf(withState(2, { id: 'search' }))).toContain('state id "search" is repeated');
  });

  it.each([
    ['from', withTransition(1, { from: 'collection' }), 'transitions[1].from'],
    ['to', withTransition(1, { to: 'checkout' }), 'transitions[1].to'],
  ])('rejects a transition whose %s names no state', (_field, graph, path) => {
    expect(problemsOf(graph)).toMatch(
      new RegExp(`${path.replace(/[[\]]/g, '\\$&')} names no state: "`),
    );
  });

  it('lists every problem in one error', () => {
    const graph = {
      ...GRAPH,
      states: [
        ...GRAPH.states,
        { id: 'home', kind: 'page', page_type: 'other', url_pattern: '/x' },
      ],
      transitions: [
        ...GRAPH.transitions,
        { ...GRAPH.transitions[1], from: 'collection', to: 'checkout' },
      ],
    };
    expect(validationError(graph).problems).toEqual([
      'state id "home" is repeated',
      'transitions[7].from names no state: "collection"',
      'transitions[7].to names no state: "checkout"',
    ]);
  });
});
