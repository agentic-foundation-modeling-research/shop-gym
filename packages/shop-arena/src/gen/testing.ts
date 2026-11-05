/**
 * Test doubles for the gen pipeline: a scripted `LlmClient` that answers
 * every synthesis prompt with a deterministic, schema-valid reply, a
 * scripted `LlmClient` for the fusion prompts, a scripted visual judge, a
 * stub storefront server for the HTTP verifiers and the final eval, and a
 * writer for a minimal Shop Manual fixture. No real merchant data.
 */

import * as fs from 'node:fs/promises';
import * as http from 'node:http';
import * as path from 'node:path';

import type { CompleteRequest, Completion, LlmClient } from '@shop-gym/agent';

import { capabilitiesSchema } from '../explore/capabilities.js';
import type { StorefrontLaunch } from './build/storefront_sidecar.js';

const JUDGE_USAGE = { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 };

/** JSON blocks of a rendered prompt, in order. */
function jsonBlocks(prompt: string): unknown[] {
  return [...prompt.matchAll(/```json\n([\s\S]*?)\n```/g)].map((m) => JSON.parse(m[1] ?? 'null'));
}

function handlesOf(value: unknown): string[] {
  return Array.isArray(value) ? value.map((v) => (v as { handle: string }).handle) : [];
}

export interface ScriptedSynthOptions {
  /** Vendor the first details reply uses for its first product; defaults to an allowlisted brand. */
  readonly firstVendor?: string;
  /** When true, the first personas reply gives every persona one address. */
  readonly singleAddressFirst?: boolean;
  /**
   * `discount_codes` of the first checkout rules replies, in order; later
   * replies use `SCRIPTED_DISCOUNT_CODES`.
   */
  readonly discountCodeReplies?: readonly (readonly unknown[])[];
}

/** The Discount codes of a checkout rules reply: one of each kind. */
export const SCRIPTED_DISCOUNT_CODES = [
  {
    code: 'WELCOME10',
    kind: 'percentage',
    amount: '10',
    minimum_subtotal: null,
    hint: '10% off your order',
  },
  {
    code: 'SAVE5',
    kind: 'fixed_amount',
    amount: '5.00',
    minimum_subtotal: '40.00',
    hint: '$5 off orders over $40',
  },
  {
    code: 'FREESHIP',
    kind: 'free_shipping',
    amount: '0',
    minimum_subtotal: null,
    hint: 'Free shipping on any order',
  },
] as const;

/**
 * Answers each `data_synth` prompt from its first line. Replies are derived
 * from the JSON blocks of the prompt so counts and handles always agree
 * with what the step asked for.
 */
export class ScriptedSynthLlm implements LlmClient {
  readonly requests: CompleteRequest[] = [];
  private detailsCalls = 0;
  private personaCalls = 0;
  private commerceCalls = 0;

