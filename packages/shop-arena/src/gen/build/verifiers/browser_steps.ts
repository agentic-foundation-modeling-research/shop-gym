/**
 * Fixed browser scripts over the storefront template's forms and pages:
 * register, log in, log out, add a product to the cart, apply or have a
 * Discount code turned down at checkout, place an order, and open that
 * order's thank-you page, the account order history and an account order
 * page. Each step drives one Playwright page, never throws, and reports
 * what it observed so the callers can record it.
 *
 * Forms are submitted with `requestSubmit()` rather than a pointer click so
 * consent or newsletter popups layered over the page cannot intercept them.
 */

import { setTimeout as sleep } from 'node:timers/promises';

import type { BrowserSession } from '@shop-gym/browser';

import { CHECKOUT_ADDRESS } from './storefront_target.js';

export interface StepOutcome {
  readonly ok: boolean;
  readonly detail: string;
  /** Final page path and query, when the step navigated. */
  readonly url?: string;
}

export interface Credentials {
  readonly email: string;
  readonly password: string;
}

type Page = BrowserSession['page'];
type Locator = ReturnType<Page['locator']>;
const NAVIGATION_TIMEOUT_MS = 30_000;
const SUBMIT_TIMEOUT_MS = 15_000;
const POLL_INTERVAL_MS = 200;
/** Checkout's error under the "Discount code" field for a code that does not apply. */
const INVALID_DISCOUNT_CODE = 'Enter a valid discount code';

export async function register(
  page: Page,
  baseUrl: string,
  account: Credentials & { readonly firstName: string; readonly lastName: string },
): Promise<StepOutcome> {
  return submitForm(page, `${baseUrl}/account/register`, 'firstName', { ...account }, '/account');
}

export async function logIn(
  page: Page,
  baseUrl: string,
  account: Credentials,
): Promise<StepOutcome> {
  return submitForm(page, `${baseUrl}/account/login`, 'email', { ...account }, '/account');
}

/** Submit the logout form on the account page; expects to land on `/`. */
export async function logOut(page: Page, baseUrl: string): Promise<StepOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}/account`);
    const form = page.locator('form[action="/account/logout"]').first();
    if ((await form.count()) === 0) {
      return { ok: false, detail: 'no logout form on /account', url: pathOf(page.url()) };
    }
    const path = await submit(page, form);
    return { ok: path === '/', detail: `logout landed on ${path}`, url: path };
  });
}

/** Add the first available variant of `productHandle`; expects a non-empty cart. */
export async function addToCart(
  page: Page,
  baseUrl: string,
  productHandle: string,
): Promise<StepOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}/products/${productHandle}`);
    const form = page
      .locator('form[action="/cart"]:has(input[name="intent"][value="add"])')
      .first();
    if ((await form.count()) === 0) {
      return { ok: false, detail: `no add-to-cart form on /products/${productHandle}` };
    }
    const enabledVariant = form.locator('input[name="merchandiseId"]:not([disabled])').first();
    if ((await enabledVariant.count()) > 0) {
      await enabledVariant.check();
    }
    await submit(page, form);
    await open(page, `${baseUrl}/cart`);
    const empty = (await page.locator('body').innerText()).includes('Your cart is empty');
    return {
      ok: !empty,
      detail: empty
        ? '/cart is still empty after submitting the add form'
        : '/cart shows the added line',
      url: '/cart',
    };
  });
}

export interface OrderOutcome extends StepOutcome {
  /** Number of the placed order, read from the landing path; set when `ok`. */
  readonly orderNumber?: number;
}

