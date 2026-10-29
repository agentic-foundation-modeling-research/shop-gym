/**
 * Browser suite of the storefront template: seeds and builds a copy of the
 * template, serves it over the in-process backend on the template's test
 * Dataset, and walks one shopper through real pages with the browser steps
 * that the final eval also uses. Each test is the next step of that
 * shopper's journey, so the tests run in order and share one browser
 * episode. Assertions read only pages and the episode's StateSnapshot from
 * the Control API. To cover one more page or flow, add a test that calls
 * one more step from `gen/build/verifiers/browser_steps.ts`.
 *
 * Not gated: it runs in every `pnpm test`. It needs `pnpm` on PATH,
 * Playwright Chromium and a built `packages/shop_backend`.
 */

import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { BrowserSession } from '@shop-gym/browser';
import {
  type StateSnapshot,
  createSandboxServer,
  loadShopData,
  stateSnapshotSchema,
} from '@shop-gym/shop-backend';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { seedTemplate } from './gen/build/seed.js';
import { freePort } from './gen/build/sidecar.js';
import { StorefrontSidecar } from './gen/build/storefront_sidecar.js';
import {
  addToCart,
  applyDiscountCode,
  logIn,
  logOut,
  placeOrder,
  register,
  rejectDiscountCode,
  showMoreReviews,
  sortReviews,
  viewOrder,
  viewOrderHistory,
  viewProduct,
  viewThankYou,
} from './gen/build/verifiers/browser_steps.js';
import { CHECKOUT_ADDRESS } from './gen/build/verifiers/storefront_target.js';
import { STOREFRONT_TEMPLATE_DIR } from './templates.js';

const FIXTURE_DIR = path.join(STOREFRONT_TEMPLATE_DIR, 'fixtures', 'sandbox_shop_v0');
const EPISODE_ID = 'storefront-template-browser';
const PRODUCT = { handle: 'shopliseum-mushroom-dog-toys', title: 'Shopliseum Mushroom Dog Toys' };
const PRODUCT_PATH = `/products/${PRODUCT.handle}`;
/** A product of the test Dataset with no Reviews. */
const NO_REVIEWS_PRODUCT = 'cartanvil-mackerel-and-sardines-70g';
const SHOPPER = {
  firstName: 'Suite',
  lastName: 'Shopper',
  email: 'suite.shopper@example.com',
  password: 'suite-password',
};
/** A seeded Persona of the test Dataset with three orders and three addresses. */
const PERSONA = { email: 'priya.nair@example.com', password: 'password123' };

let workDir: string;
let backend: ReturnType<typeof createSandboxServer>;
let backendUrl: string;
let sidecar: StorefrontSidecar;
let session: BrowserSession;
let orderNumber: number | undefined;

/** Number of the order placed by the checkout test; fails the test when none was placed. */
function placedOrderNumber(): number {
  expect(orderNumber, 'no order was placed').toBeDefined();
  return orderNumber ?? 0;
}

/** The episode's StateSnapshot, read through the Control API. */
async function snapshot(): Promise<StateSnapshot> {
  const response = await fetch(`${backendUrl}/__shopgym/episodes/${EPISODE_ID}/state`);
  expect(response.status).toBe(200);
  return stateSnapshotSchema.parse(await response.json());
}

/** Id of the shopper's customer in `state`; fails the test when absent. */
function shopperId(state: StateSnapshot): string {
  const customer = state.customers.find((entry) => entry.email === SHOPPER.email);
  expect(customer, `no customer ${SHOPPER.email} in the StateSnapshot`).toBeDefined();
  return customer?.id ?? '';
}

async function shopperSessionCount(): Promise<number> {
  const state = await snapshot();
  const customerId = shopperId(state);
  return state.sessions.filter((entry) => entry.customerId === customerId).length;
}

async function pageText(): Promise<string> {
  return session.page.locator('body').innerText();
}

