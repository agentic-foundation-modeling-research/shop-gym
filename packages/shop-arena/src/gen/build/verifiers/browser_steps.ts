/**
 * Fixed browser scripts over the storefront template's forms: register, log
 * in, log out, add a product to the cart, place an order. Each step drives
 * one Playwright page, never throws, and reports what it observed so the
 * sweeps can record it.
 *
 * Forms are submitted with `requestSubmit()` rather than a pointer click so
 * consent or newsletter popups layered over the page cannot intercept them.
 */

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

/** Fill the checkout form and place the order; expects an order or confirmation page. */
export async function placeOrder(page: Page, baseUrl: string, email: string): Promise<StepOutcome> {
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
    const ok =
      /^\/account\/orders\/\d+$/.test(path) || /^\/checkout\/confirmation\/\d+$/.test(path);
    return { ok, detail: `placing the order landed on ${path}`, url: path };
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

async function attempt(run: () => Promise<StepOutcome>): Promise<StepOutcome> {
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
