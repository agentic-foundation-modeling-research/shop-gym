/**
 * Fixed browser scripts over the storefront template's forms and pages:
 * register, log in, log out, add, edit and delete an address in the address
 * book, step through the announcement bar, open a product page, sort its
 * Reviews and show more of them, add a product to the cart, apply or have a
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
const ADDRESSES_PATH = '/account/addresses';
/** Address form fields whose values show in the postal lines of a saved address. */
const POSTAL_LINE_FIELDS = [
  'firstName',
  'lastName',
  'company',
  'address1',
  'address2',
  'city',
  'province',
  'zip',
] as const;

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

/** Text fields of an address book form by input name, e.g. `{ address1: '77 Rue Sherbrooke Est' }`. */
export type AddressFields = Readonly<Record<string, string>>;

/**
 * Open the "Add a new address" form on `/account/addresses`, fill `address`
 * (the country stays at its first option) and press "Add address"; ok when
 * the list has one more address and one of them shows the postal lines of
 * `address`.
 */
export async function addAddress(
  page: Page,
  baseUrl: string,
  address: AddressFields,
): Promise<StepOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}${ADDRESSES_PATH}`);
    const toggle = page.getByRole('button', { name: 'Add a new address', exact: true });
    if ((await toggle.count()) === 0) {
      return { ok: false, detail: `no "Add a new address" button on ${pathOf(page.url())}` };
    }
    const before = await addressEntries(page).count();
    const form = formWithButton(page.locator('form'), page, 'Add address');
    await openAddressForm(toggle, form);
    await fillFields(form, address);
    await submitInPlace(page, form);
    const { settled, error } = await waitForAddressBook(page, async () => {
      const lines = await addressEntries(page).locator('address').allInnerTexts();
      return lines.length === before + 1 && lines.some((text) => showsPostalLines(text, address));
    });
    const after = await addressEntries(page).count();
    return {
      ok: settled,
      detail: `adding an address went from ${before} to ${after} addresses${error ? `, with "${error}"` : ''}`,
      url: ADDRESSES_PATH,
    };
  });
}

/**
 * Open the edit form of the address in place `position` (from 1) on
 * `/account/addresses`, fill `changes` and press "Update address"; ok when
 * that address shows the changed postal lines and, with `setDefault`, the
 * "Default" heading.
 */
export async function editAddress(
  page: Page,
  baseUrl: string,
  position: number,
  changes: AddressFields,
  options: { readonly setDefault?: boolean } = {},
): Promise<StepOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}${ADDRESSES_PATH}`);
    const toggle = page.getByRole('button', { name: `Edit address ${position}`, exact: true });
    if ((await toggle.count()) === 0) {
      return { ok: false, detail: `no "Edit address ${position}" button on ${pathOf(page.url())}` };
    }
    const entry = page.locator('li').filter({ has: toggle });
    const form = formWithButton(entry.locator('form'), page, 'Update address');
    await openAddressForm(toggle, form);
    await fillFields(form, changes);
    if (options.setDefault === true) {
      await form.getByLabel('Set as default address', { exact: true }).evaluate((element) => {
        (element as unknown as { checked: boolean }).checked = true;
      });
    }
    await submitInPlace(page, form);
    const isDefault = async () =>
      (await entry.getByRole('heading', { name: 'Default', exact: true }).count()) > 0;
    const { settled, error } = await waitForAddressBook(page, async () => {
      const shown = showsPostalLines(await entry.locator('address').innerText(), changes);
      return shown && (options.setDefault !== true || (await isDefault()));
    });
    const lines = normalizedText(await entry.locator('address').innerText());
    return {
      ok: settled,
      detail: `address ${position} shows "${lines}"${(await isDefault()) ? ' as the default' : ''}${error ? `, with "${error}"` : ''}`,
      url: ADDRESSES_PATH,
    };
  });
}

/**
 * Press "Delete" on the address in place `position` (from 1) on
 * `/account/addresses` and accept the browser's confirm dialog; ok when the
 * list has one address less.
 */