/** Fill the checkout form and place the order; expects an order or confirmation page. */
export async function placeOrder(
  page: Page,
  baseUrl: string,
  email: string,
): Promise<OrderOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}/checkout`);
    const form = page.locator('form:has(input[name="address1"])').first();
    if ((await form.count()) === 0) {
      return {
        ok: false,
        detail: `no checkout form on /checkout (landed on ${pathOf(page.url())})`,
      };
    }
    await fillFields(form, { email, ...CHECKOUT_ADDRESS });
    for (const name of ['shippingMethodHandle', 'paymentMethodHandle']) {
      const radio = form.locator(`input[name="${name}"]`).first();
      if ((await radio.count()) > 0) {
        await radio.check();
      }
    }
    const path = await submit(page, form);
    const match = /^\/(?:account\/orders|checkout\/confirmation)\/(\d+)$/.exec(path);
    const detail = `placing the order landed on ${path}`;
    if (match?.[1] === undefined) {
      return { ok: false, detail, url: path };
    }
    return { ok: true, detail, url: path, orderNumber: Number(match[1]) };
  });
}

/**
 * Apply Discount code `code` in the checkout order summary; ok when the
 * "Total" changes and the "Enter a valid discount code" error does not show.
 */
export async function applyDiscountCode(
  page: Page,
  baseUrl: string,
  code: string,
): Promise<StepOutcome> {
  return attempt(async () => {
    const entered = await enterDiscountCode(page, baseUrl, code);
    if ('ok' in entered) return entered;
    const { before, after, error } = entered;
    return {
      ok: after !== before && !error,
      detail: `${code}: "${before}" became "${after}"${error ? `, with "${INVALID_DISCOUNT_CODE}"` : ''}`,
      url: '/checkout',
    };
  });
}

/**
 * Enter Discount code `code` that must not apply; ok when the
 * "Enter a valid discount code" error shows and the "Total" does not change.
 */
export async function rejectDiscountCode(
  page: Page,
  baseUrl: string,
  code: string,
): Promise<StepOutcome> {
  return attempt(async () => {
    const entered = await enterDiscountCode(page, baseUrl, code);
    if ('ok' in entered) return entered;
    const { before, after, error } = entered;
    return {
      ok: error && after === before,
      detail: `${code}: ${error ? `"${INVALID_DISCOUNT_CODE}" shows` : 'no error shows'}, "${before}" became "${after}"`,
      url: '/checkout',
    };
  });
}

interface DiscountObservation {
  /** The checkout "Total" row before and after the code was entered. */
  readonly before: string;
  readonly after: string;
  /** Whether "Enter a valid discount code" shows after the code was entered. */
  readonly error: boolean;
}

/**
 * Open `/checkout`, submit `code` in the "Discount code" field, and wait
 * until the "Total" changes or the error shows. The field posts in place
 * (a fetch or a document reload of `/checkout`), so the step polls the page
 * rather than wait for a new URL.
 */
async function enterDiscountCode(
  page: Page,
  baseUrl: string,
  code: string,
): Promise<DiscountObservation | StepOutcome> {
  await open(page, `${baseUrl}/checkout`);
  const form = page.locator('form:has(input[name="discountCode"])').first();
  if ((await form.count()) === 0) {
    return { ok: false, detail: `no "Discount code" field on ${pathOf(page.url())}` };
  }
  const before = await checkoutTotal(page);
  await form.locator('input[name="discountCode"]').fill(code);
  await form.evaluate((element) =>
    (element as unknown as { requestSubmit(): void }).requestSubmit(),
  );
  const error = page.getByText(INVALID_DISCOUNT_CODE, { exact: true }).filter({ visible: true });
  const deadline = Date.now() + SUBMIT_TIMEOUT_MS;
  for (;;) {
    // A document reload drops the total row, or the page, for a moment; such a read is not settled.
    const observed = await Promise.all([checkoutTotal(page), error.count()]).catch(() => undefined);
    const [after, errors] = observed ?? ['', 0];
    const settled = after !== '' && (after !== before || errors > 0);
    if (settled || Date.now() > deadline) {
      await page.waitForLoadState('load');
      return { before, after, error: errors > 0 };
    }
    await sleep(POLL_INTERVAL_MS);
  }
}

/** Text of the visible checkout "Total" row, e.g. "Total CAD $17.99"; empty when there is none. */
async function checkoutTotal(page: Page): Promise<string> {
  const label = page.getByText('Total', { exact: true }).filter({ visible: true }).first();
  if ((await label.count()) === 0) return '';
  const row = await label.locator('xpath=..').innerText({ timeout: 1000 });
  return row.replace(/\s+/g, ' ').trim();
}

/** Open the account page of order `orderNumber`; expects 200 and the heading "Order #<number>". */
export async function viewOrder(
  page: Page,
  baseUrl: string,
  orderNumber: number,
): Promise<StepOutcome> {
  const name = `Order #${orderNumber}`;
  return viewPage(page, baseUrl, `/account/orders/${orderNumber}`, `heading "${name}"`, (p) =>
    p.getByRole('heading', { name, exact: true }),
  );
}