  constructor(private readonly options: ScriptedSynthOptions = {}) {}

  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    if (typeof request.prompt !== 'string') {
      throw new Error('ScriptedSynthLlm: expected a string prompt');
    }
    return {
      text: JSON.stringify(this.reply(request.prompt)),
      model: request.model.id,
      stopReason: 'end_turn',
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
    };
  }

  private reply(prompt: string): unknown {
    const body = prompt.replace(/^[\s\S]*?Re-emit the JSON value from scratch[^\n]*\n\n/, '');
    const first = body.split('\n')[0] ?? '';
    const blocks = jsonBlocks(body);
    if (first.includes('brand identity')) {
      return {
        descriptor: 'Minimal Homeware Shop',
        tone: ['calm', 'warm'],
        currency: 'USD',
        country: 'US',
      };
    }
    if (first.includes('`store.json`')) {
      return {
        domain: 'shop.example',
        description: 'Homeware for calm rooms.',
        payment_settings: { accepted_card_brands: ['VISA', 'MASTERCARD'] },
        brand: { logo_url: null, colors: { primary: '#223344', secondary: '#eeeeee' } },
      };
    }
    if (first.includes('content pages')) {
      return [
        { handle: 'about-us', title: 'About Us', body_html: '<p>We make quiet things.</p>' },
        { handle: 'contact', title: 'Contact', body_html: '<p>Write to hello@shop.example.</p>' },
      ];
    }
    if (first.includes('policy pages')) {
      return ['privacy-policy', 'shipping-policy', 'terms-of-service', 'refund-policy'].map(
        (handle) => ({
          handle,
          title: handle.replace(/-/g, ' '),
          body_html: `<p>${handle}: standard shipping 5.00, free over 50.00, 30 day returns.</p>`,
        }),
      );
    }
    if (first.includes('checkout rules')) {
      this.commerceCalls += 1;
      return {
        tax_rate: 0.08,
        free_shipping_threshold: '50.00',
        shipping_methods: [
          { handle: 'standard', title: 'Standard', price: '5.00' },
          { handle: 'express', title: 'Express', price: '12.00' },
        ],
        payment_methods: [{ handle: 'card', title: 'Credit card' }],
        discount_codes:
          this.options.discountCodeReplies?.[this.commerceCalls - 1] ?? SCRIPTED_DISCOUNT_CODES,
      };
    }
    if (first.includes('collections (categories)')) {
      const count = Number(/exactly (\d+) collection/.exec(body)?.[1] ?? 1);
      const total = Number(/must equal (\d+)/.exec(body)?.[1] ?? count * 2);
      const per = Math.floor(total / count);
      return Array.from({ length: count }, (_, i) => ({
        title: `Collection ${i + 1}`,
        handle: `collection-${i + 1}`,
        description: `Everything in group ${i + 1}.`,
        sort_order: 'manual',
        target_product_count: i === count - 1 ? total - per * (count - 1) : per,
      }));
    }
    if (first.includes('catalog skeleton')) {
      const collections = blocks[0] as { handle: string; target_product_count: number }[];
      return collections.flatMap((c) =>
        Array.from({ length: c.target_product_count }, (_, i) => ({
          title: `Oak Bowl ${c.handle.split('-')[1]}${i + 1}`,
          handle: `${c.handle}-item-${i + 1}`,
          price: `${20 + i}.00`,
          collection_handle: c.handle,
        })),
      );
    }
    if (first.includes('rich product details')) {
      this.detailsCalls += 1;
      const skeletons = handlesOf(blocks[2]);
      return skeletons.map((handle, i) => ({
        handle,
        description_html: `<p>A sturdy ${handle.replace(/-/g, ' ')} for the table.</p>`,
        vendor:
          this.detailsCalls === 1 && i === 0
            ? (this.options.firstVendor ?? 'AisleArena')
            : 'AisleArena',
        product_type: 'Bowl',
        tags: ['bowl', 'oak'],
        options: [{ name: 'Size', position: 1, values: ['Small', 'Large'] }],
        variants: ['Small', 'Large'].map((size, p) => ({
          title: size,
          sku: `${handle}-${size.toLowerCase()}`,
          price: `${20 + p * 5}.00`,
          compare_at_price: null,
          available: true,
          option1: size,
          option2: null,
          option3: null,
          position: p + 1,
          requires_shipping: true,
        })),
      }));
    }
    if (first.includes('image alt-text')) {
      const perProduct = Number(/write (\d+) short/.exec(body)?.[1] ?? 1);
      return handlesOf(blocks[1]).map((handle) => ({
        handle,
        alts: Array.from(
          { length: perProduct },
          (_, i) => `Shot ${i + 1} of the ${handle} on a wooden bench.`,
        ),
      }));
    }
    if (first.includes('navigation menus')) {
      const collections = blocks[0] as { title: string; handle: string }[];
      const pages = blocks[1] as { title: string; handle: string }[];
      const policies = blocks[2] as { title: string; handle: string }[];
      return {
        'main-menu': [
          { title: 'Home', url: '/', type: 'HTTP', children: [] },
          ...collections.map((c) => ({
            title: c.title,
            url: `/collections/${c.handle}`,
            type: 'COLLECTION',
            children: [],
          })),
        ],
        footer: [
          ...pages.map((p) => ({
            title: p.title,
            url: `/pages/${p.handle}`,
            type: 'PAGE',
            children: [],
          })),
          ...policies.map((p) => ({
            title: p.title,
            url: `/policies/${p.handle}`,
            type: 'PAGE',
            children: [],
          })),
        ],
      };
    }
    if (first.includes('customer personas')) {
      const count = Number(/inventing (\d+) fictional/.exec(body)?.[1] ?? 5);
      this.personaCalls += 1;
      const single = this.personaCalls === 1 && this.options.singleAddressFirst === true;
      return Array.from({ length: count }, (_, i) => ({
        first_name: ['Jane', 'Omar', 'Lena', 'Kenji', 'Ana'][i] ?? `Person${i}`,
        last_name: ['Doe', 'Haddad', 'Berg', 'Sato', 'Silva'][i] ?? 'Example',
        phone: null,
        accepts_marketing: i === 0,
        // One, two or three addresses: 1, 2, 3, 1, 2, ...
        addresses: Array.from({ length: single ? 1 : (i % 3) + 1 }, (_, k) => ({
          address1: `${i + 1}${k} Example Street`,
          address2: null,
          city: ['Springfield', 'Shelbyville', 'Ogdenville'][k] ?? 'Springfield',
          province: 'Illinois',
          province_code: 'IL',
          zip: `627${i}${k}`,
        })),
      }));
    }
    throw new Error(`ScriptedSynthLlm: unrecognised prompt: ${first}`);
  }
}

