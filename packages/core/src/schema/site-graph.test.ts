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

/** `GRAPH` with `transitions` added after its own. */
function withAddedTransitions(...transitions: readonly Record<string, unknown>[]): unknown {
  return { ...GRAPH, transitions: [...GRAPH.transitions, ...transitions] };
}

/** A click transition with `effect` from `from` to `to`, shown by the `account_pages` part. */
function clickTransition(from: string, to: string, effect: string): Record<string, unknown> {
  return { from, to, trigger: 'click', action: 'test_action', effect, source: 'account_pages' };
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
    ['triggers', TRANSITION_TRIGGERS, ['click', 'hover', 'type', 'submit', 'key', 'load']],
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

  describe('URL patterns', () => {
    it.each([
      '/collections/{handle}?sort_by={sort}&page={page}',
      '/collections/{handle}?filter.v.price.gte={min_price}',
    ])('accepts %s', (urlPattern) => {
      expect(() => parseSiteGraph(withState(2, { url_pattern: urlPattern }))).not.toThrow();
    });

    const ONE_SLASH = 'expected a path that starts with one "/", with no scheme or host';
    const PLACEHOLDERS = 'expected snake_case {name} placeholders only';
    const QUERY_VALUES = 'expected a {name} placeholder for each query value';
    it.each([
      ['products/{handle}', ONE_SLASH],
      ['https://shop.example/products/{handle}', ONE_SLASH],
      ['//shop.example/products/{handle}', ONE_SLASH],
      ['/out/https://shop.example/products/{handle}', ONE_SLASH],
      ['/products/{productHandle}', PLACEHOLDERS],
      ['/products/{handle', PLACEHOLDERS],
      ['/search?q=shoes', QUERY_VALUES],
      ['/search?q={query}&ref=nav', QUERY_VALUES],
      ['/search?q={query}&utm', QUERY_VALUES],
    ])('rejects %s and names the rule', (urlPattern, rule) => {
      expect(validationError(withState(2, { url_pattern: urlPattern })).problems).toEqual([
        `states[2].url_pattern: ${rule} (got ${JSON.stringify(urlPattern)})`,
      ]);
    });

    it('accepts two page states of different page types with the same path', () => {
      expect(() => parseSiteGraph(withState(1, { url_pattern: '/?q={query}' }))).not.toThrow();
    });

    it('rejects two page states of one page type with the same path and another query', () => {
      const graph = withState(1, {
        page_type: 'product',
        url_pattern: '/products/{id}?v={variant}',
      });
      expect(validationError(graph).problems).toEqual([
        'states[2].url_pattern has the same path as states[1].url_pattern, and both are "product" pages: "/products/{handle}"',
      ]);
    });

    it('gives one problem for two page states of one page type with one URL pattern', () => {
      const graph = withState(1, { page_type: 'product', url_pattern: '/products/{id}' });
      expect(validationError(graph).problems).toEqual([
        'states[2].url_pattern matches the same URLs as states[1].url_pattern: "/products/{handle}"',
      ]);
    });

    it.each([
      ['the same URL pattern', '/products/{handle}'],
      ['a URL pattern with other placeholder names', '/products/{id}'],
    ])('rejects two page states with %s', (_name, urlPattern) => {
      expect(validationError(withState(1, { url_pattern: urlPattern })).problems).toEqual([
        'states[2].url_pattern matches the same URLs as states[1].url_pattern: "/products/{handle}"',
      ]);
    });
  });

  describe('params and needs', () => {
    it('accepts params and needs with no repeated item', () => {
      const graph = withTransition(3, { params: ['quantity'], needs: ['variant', 'size'] });
      expect(() => parseSiteGraph(graph)).not.toThrow();
    });

    it.each([
      [
        'params',
        withTransition(0, { params: ['query', 'query'] }),
        'transitions[0].params: "query" is repeated',
      ],
      [
        'needs',
        withTransition(3, { needs: ['variant', 'size', 'variant'] }),
        'transitions[3].needs: "variant" is repeated',
      ],
    ])('rejects %s with a repeated item', (_name, graph, problem) => {
      expect(validationError(graph).problems).toEqual([problem]);
    });
  });

  describe('unused states', () => {
    const CART = { id: 'cart', kind: 'page', page_type: 'cart', url_pattern: '/cart' };

    it('accepts a state that is only the from of a transition', () => {
      const graph = {
        ...GRAPH,
        states: [...GRAPH.states, CART],
        transitions: [...GRAPH.transitions, clickTransition('cart', 'home', 'navigate')],
      };
      expect(() => parseSiteGraph(graph)).not.toThrow();
    });

    it.each([
      [
        'a page state that only hosts an overlay',
        {
          ...GRAPH,
          states: [
            ...GRAPH.states.map((state) =>
              state.id === 'cart_drawer' ? { ...state, on: ['product', 'cart'] } : state,
            ),
            CART,
          ],
        },
        'no transition starts or ends on state "cart"',
      ],
      [
        'an overlay state',
        {
          ...GRAPH,
          states: [
            ...GRAPH.states,
            { id: 'menu_flyout', kind: 'overlay', overlay: 'flyout', on: ['home'] },
          ],
        },
        'no transition starts or ends on state "menu_flyout"',
      ],
    ])('rejects %s that no transition uses', (_name, graph, problem) => {
      expect(validationError(graph).problems).toEqual([problem]);
    });
  });

  describe('the host pages of an overlay', () => {
    it('accepts an overlay that opens on every page', () => {
      expect(() =>
        parseSiteGraph(withState(3, { on: ['home', 'search', 'product'] })),
      ).not.toThrow();
    });

    it.each([
      [
        'no host page',
        withState(3, { on: [] }),
        'states[3].on: expected one or more page state ids',
      ],
      [
        'a host that names no state',
        withState(3, { on: ['product', 'collection'] }),
        'states[3].on names no page state: "collection"',
      ],
      [
        'a host that is an overlay',
        withState(3, { on: ['product', 'sign_in_modal'] }),
        'states[3].on names no page state: "sign_in_modal"',
      ],
    ])('rejects an overlay with %s', (_name, graph, problem) => {
      expect(validationError(graph).problems).toEqual([problem]);
    });
  });

  describe('the effect rules', () => {
    it.each([
      [
        'a navigate transition from an overlay',
        withAddedTransitions(clickTransition('cart_drawer', 'search', 'navigate')),
      ],
      [
        'an update_in_place transition on an overlay',
        withAddedTransitions(clickTransition('cart_drawer', 'cart_drawer', 'update_in_place')),
      ],
      [
        'a swap_overlay transition to an overlay with other host pages',
        withAddedTransitions(clickTransition('sign_in_modal', 'cart_drawer', 'swap_overlay')),
      ],
      [
        'open_overlay and close_overlay transitions on a second host page',
        {
          ...GRAPH,
          states: GRAPH.states.map((state) =>
            state.id === 'cart_drawer' ? { ...state, on: ['product', 'search'] } : state,
          ),
          transitions: [
            ...GRAPH.transitions,
            clickTransition('search', 'cart_drawer', 'open_overlay'),
            clickTransition('cart_drawer', 'search', 'close_overlay'),
          ],
        },
      ],
    ])('accepts %s', (_name, graph) => {
      expect(() => parseSiteGraph(graph)).not.toThrow();
    });

    it.each([
      [
        'a navigate transition that ends on an overlay',
        withTransition(1, { to: 'sign_in_modal' }),
        'transitions[1] goes from "search" to "sign_in_modal": a navigate transition ends on a page',
      ],
      [
        'an open_overlay transition that ends on a page',
        withTransition(4, { to: 'search' }),
        'transitions[4] goes from "home" to "search": an open_overlay transition ends on an overlay',
      ],
      [
        'an open_overlay transition that starts on a page that does not host the overlay',
        withTransition(4, { from: 'search' }),
        'transitions[4] goes from "search" to "sign_in_modal": an open_overlay transition starts on one of the host pages of its overlay',
      ],
      [
        'an open_overlay transition that starts on an overlay',
        withTransition(3, { from: 'register_modal' }),
        'transitions[3] goes from "register_modal" to "cart_drawer": an open_overlay transition starts on one of the host pages of its overlay',
      ],
      [
        'a swap_overlay transition that starts on a page',
        withTransition(5, { from: 'home' }),
        'transitions[5] goes from "home" to "register_modal": a swap_overlay transition starts on an overlay',
      ],
      [
        'a swap_overlay transition that ends on a page',
        withTransition(5, { to: 'home' }),
        'transitions[5] goes from "sign_in_modal" to "home": a swap_overlay transition ends on a different overlay',
      ],
      [
        'a swap_overlay transition that ends on the overlay where it starts',
        withTransition(5, { to: 'sign_in_modal' }),
        'transitions[5] goes from "sign_in_modal" to "sign_in_modal": a swap_overlay transition ends on a different overlay',
      ],
      [
        'a close_overlay transition that starts on a page',
        withTransition(6, { from: 'search' }),
        'transitions[6] goes from "search" to "home": a close_overlay transition starts on an overlay',
      ],
      [
        'a close_overlay transition that ends on a page that does not host the overlay',
        withTransition(6, { to: 'search' }),
        'transitions[6] goes from "register_modal" to "search": a close_overlay transition ends on one of the host pages of its overlay',
      ],
      [
        'an update_in_place transition that goes to another state',
        withTransition(2, { to: 'search' }),
        'transitions[2] goes from "product" to "search": an update_in_place transition has the same from and to',
      ],
    ])('rejects %s and names the rule', (_name, graph, problem) => {
      expect(validationError(graph).problems).toEqual([problem]);
    });
  });

  describe('repeated transitions', () => {
    it('accepts one action from one state to two states', () => {
      const graph = withAddedTransitions({ ...GRAPH.transitions[1], to: 'search' });
      expect(() => parseSiteGraph(graph)).not.toThrow();
    });

    it.each([
      ['the same transition', {}],
      ['another trigger and source', { trigger: 'key', source: 'related_products' }],
    ])('rejects a transition with the from, action and to of an earlier one: %s', (_name, edit) => {
      const graph = withAddedTransitions({ ...GRAPH.transitions[1], ...edit });
      expect(validationError(graph).problems).toEqual([
        'transitions[7] has the same from, action and to as transitions[1]: "search", "open_result", "product"',
      ]);
    });
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
