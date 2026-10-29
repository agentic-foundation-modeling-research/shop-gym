/**
 * Slow end-to-end smoke of the storefront template against the backend
 * template: copies the template to a temp dir, installs and builds it, boots
 * `shop-backend` on the template fixture plus the built storefront, and
 * drives the shopping, account, checkout, and episode-isolation flows over
 * HTTP. Gated by `SHOPGYM_SLOW_TESTS=1`; requires `pnpm` on PATH and a built
 * `packages/shop_backend/dist`.
 */

import { type ChildProcess, execFileSync, spawn } from 'node:child_process';
import { cpSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { STOREFRONT_TEMPLATE_DIR } from './templates.js';

const BACKEND_CLI = fileURLToPath(new URL('../../shop_backend/dist/cli.js', import.meta.url));
const FIXTURE_DIR = join(STOREFRONT_TEMPLATE_DIR, 'fixtures', 'sandbox_shop_v0');
const BOOT_TIMEOUT_MS = 30_000;

const GUEST_ADDRESS = {
  firstName: 'Guest',
  lastName: 'Shopper',
  address1: '1 Sample Road',
  city: 'Ottawa',
  province: 'Ontario',
  country: 'Canada',
  zip: 'K1A 0B1',
};

describe.skipIf(!process.env.SHOPGYM_SLOW_TESTS)('storefront template smoke', () => {
  let workDir: string;
  let storefrontUrl: string;
  const children: ChildProcess[] = [];

  beforeAll(async () => {
    workDir = mkdtempSync(join(tmpdir(), 'shopgym-storefront-'));
    const templateDir = join(workDir, 'storefront');
    copyTrackedFiles(STOREFRONT_TEMPLATE_DIR, templateDir);
    execFileSync('pnpm', ['install', '--ignore-workspace', '--frozen-lockfile'], {
      cwd: templateDir,
      stdio: 'pipe',
    });
    execFileSync('pnpm', ['build'], { cwd: templateDir, stdio: 'pipe' });

    const backendPort = await freePort();
    const storefrontPort = await freePort();
    const backendUrl = `http://127.0.0.1:${backendPort}`;
    storefrontUrl = `http://127.0.0.1:${storefrontPort}`;

    children.push(
      spawn('node', [BACKEND_CLI, FIXTURE_DIR, String(backendPort)], { stdio: 'pipe' }),
    );
    await waitForHealth(`${backendUrl}/health`);
    children.push(
      spawn('node', ['server.mjs'], {
        cwd: templateDir,
        stdio: 'pipe',
        env: {
          ...process.env,
          NODE_ENV: 'production',
          PORT: String(storefrontPort),
          PUBLIC_STORE_DOMAIN: backendUrl,
          SESSION_SECRET: 'smoke-test-secret',
        },
      }),
    );
    await waitForHealth(`${storefrontUrl}/health`);
  }, 300_000);

  afterAll(() => {
    for (const child of children) child.kill();
    if (workDir) rmSync(workDir, { recursive: true, force: true });
  });

  it('serves the catalog, cart, account, and checkout flows', async () => {
    const guest = new HttpClient(storefrontUrl);

    const home = await guest.get('/');
    expect(home.status).toBe(200);
    expect(home.body).toContain('Mock Pet Foods');
    expect(home.body).toContain('/account/login');

    const product = await guest.get('/products/shopliseum-mushroom-dog-toys');
    expect(product.status).toBe(200);
    const merchandiseId = availableMerchandiseId(product.body);

    await guest.post('/cart', { intent: 'add', merchandiseId, quantity: '1' });
    expect((await guest.get('/cart')).body).toContain('Shopliseum Mushroom Dog Toys');

    // The cart page turns down an unknown Discount code and keeps a valid one.
    const rejected = await guest.post('/cart', { intent: 'discount', discountCode: 'nope' });
    expect(rejected.status).toBe(200);
    expect(rejected.body).toContain('Enter a valid discount code');
    await guest.post('/cart', { intent: 'discount', discountCode: 'freeship' });
    expect((await guest.get('/cart')).body).toContain('Remove discount code FREESHIP');

    // Guest checkout.
    const guestCheckout = await guest.post('/checkout', {
      email: 'guest@example.com',
      ...GUEST_ADDRESS,
      shippingMethodHandle: 'express',
      paymentMethodHandle: 'paypal',
    });
    expect(guestCheckout.location).toMatch(/^\/checkout\/confirmation\/\d+$/);
    const confirmation = await guest.get(guestCheckout.location);
    expect(confirmation.status).toBe(200);
    expect(confirmation.body).toContain('Thank you, Guest!');
    expect(confirmation.body).toContain('guest@example.com');
    expect(confirmation.body).toContain('FREESHIP');
    expect((await guest.get('/cart')).body).toContain('Your cart is empty');

    // Inline checkout errors on a blank required field.
    await guest.post('/cart', { intent: 'add', merchandiseId, quantity: '1' });
    const failed = await guest.post('/checkout', {
      email: 'guest@example.com',
      ...GUEST_ADDRESS,
      address1: '',
    });
    expect(failed.status).toBe(200);
    expect(failed.body).toContain("Shipping address address1 can't be blank");

    // Register, then log out.
    const fresh = new HttpClient(storefrontUrl);
    const registered = await fresh.post('/account/register', {
      firstName: 'Test',
      lastName: 'Shopper',
      email: 'test.shopper@example.com',
      password: 'password123',
    });
    expect(registered.location).toBe('/account');
    const profile = await fresh.get('/account');
    expect(profile.status).toBe(200);
    expect(profile.body).toContain('Test Shopper');
    expect((await fresh.post('/account/logout', {})).location).toBe('/');
    expect((await fresh.get('/account')).location).toBe('/account/login?redirectTo=%2Faccount');

    // Log in as the seeded customer with a cart already in the session.
    const member = new HttpClient(storefrontUrl);
    await member.post('/cart', { intent: 'add', merchandiseId, quantity: '1' });
    const login = await member.post('/account/login', {
      email: 'jane.doe@example.com',
      password: 'password123',
    });
    expect(login.location).toBe('/account');
    const memberProfile = await member.get('/account');
    expect(memberProfile.body).toContain('Jane Doe');
    expect(memberProfile.body).toContain('#1001');
    expect((await member.get('/account/addresses')).body).toContain('123 Bank Street');

    // Logged-in checkout is prefilled, lands on the thank-you page, and joins the order history.
    const checkoutPage = await member.get('/checkout');
    expect(checkoutPage.body).toContain('value="jane.doe@example.com"');
    expect(checkoutPage.body).toContain('value="123 Bank Street"');
    const memberCheckout = await member.post('/checkout', {
      email: 'jane.doe@example.com',
      ...GUEST_ADDRESS,
      firstName: 'Jane',
      lastName: 'Doe',
      shippingMethodHandle: 'standard',
      paymentMethodHandle: 'card',
    });
    const placed = /^\/checkout\/confirmation\/(\d+)$/.exec(memberCheckout.location);
    expect(placed?.[1]).toBeDefined();
    const orderPath = `/account/orders/${placed?.[1]}`;
    const orderPage = await member.get(orderPath);
    expect(orderPage.status).toBe(200);
    expect(orderPage.body).toContain('Shopliseum Mushroom Dog Toys');
    expect((await member.get('/account/orders')).body).toContain(orderPath);
    expect((await member.get('/account/orders/999999')).status).toBe(404);
  });

  it('keeps x-shopgym-episode requests out of the default episode', async () => {
    const shopper = new HttpClient(storefrontUrl);
    const product = await shopper.get('/products/aislearena-anti-tick-collar');
    const merchandiseId = availableMerchandiseId(product.body);
    await shopper.post('/cart', { intent: 'add', merchandiseId, quantity: '1' });
    expect((await shopper.get('/cart')).body).toContain('AisleArena Anti Tick Collar');

    // Same cookies, different episode: the default-episode cart is invisible.
    const episode = new HttpClient(storefrontUrl, 'ep1', shopper.cookies);
    expect((await episode.get('/cart')).body).toContain('Your cart is empty');

    // Seeded customers exist in every episode, but default-episode orders do not leak.
    await episode.post('/account/login', {
      email: 'jane.doe@example.com',
      password: 'password123',
    });
    const orders = await episode.get('/account/orders');
    expect(orders.status).toBe(200);
    expect(orders.body).toContain('#1001');
    expect(orders.body).not.toContain('#1003');
  });
});

interface HttpResult {
  readonly status: number;
  readonly location: string;
  readonly body: string;
}

/** Minimal cookie-jar HTTP client; redirects are reported, not followed. */
class HttpClient {
  constructor(
    private readonly baseUrl: string,
    private readonly episodeId: string | null = null,
    readonly cookies: Map<string, string> = new Map(),
  ) {}

  get(path: string): Promise<HttpResult> {
    return this.request(path, { method: 'GET' });
  }

  post(path: string, form: Record<string, string>): Promise<HttpResult> {
    return this.request(path, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(form).toString(),
    });
  }

  private async request(path: string, init: RequestInit): Promise<HttpResult> {
    const headers = new Headers(init.headers);
    if (this.cookies.size > 0) {
      headers.set('cookie', [...this.cookies].map(([k, v]) => `${k}=${v}`).join('; '));
    }
    if (this.episodeId !== null) headers.set('x-shopgym-episode', this.episodeId);
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      redirect: 'manual',
    });
    for (const cookie of response.headers.getSetCookie()) {
      const [pair] = cookie.split(';');
      const eq = pair?.indexOf('=') ?? -1;
      if (pair && eq > 0) this.cookies.set(pair.slice(0, eq), pair.slice(eq + 1));
    }
    return {
      status: response.status,
      location: response.headers.get('location') ?? '',
      body: await response.text(),
    };
  }
}

function copyTrackedFiles(sourceDir: string, targetDir: string): void {
  const listing = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard'], {
    cwd: sourceDir,
    encoding: 'utf8',
  });
  for (const relative of listing.split('\n').filter((line) => line.length > 0)) {
    const target = join(targetDir, relative);
    mkdirSync(dirname(target), { recursive: true });
    cpSync(join(sourceDir, relative), target);
  }
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (address === null || typeof address === 'string') {
        reject(new Error('Could not allocate a port.'));
        return;
      }
      server.close(() => resolve(address.port));
    });
  });
}

async function waitForHealth(url: string): Promise<void> {
  const deadline = Date.now() + BOOT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Not listening yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

/** `value` of the first enabled variant radio on a product page. */
function availableMerchandiseId(html: string): string {
  for (const [input] of html.matchAll(/<input[^>]*name="merchandiseId"[^>]*>/g)) {
    if (input.includes('disabled')) continue;
    const value = /value="([^"]+)"/.exec(input)?.[1];
    if (value !== undefined) return value;
  }
  throw new Error('No available variant radio found on the product page.');
}