export async function deleteAddress(
  page: Page,
  baseUrl: string,
  position: number,
): Promise<StepOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}${ADDRESSES_PATH}`);
    const button = page.getByRole('button', { name: `Delete ${position}`, exact: true });
    if ((await button.count()) === 0) {
      return { ok: false, detail: `no "Delete ${position}" button on ${pathOf(page.url())}` };
    }
    const before = await addressEntries(page).count();
    let confirmText = '';
    const accept = (dialog: { message(): string; accept(): Promise<void> }) => {
      confirmText = dialog.message();
      dialog.accept().catch(() => undefined);
    };
    page.on('dialog', accept);
    try {
      await submitInPlace(page, button.locator('xpath=ancestor::form'));
    } finally {
      page.off('dialog', accept);
    }
    const { settled, error } = await waitForAddressBook(
      page,
      async () => (await addressEntries(page).count()) === before - 1,
    );
    const after = await addressEntries(page).count();
    return {
      ok: settled,
      detail: `confirming "${confirmText}" went from ${before} to ${after} addresses${error ? `, with "${error}"` : ''}`,
      url: ADDRESSES_PATH,
    };
  });
}

/** The saved addresses on the address book page: each has an "Edit address <n>" button. */
function addressEntries(page: Page): Locator {
  return page
    .locator('li')
    .filter({ has: page.getByRole('button', { name: /^Edit address \d+$/ }) });
}

/** The form among `forms` with button `name`, also while the form is hidden. */
function formWithButton(forms: Locator, page: Page, name: string): Locator {
  return forms.filter({
    has: page.getByRole('button', { name, exact: true, includeHidden: true }),
  });
}

/** Press `toggle` unless `form` already shows, then wait until it shows. */
async function openAddressForm(toggle: Locator, form: Locator): Promise<void> {
  if (await form.isVisible()) return;
  await toggle.evaluate((element) => (element as unknown as { click(): void }).click());
  await form.waitFor({ state: 'visible', timeout: SUBMIT_TIMEOUT_MS });
}

/** Whether postal lines `text` show every postal line value of `fields`. */
function showsPostalLines(text: string, fields: AddressFields): boolean {
  const shown = normalizedText(text);
  return POSTAL_LINE_FIELDS.every((name) => {
    const value = fields[name]?.trim() ?? '';
    return value === '' || shown.includes(value);
  });
}

/**
 * Submit `form` and wait for the answer to its POST. The address book posts
 * back to its own URL, so there is no new URL to wait for.
 */
async function submitInPlace(page: Page, form: Locator): Promise<void> {
  const posted = page
    .waitForResponse((response) => response.request().method() === 'POST', {
      timeout: SUBMIT_TIMEOUT_MS,
    })
    .catch(() => undefined);
  await form.evaluate((element) =>
    (element as unknown as { requestSubmit(): void }).requestSubmit(),
  );
  await posted;
}

/**
 * Poll the address book until `settled` holds or a form error shows. A read
 * while the page reloads fails and is tried again.
 */
async function waitForAddressBook(
  page: Page,
  settled: () => Promise<boolean>,
): Promise<{ readonly settled: boolean; readonly error: string }> {
  const errors = page.getByRole('alert').filter({ visible: true });
  const [done, alerts] = await pollPage(
    page,
    () => Promise.all([settled(), errors.allInnerTexts()]),
    [false, []],
    ([ok, texts]) => ok || texts.length > 0,
  );
  return { settled: done, error: normalizedText(alerts.join(' ')) };
}

/**
 * Read the page every `POLL_INTERVAL_MS` until `done` holds for a read or
 * `SUBMIT_TIMEOUT_MS` passes, then wait for the load event and return the
 * last read. A read that fails while the page reloads gives `unsettled`.
 */
async function pollPage<T>(
  page: Page,
  read: () => Promise<T>,
  unsettled: T,
  done: (observed: T) => boolean,
): Promise<T> {
  const deadline = Date.now() + SUBMIT_TIMEOUT_MS;
  for (;;) {
    const observed = await read().catch(() => unsettled);
    if (done(observed) || Date.now() > deadline) {
      await page.waitForLoadState('load');
      return observed;
    }
    await sleep(POLL_INTERVAL_MS);
  }
}

export interface AnnouncementOutcome extends StepOutcome {
  /** Text of each slide that the bar showed, from the first; empty when there is no bar. */
  readonly slides?: readonly string[];
}

/**
 * The slide that the announcement bar shows. `label` is its accessible
 * name, "<n> of <total>"; when not exactly one slide shows, it tells how
 * many do, for the step's detail.
 */
interface Slide {
  readonly label: string;
  readonly text: string;
}

/**
 * Open `/` and read every slide of the announcement bar. With no bar, ok
 * with no slides. A plain "Announcement" region is one slide, ok when it
 * has no buttons. An "Announcement bar" carousel is stepped through: read
 * the slide it starts on, press "Next announcement" until the bar is back
 * on the first slide, then press "Previous announcement" once. ok when the
 * bar starts on "1 of <n>", Next shows "2 of <n>" to "<n> of <n>" and then
 * "1 of <n>" again, and Previous on the first slide shows "<n> of <n>".
 */
export async function stepThroughAnnouncements(
  page: Page,
  baseUrl: string,
): Promise<AnnouncementOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}/`);
    const carousel = page.getByRole('region', { name: 'Announcement bar', exact: true });
    if ((await carousel.count()) > 0) return stepThroughCarousel(page, carousel);
    const plain = page.getByRole('region', { name: 'Announcement', exact: true });
    if ((await plain.count()) === 0) {
      return { ok: true, detail: 'no announcement bar on /', url: '/', slides: [] };
    }
    const buttons = await plain.getByRole('button').count();
    const text = normalizedText(await plain.innerText());
    return {
      ok: buttons === 0,
      detail: `the "Announcement" region shows "${text}" with ${buttons} buttons`,
      url: '/',
      slides: [text],
    };
  });
}