/**
 * Answers the fusion prompts of `manual_merge`. For each section it gives
 * the queued replies first, in order, and then the prompt's standard text
 * unchanged.
 */
export class ScriptedFusionLlm implements LlmClient {
  readonly requests: CompleteRequest[] = [];
  private readonly calls = new Map<string, number>();

  /** @param replies Fused section bodies by section name, for example `{ Account: [body] }`. */
  constructor(private readonly replies: Readonly<Record<string, readonly string[]>> = {}) {}

  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    const match =
      typeof request.prompt === 'string'
        ? /## Standard text of `## (.+?)`\n\n([\s\S]*?)\n\n## Observed notes for /.exec(
            request.prompt,
          )
        : null;
    if (match?.[1] === undefined || match[2] === undefined) {
      throw new Error('ScriptedFusionLlm: expected a fusion prompt');
    }
    const [, section, standard] = match;
    const count = this.calls.get(section) ?? 0;
    this.calls.set(section, count + 1);
    return {
      text: this.replies[section]?.[count] ?? standard,
      model: request.model.id,
      stopReason: 'end_turn',
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 },
    };
  }
}

const MANUAL_MD = `# Shop Manual - Minimal Homeware Shop

## Overview

A compact homeware storefront with a drawer cart.

## Site shell

Single-row header with one link per collection.

## Homepage

Hero followed by a featured collection grid.

## Product page

Gallery on the left, buy box on the right.

## Cart

Drawer cart with a promo input.
`;

const NAVIGATION_PART_MD = `# Navigation

## Site shell

The header carries the logo and one link per collection. The footer is a
flat row of links: About, Privacy.
`;

/**
 * Writes `manual.md`, `capabilities.json`, `stats.json`, and
 * `parts/navigation.md` into `dir`.
 */
export async function writeManualFixture(
  dir: string,
  overrides: { descriptor?: string; tone?: string[] } = {},
): Promise<string> {
  await fs.mkdir(dir, { recursive: true });
  const capabilities = capabilitiesSchema.parse({
    shop: {
      descriptor: overrides.descriptor ?? 'Minimal Homeware Shop',
      currency: 'USD',
      tone: overrides.tone ?? ['calm'],
    },
    homepage: { section_types: ['hero', 'featured_collection'], section_count: 2 },
    cart: { type: 'drawer', has_promo_input: true },
  });
  await fs.mkdir(path.join(dir, 'parts'), { recursive: true });
  await fs.writeFile(path.join(dir, 'manual.md'), MANUAL_MD);
  await fs.writeFile(path.join(dir, 'parts', 'navigation.md'), NAVIGATION_PART_MD);
  await fs.writeFile(path.join(dir, 'capabilities.json'), JSON.stringify(capabilities, null, 2));
  await fs.writeFile(
    path.join(dir, 'stats.json'),
    JSON.stringify({
      products_total: 40,
      collections_total: 4,
      products_per_collection: { avg: 10, median: 10, max: 12 },
      price: { min: 10, max: 120, median: 35, currency: 'USD' },
      products_with_variants_pct: 50,
      variant_axes_observed: ['Size'],
      navigation_depth_max: 1,
      homepage_section_count: 2,
      info_pages_count: 2,
      feature_count: 4,
    }),
  );
  return dir;
}

/**
 * Answers every visual-judge prompt with a passing verdict, except pages
 * whose route starts with `/search`, which fail with one major issue.
 */
export class ScriptedJudge implements LlmClient {
  readonly requests: CompleteRequest[] = [];
  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    const failing =
      typeof request.prompt !== 'string' && request.prompt.text.includes('Route: `/search');
    const text = JSON.stringify({
      verdict: failing ? 'fail' : 'pass',
      score: failing ? 5 : 8,
      categoryScores: { structure: 8, components: 8, visualTone: 8 },
      feedback: failing ? 'No results grid.' : 'Looks finished.',
      issues: failing
        ? [{ viewport: 'both', severity: 'major', summary: 'empty results', capability: null }]
        : [],
    });
    return { text, model: 'm', stopReason: 'stop', usage: JUDGE_USAGE };
  }
}