/** Open `/account`; expects 200 and an order history link to order `orderNumber`. */
export async function viewOrderHistory(
  page: Page,
  baseUrl: string,
  orderNumber: number,
): Promise<StepOutcome> {
  const name = `Order number #${orderNumber}`;
  return viewPage(page, baseUrl, '/account', `link "${name}"`, (p) =>
    p.getByRole('link', { name, exact: true }),
  );
}

/** Open the thank-you page of order `orderNumber`; expects 200 and a "Thank you" heading. */
export async function viewThankYou(
  page: Page,
  baseUrl: string,
  orderNumber: number,
): Promise<StepOutcome> {
  return viewPage(
    page,
    baseUrl,
    `/checkout/confirmation/${orderNumber}`,
    'a "Thank you" heading',
    (p) => p.getByRole('heading', { level: 1, name: /thank you/i }),
  );
}

/**
 * Open `path`; ok when it answers 200 and shows what `find` locates.
 * `targetDescription` names that target in the detail.
 */
async function viewPage(
  page: Page,
  baseUrl: string,
  path: string,
  targetDescription: string,
  find: (page: Page) => Locator,
): Promise<StepOutcome> {
  return attempt(async () => {
    const response = await page.goto(`${baseUrl}${path}`, {
      waitUntil: 'load',
      timeout: NAVIGATION_TIMEOUT_MS,
    });
    const status = response?.status() ?? 0;
    const found = (await find(page).count()) > 0;
    return {
      ok: status === 200 && found,
      detail: `${path} returned ${status} with heading "${await heading(page)}" and ${found ? '' : 'no '}${targetDescription}`,
      url: path,
    };
  });
}

/** Open `url`, fill the form that has an input named `keyField`, submit, and compare the landing path. */
async function submitForm(
  page: Page,
  url: string,
  keyField: string,
  fields: Readonly<Record<string, string>>,
  expectedPath: string,
): Promise<StepOutcome> {
  return attempt(async () => {
    await open(page, url);
    const form = page.locator(`form:has(input[name="${keyField}"])`).first();
    if ((await form.count()) === 0) {
      return {
        ok: false,
        detail: `no form with the expected fields at ${pathOf(page.url())} (heading "${await heading(page)}")`,
      };
    }
    await fillFields(form, fields);
    const path = await submit(page, form);
    return { ok: path === expectedPath, detail: `submitting landed on ${path}`, url: path };
  });
}

async function open(page: Page, url: string): Promise<void> {
  await page.goto(url, { waitUntil: 'load', timeout: NAVIGATION_TIMEOUT_MS });
}

/** Submit `form` and wait for the URL to change; resolves with the resulting path. */
async function submit(page: Page, form: Locator): Promise<string> {
  const before = pathOf(page.url());
  await form.evaluate((element) =>
    (element as unknown as { requestSubmit(): void }).requestSubmit(),
  );
  await page
    .waitForURL((url) => url.pathname + url.search !== before, { timeout: SUBMIT_TIMEOUT_MS })
    .catch(() => undefined);
  await page.waitForLoadState('load');
  return pathOf(page.url());
}

async function fillFields(form: Locator, fields: Readonly<Record<string, string>>): Promise<void> {
  for (const [name, value] of Object.entries(fields)) {
    const input = form.locator(`input[name="${name}"], textarea[name="${name}"]`).first();
    if ((await input.count()) > 0) {
      await input.fill(value);
    }
  }
}

async function attempt<T extends StepOutcome>(run: () => Promise<T>): Promise<T | StepOutcome> {
  try {
    return await run();
  } catch (error) {
    return { ok: false, detail: error instanceof Error ? error.message : String(error) };
  }
}

async function heading(page: Page): Promise<string> {
  return page
    .locator('h1')
    .first()
    .innerText({ timeout: 1000 })
    .catch(() => '');
}

function pathOf(url: string): string {
  const parsed = new URL(url);
  return parsed.pathname + parsed.search;
}