/** Step through the "Announcement bar" carousel `bar` as `stepThroughAnnouncements` says. */
async function stepThroughCarousel(page: Page, bar: Locator): Promise<AnnouncementOutcome> {
  const next = bar.getByRole('button', { name: 'Next announcement', exact: true });
  const previous = bar.getByRole('button', { name: 'Previous announcement', exact: true });
  if ((await next.count()) === 0 || (await previous.count()) === 0) {
    return {
      ok: false,
      detail: 'the "Announcement bar" has no Previous and Next arrows',
      url: '/',
    };
  }
  const first = await shownSlide(bar);
  const total = Number(/^1 of (\d+)$/.exec(first.label)?.[1] ?? 0);
  if (total < 2) {
    return { ok: false, detail: `the bar starts on "${first.label}"`, url: '/' };
  }
  const slides = [first];
  let last = first;
  while (slides.length < total) {
    const slide = await pressArrow(page, bar, next, last.label);
    if (slide.label === last.label) break;
    slides.push(slide);
    last = slide;
  }
  const wrapped = await pressArrow(page, bar, next, last.label);
  const back = await pressArrow(page, bar, previous, wrapped.label);
  const labels = slides.map((slide) => slide.label);
  return {
    ok:
      labels.length === total &&
      labels.every((label, index) => label === `${index + 1} of ${total}`) &&
      wrapped.label === `1 of ${total}` &&
      back.label === `${total} of ${total}`,
    detail: `the bar showed ${labels.map((label) => `"${label}"`).join(', ')}, then Next showed "${wrapped.label}" and Previous "${back.label}"`,
    url: '/',
    slides: slides.map((slide) => slide.text),
  };
}

/**
 * Press `arrow` until `bar` no longer shows the slide labelled `from`, and
 * return the slide it shows then. A press before the page hydrates does
 * nothing, so each poll presses again until the slide changes.
 */