function stubHtml(body: string, loggedIn: boolean): string {
  const logout = loggedIn
    ? '<form method="post" action="/account/logout"><button type="submit">Log out</button></form>'
    : '<a href="/account/login">Log in</a>';
  return `<!doctype html><html><head><title>Stub</title></head><body><header><nav><a href="/">Home</a><a href="/collections/dog-essentials">Dogs</a>${logout}</nav></header><main>${body}</main><footer><a href="/policies/privacy-policy">Privacy</a></footer></body></html>`;
}

/**
 * The stub's login page: the login form, then the "Forgot your password?"
 * form, which shows in place of the login form only while the URL targets
 * `#recover`. It posts to the path with no `#recover`, so the answer shows
 * the login form again.
 */
const STUB_LOGIN =
  '<style>#recover:not(:target),main:has(#recover:target) form:not(#recover){display:none}</style><h1>Login</h1><form method="post"><input name="email"><input name="password" type="password"><a href="#recover">Forgot your password?</a><button type="submit">Sign in</button></form><form method="post" action="/account/login" id="recover"><input type="hidden" name="intent" value="recover"><input name="email"><button type="submit">Submit</button></form>';

/** Fields of the stub's address book forms, by input name. */
const STUB_ADDRESS_FIELDS = [
  'firstName',
  'lastName',
  'company',
  'address1',
  'address2',
  'city',
  'province',
  'zip',
  'phone',
] as const;

/**
 * The stub's address book page: the add form, then the one saved address
 * (always the default) with its edit and delete forms. Every form shows,
 * because the stub has no client script to open them.
 */
function stubAddressBook(address: Readonly<Record<string, string>> | undefined): string {
  const fields = (values: Readonly<Record<string, string>>) => {
    const inputs = STUB_ADDRESS_FIELDS.map(
      (name) => `<input name="${name}" value="${escapeHtml(values[name] ?? '')}">`,
    ).join('');
    return `${inputs}<label><input type="checkbox" name="default" value="true"> Set as default address</label>`;
  };
  const add = `<button type="button">Add a new address</button><form method="post"><input type="hidden" name="intent" value="create">${fields({})}<button type="submit">Add address</button></form>`;
  if (address === undefined) return `<h1>Addresses</h1>${add}<ul></ul>`;
  const name = [address.firstName, address.lastName].filter(Boolean).join(' ');
  const cityLine = [address.city, address.province, address.zip].filter(Boolean).join(' ');
  const lines = [name, address.company, address.address1, address.address2, cityLine]
    .filter(Boolean)
    .map((line) => `<span>${escapeHtml(line ?? '')}</span><br>`)
    .join('');
  return `<h1>Addresses</h1>${add}<ul><li><h2>Default</h2><address>${lines}</address><button type="button" aria-label="Edit address 1">Edit</button><form method="post" onsubmit="return confirm('Are you sure you wish to delete this address?')"><input type="hidden" name="intent" value="delete"><button type="submit" aria-label="Delete 1">Delete</button></form><form method="post"><input type="hidden" name="intent" value="update">${fields(address)}<button type="submit">Update address</button></form></li></ul>`;
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (char) => `&#${char.charCodeAt(0)};`);
}

/**
 * A stand-in storefront that answers every route with a minimal page and
 * walks the account, cart and checkout flows with four cookies (the
 * "Forgot your password?" form needs none; its answer is the message):
 * `session=1` marks a logged-in customer, `cart=1` a non-empty cart,
 * `discount=1` a Discount code applied at checkout, and `address=<JSON>`
 * the one saved address.
 */
