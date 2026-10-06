/**
 * `routes_200` verifier: every route the task touches answers, over HTTP,
 * the way a shopper would see it. Static routes and the task's dataset
 * routes return 200; account pages redirect to the login page when logged
 * out and return 200 after logging in as the seeded customer; `/checkout`
 * returns 200 with a non-empty cart; internal links found in the rendered
 * pages do not 4xx/5xx.
 */

import type { Verifier, VerifierContext, VerifierResult } from '@shop-gym/harness';

import {
  type HttpResult,
  StorefrontClient,
  bodyExcerpt,
  firstAvailableMerchandiseId,
} from './http.js';
import {
  type SeededCustomer,
  type StorefrontTarget,
  prepareTarget,
  readSeededCustomer,
} from './storefront_target.js';
import {
  ALL_BUCKETS,
  type BucketCaps,
  SWEEP_CAPS,
  bucketsForTask,
  isStorefrontTask,
  readDatasetHandles,
  routesForBuckets,
  sampleProductHandles,
} from './task_routes.js';

export const ROUTES_200_NAME = 'routes_200';
const STATIC_ROUTES = [
  '/',
  '/collections',
  '/search',
  '/cart',
  '/account/login',
  '/account/register',
];
const ACCOUNT_ROUTES = ['/account', '/account/orders', '/account/addresses'];
const LOGIN_PREFIX = '/account/login';
const MAX_LINK_PROBES = 40;
const LINK_RE = /href="(\/[^"#?]*(?:\?[^"#]*)?)"/g;

export interface RouteProbe {
  readonly route: string;
  readonly expected: string;
  readonly ok: boolean;
  readonly status: number;
  readonly location: string;
  /** Short tag-stripped body excerpt, only on failure. */
  readonly excerpt?: string;
}

export interface Routes200Options {
  readonly target: StorefrontTarget;
  readonly dataDir: string;
  readonly caps?: BucketCaps;
}

export function routes200Verifier(options: Routes200Options): Verifier {
  const caps = options.caps ?? SWEEP_CAPS;
  return {
    name: ROUTES_200_NAME,
    appliesTo: isStorefrontTask,
    async run(ctx: VerifierContext): Promise<VerifierResult> {
      const blocked = await prepareTarget(options.target);
      if (blocked !== undefined) {
        return blocked;
      }
      const handles = await readDatasetHandles(options.dataDir);
      const customer = await readSeededCustomer(options.dataDir);
      const buckets = bucketsForTask(ctx.selectedTaskId);
      const taskRoutes = routesForBuckets(
        buckets.length > 0 ? buckets : ALL_BUCKETS,
        handles,
        caps,
      );
      const guest = new StorefrontClient({
        baseUrl: options.target.url,
        episodeId: `routes-200-${ctx.iterId}`,
      });
      const probes: RouteProbe[] = [];
      const bodies: string[] = [];

      // Member-only account routes are probed below in both sessions.
      const guestRoutes = new Set(
        [...STATIC_ROUTES, ...taskRoutes].filter((route) => !ACCOUNT_ROUTES.includes(route)),
      );
      for (const route of guestRoutes) {
        const result = await guest.get(route);
        probes.push(probe(route, 'status 200', result.status === 200, result));
        if (result.status === 200) {
          bodies.push(result.body);
        }
      }
      for (const route of ACCOUNT_ROUTES) {
        const result = await guest.get(route);
        const ok = result.status === 302 && result.location.startsWith(LOGIN_PREFIX);
        probes.push(probe(route, `302 to ${LOGIN_PREFIX} when logged out`, ok, result));
      }
      const seen = new Set(probes.map((p) => p.route));
      for (const link of internalLinks(bodies)
        .filter((l) => !seen.has(l))
        .slice(0, MAX_LINK_PROBES)) {
        const result = await guest.get(link);
        const ok = result.status === 200 || result.status === 302;
        probes.push(probe(link, 'linked page answers 200 or 302', ok, result));
      }
      probes.push(...(await checkoutProbes(guest, handles)));
      if (customer !== undefined) {
        probes.push(...(await loggedInProbes(options.target.url, ctx.iterId, customer)));
      }

      const failures = probes.filter((p) => !p.ok);
      const details = { probes, loggedInChecks: customer !== undefined };
      if (failures.length === 0) {
        return { verdict: 'pass', details };
      }
      return { verdict: 'fail', feedback: renderFailures(failures), details };
    },
  };
}

async function checkoutProbes(
  guest: StorefrontClient,
  handles: Awaited<ReturnType<typeof readDatasetHandles>>,
): Promise<RouteProbe[]> {
  const productHandle = sampleProductHandles(handles, SWEEP_CAPS)[0];
  if (productHandle === undefined) {
    return [];
  }
  const productRoute = `/products/${productHandle}`;
  const page = await guest.get(productRoute);
  const merchandiseId = firstAvailableMerchandiseId(page.body);
  if (merchandiseId === undefined) {
    return [probe(productRoute, 'an enabled merchandiseId radio to add to cart', false, page)];
  }
  await guest.post('/cart', { intent: 'add', merchandiseId, quantity: '1' });
  const checkout = await guest.get('/checkout');
  return [
    probe('/checkout', 'status 200 with a non-empty cart', checkout.status === 200, checkout),
  ];
}

async function loggedInProbes(
  baseUrl: string,
  iterId: string,
  customer: SeededCustomer,
): Promise<RouteProbe[]> {
  const member = new StorefrontClient({ baseUrl, episodeId: `routes-200-${iterId}` });
  const login = await member.post('/account/login', {
    email: customer.email,
    password: customer.password,
  });
  const probes = [
    probe(
      '/account/login',
      'POST with the seeded credentials redirects to /account',
      login.status === 302 && login.location === '/account',
      login,
    ),
  ];
  for (const route of ACCOUNT_ROUTES) {
    const result = await member.get(route);
    probes.push(probe(route, 'status 200 when logged in', result.status === 200, result));
  }
  return probes;
}

function probe(route: string, expected: string, ok: boolean, result: HttpResult): RouteProbe {
  return {
    route,
    expected,
    ok,
    status: result.status,
    location: result.location,
    ...(ok ? {} : { excerpt: bodyExcerpt(result.body) }),
  };
}

/** Same-origin `href` paths in rendered pages, except logout, in first-seen order. */
export function internalLinks(bodies: readonly string[]): string[] {
  const links = new Set<string>();
  for (const body of bodies) {
    for (const [, href] of body.matchAll(LINK_RE)) {
      if (href !== undefined && !href.startsWith('//') && href !== '/account/logout') {
        links.add(href);
      }
    }
  }
  return [...links];
}

function renderFailures(failures: readonly RouteProbe[]): string {
  const lines = [`\`routes_200\`: ${failures.length} route(s) did not answer as expected.`, ''];
  for (const failure of failures) {
    const location = failure.location === '' ? '' : ` -> ${failure.location}`;
    lines.push(
      `- \`${failure.route}\`: expected ${failure.expected}; got ${failure.status}${location}`,
    );
    if (failure.excerpt !== undefined && failure.excerpt !== '') {
      lines.push(`  body: ${failure.excerpt}`);
    }
  }
  return lines.join('\n');
}