async function pressArrow(page: Page, bar: Locator, arrow: Locator, from: string): Promise<Slide> {
  return pollPage(
    page,
    async () => {
      await arrow.evaluate((element) => (element as unknown as { click(): void }).click());
      return shownSlide(bar);
    },
    { label: from, text: '' },
    (slide) => slide.label !== from,
  );
}

/** The one slide of `bar` that shows; hidden slides are not in the accessibility tree. */
async function shownSlide(bar: Locator): Promise<Slide> {
  const slides = bar.getByRole('group', { name: /^\d+ of \d+$/ });
  const count = await slides.count();
  if (count !== 1) return { label: `${count} slides shown`, text: '' };
  return {
    label: (await slides.getAttribute('aria-label')) ?? '',
    text: normalizedText(await slides.innerText()),
  };
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
  // A document reload drops the total row, or the page, for a moment; such a read is not settled.
  const [after, errors] = await pollPage(
    page,
    () => Promise.all([checkoutTotal(page), error.count()]),
    ['', 0],
    ([total, count]) => total !== '' && (total !== before || count > 0),
  );
  return { before, after, error: errors > 0 };
}

/** Text of the visible checkout "Total" row, e.g. "Total CAD $17.99"; empty when there is none. */
async function checkoutTotal(page: Page): Promise<string> {
  const label = page.getByText('Total', { exact: true }).filter({ visible: true }).first();
  if ((await label.count()) === 0) return '';
  const row = await label.locator('xpath=..').innerText({ timeout: 1000 });
  return row.replace(/\s+/g, ' ').trim();
}

/** Open the page of `productHandle`; expects 200 and a level-1 heading. */
export async function viewProduct(
  page: Page,
  baseUrl: string,
  productHandle: string,
): Promise<StepOutcome> {
  return viewPage(page, baseUrl, `/products/${productHandle}`, 'a level-1 heading', (p) =>
    p.getByRole('heading', { level: 1 }),
  );
}

/**
 * Open product page `path`, choose `sortLabel` in the Reviews "Sort by"
 * control and submit it; ok when the page reloads with that option chosen.
 * `path` may hold a query, e.g. `/products/<handle>?reviews_sort=most_helpful`.
 */
export async function sortReviews(
  page: Page,
  baseUrl: string,
  path: string,
  sortLabel: string,
): Promise<StepOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}${path}`);
    const select = reviewsSection(page).getByLabel('Sort by', { exact: true });
    if ((await select.count()) === 0) {
      return { ok: false, detail: `no Reviews "Sort by" control on ${path}` };
    }
    await select.selectOption({ label: sortLabel });
    const landed = await submit(page, select.locator('xpath=ancestor::form'));
    const chosen = (await select.locator('option:checked').textContent()) ?? '';
    return {
      ok: landed !== path && chosen === sortLabel,
      detail: `sorting by "${sortLabel}" landed on ${landed} with "${chosen}" chosen`,
      url: landed,
    };
  });
}

/**
 * Open product page `path` and press "Show more reviews"; ok when the page
 * reloads with more Reviews than before. `path` may hold a query.
 */
export async function showMoreReviews(
  page: Page,
  baseUrl: string,
  path: string,
): Promise<StepOutcome> {
  return attempt(async () => {
    await open(page, `${baseUrl}${path}`);
    const reviews = reviewsSection(page).locator('article');
    const before = await reviews.count();
    const button = reviewsSection(page).getByRole('button', {
      name: 'Show more reviews',
      exact: true,
    });
    if ((await button.count()) === 0) {
      return { ok: false, detail: `no "Show more reviews" button on ${path}` };
    }
    const landed = await submit(page, button.locator('xpath=ancestor::form'));
    const after = await reviews.count();
    return {
      ok: after > before,
      detail: `"Show more reviews" landed on ${landed} with ${after} Reviews, up from ${before}`,
      url: landed,
    };
  });
}

/** The product page's "Reviews" section. */
function reviewsSection(page: Page): Locator {
  return page.getByRole('region', { name: 'Reviews', exact: true });
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

function normalizedText(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}