export function stubStorefront(): http.Server {
  return http.createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    const cookies = req.headers.cookie ?? '';
    const loggedIn = cookies.includes('session=1');
    const hasCart = cookies.includes('cart=1');
    const hasDiscount = cookies.includes('discount=1');
    const savedAddress = /(?:^|;\s*)address=([^;]+)/.exec(cookies)?.[1];
    const address =
      savedAddress === undefined
        ? undefined
        : (JSON.parse(decodeURIComponent(savedAddress)) as Record<string, string>);
    const page = (body: string): void => {
      res.writeHead(200, { 'content-type': 'text/html' });
      res.end(stubHtml(body, loggedIn));
    };
    const redirect = (location: string, cookie?: string): void => {
      res.writeHead(302, { location, ...(cookie ? { 'set-cookie': cookie } : {}) });
      res.end();
    };
    if (req.method === 'POST') {
      let raw = '';
      req.on('data', (chunk) => {
        raw += chunk;
      });
      req.on('end', () => {
        const form = new URLSearchParams(raw);
        switch (url.pathname) {
          case '/account/register':
          case '/account/login':
            if (form.get('intent') === 'recover') {
              page(
                `${STUB_LOGIN}<p>We've sent you an email with a link to update your password.</p>`,
              );
              return;
            }
            redirect('/account', 'session=1; Path=/');
            return;
          case '/account/logout':
            redirect('/', 'session=; Path=/; Max-Age=0');
            return;
          case '/account/addresses': {
            if (form.get('intent') === 'delete') {
              redirect('/account/addresses', 'address=; Path=/; Max-Age=0');
              return;
            }
            const saved = Object.fromEntries(
              STUB_ADDRESS_FIELDS.map((name) => [name, form.get(name) ?? '']),
            );
            redirect(
              '/account/addresses',
              `address=${encodeURIComponent(JSON.stringify(saved))}; Path=/`,
            );
            return;
          }
          case '/cart':
            redirect(form.get('redirectTo') ?? '/cart', 'cart=1; Path=/');
            return;
          case '/checkout':
            // The stub takes any Discount code.
            if (form.get('intent') === 'discount') {
              redirect('/checkout', 'discount=1; Path=/');
              return;
            }
            redirect('/checkout/confirmation/1001', 'cart=; Path=/; Max-Age=0');
            return;
          default:
            redirect('/');
        }
      });
      return;
    }
    switch (true) {
      case url.pathname === '/account/login':
        page(STUB_LOGIN);
        return;
      case url.pathname === '/account/register':
        page(
          '<h1>Create account</h1><form method="post"><input name="firstName"><input name="lastName"><input name="email"><input name="password" type="password"><button type="submit">Create</button></form>',
        );
        return;
      case url.pathname.startsWith('/account'):
        if (!loggedIn) {
          redirect(`/account/login?redirectTo=${encodeURIComponent(url.pathname)}`);
          return;
        }
        if (url.pathname === '/account/addresses') {
          page(stubAddressBook(address));
          return;
        }
        page(
          url.pathname.startsWith('/account/orders/')
            ? `<h1>Order #${url.pathname.split('/').at(-1)}</h1>`
            : '<h1>Account</h1>',
        );
        return;
      case url.pathname.startsWith('/products/'):
        page(
          '<h1>Product</h1><form method="post" action="/cart" class="product-form"><input type="hidden" name="redirectTo" value="/cart"><input type="hidden" name="intent" value="add"><input type="radio" name="merchandiseId" value="gid://shopify/ProductVariant/1" checked><button type="submit">Add to cart</button></form>',
        );
        return;
      case url.pathname === '/cart':
        page(
          hasCart
            ? '<h1>Cart</h1><p>1 x Product</p><p>Subtotal CA$10.00</p>'
            : '<h1>Cart</h1><p>Your cart is empty.</p>',
        );
        return;
      case url.pathname === '/checkout':
        if (!hasCart) {
          redirect('/cart');
          return;
        }
        page(
          `<h1>Checkout</h1><form method="post"><input name="email"><input name="firstName"><input name="lastName"><input name="address1"><input name="city"><input name="province"><input name="country"><input name="zip"><input type="radio" name="shippingMethodHandle" value="standard"><input type="radio" name="paymentMethodHandle" value="card"><button type="submit">Pay now</button></form><form method="post"><input type="hidden" name="intent" value="discount"><input name="discountCode"><button type="submit">Apply</button></form><div><span>Total</span> <span>${hasDiscount ? 'CAD $9.00' : 'CAD $10.00'}</span></div>`,
        );
        return;
      case url.pathname.startsWith('/checkout/confirmation/'):
        page(`<p>Confirmation #${url.pathname.split('/').at(-1)}</p><h1>Thank you!</h1>`);
        return;
      default:
        page(`<h1>${url.pathname}</h1>`);
    }
  });
}

/** `StorefrontLaunch` seam serving `stubStorefront()` on the requested port. */
export const stubStorefrontLaunch: StorefrontLaunch = async (options) => {
  const server = stubStorefront();
  await new Promise<void>((resolve) => server.listen(options.port, '127.0.0.1', resolve));
  return { stop: () => new Promise<void>((resolve) => server.close(() => resolve())) };
};