function normalized(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

/** The product page's "Reviews" section. */
function reviewsSection() {
  return session.page.getByRole('region', { name: 'Reviews', exact: true });
}

/** Text of each Review block in the "Reviews" section, in page order. */
async function reviewBlocks(): Promise<string[]> {
  return (await reviewsSection().locator('article').allInnerTexts()).map(normalized);
}

async function reviewTitles(): Promise<string[]> {
  return reviewsSection().locator('article h3').allInnerTexts();
}

/** Text of each order history row, in page order. */
async function orderHistoryRows(): Promise<string[]> {
  const rows = await session.page.locator('table tbody tr').allInnerTexts();
  return rows.map((row) => row.replace(/\s+/g, ' ').trim());
}

describe('storefront template in a browser', () => {
  beforeAll(async () => {
    workDir = await fs.mkdtemp(path.join(os.tmpdir(), 'storefront-browser-'));
    const storefrontDir = path.join(workDir, 'storefront');
    await seedTemplate({ templateDir: STOREFRONT_TEMPLATE_DIR, destDir: storefrontDir });
    const backendPort = await freePort();
    backend = createSandboxServer({
      data: loadShopData(FIXTURE_DIR),
      dataDir: FIXTURE_DIR,
      port: backendPort,
    });
    await backend.listen();
    backendUrl = `http://127.0.0.1:${backendPort}`;
    sidecar = new StorefrontSidecar({
      storefrontDir,
      backendUrl,
      port: await freePort(),
      logPath: path.join(workDir, 'storefront.log'),
    });
    await sidecar.start();
    session = await BrowserSession.launch({ episodeId: EPISODE_ID });
  }, 600_000);

  afterAll(async () => {
    await session?.close();
    await sidecar?.stop();
    await backend?.close();
    if (workDir) await fs.rm(workDir, { recursive: true, force: true });
  });

  it('signs up a new customer', async () => {
    const outcome = await register(session.page, sidecar.url, SHOPPER);
    expect(outcome.ok, outcome.detail).toBe(true);
    const { customers } = await snapshot();
    expect(customers.find((customer) => customer.email === SHOPPER.email)).toMatchObject({
      firstName: SHOPPER.firstName,
      lastName: SHOPPER.lastName,
    });
  }, 60_000);

  it('logs out', async () => {
    const outcome = await logOut(session.page, sidecar.url);
    expect(outcome.ok, outcome.detail).toBe(true);
    expect(await shopperSessionCount()).toBe(0);
  }, 60_000);

  it('logs back in', async () => {
    const outcome = await logIn(session.page, sidecar.url, SHOPPER);
    expect(outcome.ok, outcome.detail).toBe(true);
    expect(await shopperSessionCount()).toBe(1);
  }, 60_000);

  it('reads the Reviews on a product page', async () => {
    const outcome = await viewProduct(session.page, sidecar.url, PRODUCT.handle);
    expect(outcome.ok, outcome.detail).toBe(true);
    // Near the title: the stars, the rating and the count. 23 stars over 6 Reviews is 3.8.
    const details = session.page.getByRole('region', { name: PRODUCT.title, exact: true });
    expect(await details.getByRole('img', { name: '3.8 out of 5.0 stars' }).count()).toBe(1);
    expect(normalized(await details.innerText())).toContain('3.8 / 5.0 (6)');

    const reviews = reviewsSection();
    expect(await reviews.getByRole('img', { name: '3.8 out of 5.0 stars' }).count()).toBe(1);
    expect(normalized(await reviews.innerText())).toContain('3.8 / 5.0 6 reviews');
    expect(await reviews.getByLabel('Sort by').locator('option').allTextContents()).toEqual([
      'Most recent',
      'Highest rating',
      'Lowest rating',
      'Most helpful',
    ]);
    // The first page holds five of the six Reviews, most recent first.
    expect(await reviewBlocks()).toEqual([
      'Too small for a large dog Our labrador can fit the whole toy in her mouth. Buy it for a small dog only. Ana P. December 14, 2025 Red Mushroom: Green Mushroom 1 person found this helpful',
      'Fine for gentle chewers Good for a dog that plays gently. A strong chewer gets through the fabric in a day. Sara M. Verified Buyer December 14, 2025 Red Mushroom: Red Mushroom 1 person found this helpful',
      'Still squeaking after a month Our terrier carries this everywhere. The squeaker still works after a month of daily play. Maya R. Verified Buyer November 20, 2025 Red Mushroom: Red Mushroom 4 people found this helpful',
      'Good, but the stem came off Soft and bright. After two weeks the stem came off, but the cap is still in one piece. Tom B. Verified Buyer October 2, 2025 Red Mushroom: Blue Mushroom 12 people found this helpful',
      "Our puppy's favourite The yellow one is easy to find in the grass. She brings it back every time. Leo K. Verified Buyer September 5, 2025 Red Mushroom: Yellow Mushroom",
    ]);
    const firstReview = reviews.locator('article').first();
    expect(await firstReview.getByRole('img', { name: '2 out of 5 stars' }).count()).toBe(1);
    // No "Write a Review" and no helpful-vote buttons: sorting and paging only.
    expect(await reviews.getByRole('button').allInnerTexts()).toEqual([
      'Sort',
      'Show more reviews',
    ]);
  }, 60_000);

  it('shows more Reviews until there are no more', async () => {
    const outcome = await showMoreReviews(session.page, sidecar.url, PRODUCT_PATH);
    expect(outcome.ok, outcome.detail).toBe(true);
    expect(await reviewTitles()).toEqual([
      'Too small for a large dog',
      'Fine for gentle chewers',
      'Still squeaking after a month',
      'Good, but the stem came off',
      "Our puppy's favourite",
      'Bright colours',
    ]);
    expect(await reviewsSection().getByRole('button', { name: 'Show more reviews' }).count()).toBe(
      0,
    );
  }, 60_000);

  it('sorts the Reviews by lowest rating and keeps the order on the next page', async () => {
    const sorted = await sortReviews(session.page, sidecar.url, PRODUCT_PATH, 'Lowest rating');
    expect(sorted.ok, sorted.detail).toBe(true);
    expect(await reviewTitles()).toEqual([
      'Too small for a large dog',
      'Fine for gentle chewers',
      'Good, but the stem came off',
      'Bright colours',
      'Still squeaking after a month',
    ]);
    const more = await showMoreReviews(session.page, sidecar.url, sorted.url ?? PRODUCT_PATH);
    expect(more.ok, more.detail).toBe(true);
    expect((await reviewTitles()).slice(4)).toEqual([
      'Still squeaking after a month',
      "Our puppy's favourite",
    ]);
  }, 60_000);

  it('shows no Reviews for a product with none', async () => {
    const outcome = await viewProduct(session.page, sidecar.url, NO_REVIEWS_PRODUCT);
    expect(outcome.ok, outcome.detail).toBe(true);
    expect(await reviewsSection().count()).toBe(0);
    expect(await session.page.getByRole('img', { name: /out of 5\.0 stars/ }).count()).toBe(0);
  }, 60_000);

  it('adds a product to the cart', async () => {
    const outcome = await addToCart(session.page, sidecar.url, PRODUCT.handle);
    expect(outcome.ok, outcome.detail).toBe(true);
    const { carts } = await snapshot();
    expect(carts.map((cart) => cart.lines.map((line) => line.quantity))).toEqual([[1]]);
  }, 60_000);

  it('turns down an unknown Discount code and keeps the price', async () => {
    const outcome = await rejectDiscountCode(session.page, sidecar.url, 'NOT-A-CODE');
    expect(outcome.ok, outcome.detail).toBe(true);
    const { carts } = await snapshot();
    expect(carts.map((cart) => cart.discountCodes)).toEqual([[]]);
  }, 60_000);

  it('applies a Discount code typed in lower case and changes the total', async () => {
    const outcome = await applyDiscountCode(session.page, sidecar.url, 'welcome10');
    expect(outcome.ok, outcome.detail).toBe(true);
    const { carts } = await snapshot();
    expect(carts.map((cart) => cart.appliedDiscountCode)).toEqual(['WELCOME10']);
  }, 60_000);

  it('places the order and lands on its thank-you page', async () => {
    const outcome = await placeOrder(session.page, sidecar.url, SHOPPER.email);
    expect(outcome.ok, outcome.detail).toBe(true);
    orderNumber = outcome.orderNumber;
    expect(outcome.url).toBe(`/checkout/confirmation/${orderNumber}`);
    const state = await snapshot();
    const customerId = shopperId(state);
    const orders = state.orders.filter((order) => order.customerId === customerId);
    expect(orders).toHaveLength(1);
    expect(orders[0]).toMatchObject({
      name: `#${orderNumber}`,
      email: SHOPPER.email,
      lineItems: [{ title: expect.stringContaining(PRODUCT.title), quantity: 1 }],
      // 19.99 less 10% (2.00), plus 9.99 standard shipping.
      discountCode: 'WELCOME10',
      discountAmount: '2.00',
      totalPrice: '27.98',
    });
  }, 60_000);

  it('shows the thank-you page of the order', async () => {
    const number = placedOrderNumber();
    const outcome = await viewThankYou(session.page, sidecar.url, number);
    expect(outcome.ok, outcome.detail).toBe(true);
    const text = await pageText();
    expect(text).toContain(`Confirmation #${number}`);
    expect(text).toContain(`Thank you, ${CHECKOUT_ADDRESS.firstName}!`);
    expect(text).toContain('WELCOME10');
    expect(text).toContain('Continue shopping');
  }, 60_000);

  it('lists the placed order in the account order history', async () => {
    const number = placedOrderNumber();
    const outcome = await viewOrderHistory(session.page, sidecar.url, number);
    expect(outcome.ok, outcome.detail).toBe(true);
    expect(await orderHistoryRows()).toEqual([
      // The Episode clock starts at 2026-01-01 and ticks one second for each change.
      `#${number} January 1, 2026 Paid Unfulfilled $27.98 CAD`,
    ]);
    // A new customer has no saved address.
    expect(await pageText()).toContain('View addresses (0)');
  }, 60_000);

  it('shows the order in the account order detail', async () => {
    const number = placedOrderNumber();
    const outcome = await viewOrder(session.page, sidecar.url, number);
    expect(outcome.ok, outcome.detail).toBe(true);
    const text = await pageText();
    expect(text).toContain('Return to Account details');
    expect(text).toContain(PRODUCT.title);
    expect(text).toContain('WELCOME10');
    expect(text).toContain('Shipping (Standard Shipping (5-7 days))');
    expect(text).toContain('Payment Status: Paid');
    expect(text).toContain('Fulfillment Status: Unfulfilled');
  }, 60_000);

  it('logs in as a seeded Persona and reads their order history', async () => {
    expect((await logOut(session.page, sidecar.url)).ok).toBe(true);
    const login = await logIn(session.page, sidecar.url, PERSONA);
    expect(login.ok, login.detail).toBe(true);
    const outcome = await viewOrderHistory(session.page, sidecar.url, 1006);
    expect(outcome.ok, outcome.detail).toBe(true);
    expect(await orderHistoryRows()).toEqual([
      '#1006 December 28, 2025 Paid Partially fulfilled $99.98 CAD',
      '#1004 November 8, 2025 Paid Fulfilled $37.97 CAD',
      '#1003 September 30, 2025 Refunded Fulfilled $64.98 CAD',
    ]);
    const text = await pageText();
    expect(text).toContain('Account details');
    expect(text).toContain('88 Harbord Street');
    expect(text).toContain('Toronto ON M5S 1G5');
    expect(text).toContain('+14165550199');
    expect(text).toContain('View addresses (3)');
  }, 60_000);

  it('reads one past order of the Persona', async () => {
    const outcome = await viewOrder(session.page, sidecar.url, 1004);
    expect(outcome.ok, outcome.detail).toBe(true);
    const text = await pageText();
    expect(text).toContain('Placed on November 8, 2025 at 10:30 am');
    expect(text).toContain('Carthaeum Toothbrush');
    // The toy has four variants, so its variant title shows; the toothbrush has one.
    expect(text).toContain('Green Mushroom');
    expect(text).not.toContain('Default Title');
    // 12.99 + 19.99 = 32.98, less SAVE5 (5.00), plus 9.99 standard shipping.
    expect(text).toMatch(/Subtotal\s+\$32\.98/);
    expect(text).toMatch(/Discount\s+SAVE5 -\$5\.00/);
    expect(text).toMatch(/Shipping \(Standard Shipping \(5-7 days\)\)\s+\$9\.99/);
    expect(text).toMatch(/Total\s+\$37\.97 CAD/);
    expect(text).toContain('Payment Status: Paid');
    expect(text).toContain('Fulfillment Status: Fulfilled');
    expect(text).toContain('88 Harbord Street');
  }, 60_000);
});
