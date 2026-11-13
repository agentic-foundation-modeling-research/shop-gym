/**
 * The canonical pages of a shop and the one fixed walk over them. The
 * build-loop `page_lint` verifier and the final eval both walk this list,
 * so a shop that passes the checks in the build loop passes the same
 * checks on the same pages in the final eval.
 *
 * Pages that need state (a cart line, a logged-in customer, an existing
 * order) get it from the fixed browser scripts of `browser_steps`, in a
 * fixed order: the guest pages, then a cart line (the open cart drawer, the
 * cart and checkout), then one order (its thank-you page), then the seeded
 * customer's session (the account pages). The walk sets up a state only
 * when a selected page needs it. A page whose state the dataset or the
 * storefront cannot give is returned as skipped, with the reason.
 */

import type { BrowserSession } from '@shop-gym/browser';

import { addToCart, logIn, placeOrder } from './browser_steps.js';
import { readSeededCustomer, readSeededOrderId } from './storefront_target.js';
import {
  type DatasetHandles,
  type PageBucket,
  SWEEP_CAPS,
  sampleProductHandles,
  searchToken,
} from './task_routes.js';

type Page = BrowserSession['page'];

/** The element that the storefront renders for its open cart drawer. */
export const CART_DRAWER_SELECTOR = '#cart-drawer';
const NAVIGATION_TIMEOUT_MS = 30_000;

export interface CanonicalPage {
  readonly name: string;
  readonly route: string;
  readonly bucket: PageBucket;
}

export interface SkippedPage extends CanonicalPage {
  readonly status: 'skipped';
  readonly reason: string;
}

/** The route that shows `productHandle`'s page with the cart drawer open over it. */
export function cartDrawerRoute(productHandle: string): string {
  return `/products/${productHandle}?cart=open`;
}

/**
 * Load `route` and tell whether it shows the open cart drawer. A storefront
 * without a cart drawer (or a route that does not load) gives `false`.
 */
export async function opensCartDrawer(
  page: Page,
  baseUrl: string,
  route: string,
): Promise<boolean> {
  try {
    await page.goto(`${baseUrl}${route}`, { waitUntil: 'load', timeout: NAVIGATION_TIMEOUT_MS });
  } catch {
    return false;
  }
  return page.locator(CART_DRAWER_SELECTOR).first().isVisible();
}

/**
 * Whether `page` belongs to `buckets`. The header and footer show on every
 * page, so the `navigation` bucket selects the home page.
 */
export function pageInBuckets(page: CanonicalPage, buckets: readonly PageBucket[]): boolean {
  return buckets.includes(page.bucket) || (page.name === 'home' && buckets.includes('navigation'));
}

export interface WalkShopPagesOptions {
  readonly session: BrowserSession;
  readonly baseUrl: string;
  readonly dataDir: string;
  readonly handles: DatasetHandles;
  /** Walk only the pages of these buckets (see `pageInBuckets`); every page when omitted. */
  readonly buckets?: readonly PageBucket[];
  /** The email of the guest order that the walk places for the thank-you page. */
  readonly orderEmail: string;
  /** Called with the session on `page`'s state; it loads `page.route` itself. */
  readonly visit: (page: CanonicalPage) => Promise<void>;
}

/** Walk the canonical pages in order; returns the selected pages that were skipped. */
export async function walkShopPages(options: WalkShopPagesOptions): Promise<SkippedPage[]> {
  const { session, baseUrl, handles } = options;
  const skipped: SkippedPage[] = [];
  const selected = (page: CanonicalPage): boolean =>
    options.buckets === undefined || pageInBuckets(page, options.buckets);
  const visit = async (page: CanonicalPage): Promise<void> => {
    if (selected(page)) await options.visit(page);
  };
  const skip = (page: CanonicalPage, reason: string): void => {
    if (selected(page)) skipped.push({ ...page, status: 'skipped', reason });
  };
  const visitUnless = async (page: CanonicalPage, missing: string | undefined): Promise<void> => {
    if (missing === undefined) {
      await visit(page);
    } else {
      skip(page, missing);
    }
  };

  const collection = handles.collections[0]?.handle;
  const productHandle = sampleProductHandles(handles, SWEEP_CAPS)[0];
  const policy = handles.policies[0];
  const noProduct = productHandle === undefined ? 'the dataset has no product' : undefined;

  await visit({ name: 'home', route: '/', bucket: 'homepage' });
  await visitUnless(
    { name: 'collection', route: `/collections/${collection ?? ''}`, bucket: 'collections' },
    collection === undefined ? 'the dataset has no collection' : undefined,
  );
  await visitUnless(
    { name: 'product', route: `/products/${productHandle ?? ''}`, bucket: 'product' },
    noProduct,
  );
  await visit({
    name: 'search',
    route: `/search?q=${encodeURIComponent(searchToken(handles))}`,
    bucket: 'cart_search',
  });
  await visit({ name: 'accountLogin', route: '/account/login', bucket: 'account' });
  await visit({ name: 'accountRegister', route: '/account/register', bucket: 'account' });
  await visitUnless(
    { name: 'policy', route: `/policies/${policy ?? ''}`, bucket: 'info_pages' },
    policy === undefined ? 'the dataset has no policy' : undefined,
  );

  const drawerPage: CanonicalPage = {
    name: 'cartDrawer',
    route: cartDrawerRoute(productHandle ?? ''),
    bucket: 'cart_search',
  };
  const cartPage: CanonicalPage = { name: 'cart', route: '/cart', bucket: 'cart_search' };
  const checkoutPage: CanonicalPage = { name: 'checkout', route: '/checkout', bucket: 'checkout' };
  const thankYouPage = (orderNumber: number | undefined): CanonicalPage => ({
    name: 'thankYou',
    route: `/checkout/confirmation/${orderNumber ?? ''}`,
    bucket: 'checkout',
  });
  const cartPages = [drawerPage, cartPage, checkoutPage, thankYouPage(undefined)];
  if (cartPages.some(selected)) {
    const added =
      productHandle === undefined
        ? { ok: false, detail: 'the dataset has no product' }
        : await addToCart(session.page, baseUrl, productHandle);
    if (added.ok) {
      if (selected(drawerPage)) {
        const opens = await opensCartDrawer(session.page, baseUrl, drawerPage.route);
        await visitUnless(drawerPage, opens ? undefined : 'the storefront has no cart drawer');
      }
      await visit(cartPage);
      await visit(checkoutPage);
      if (selected(thankYouPage(undefined))) {
        const order = await placeOrder(session.page, baseUrl, options.orderEmail);
        await visitUnless(
          thankYouPage(order.orderNumber),
          order.orderNumber === undefined ? `could not place an order: ${order.detail}` : undefined,
        );
      }
    } else {
      for (const page of cartPages) skip(page, `could not add to cart: ${added.detail}`);
    }
  }

  const customer = await readSeededCustomer(options.dataDir);
  const orderId =
    customer === undefined ? undefined : await readSeededOrderId(options.dataDir, customer.email);
  const profilePage: CanonicalPage = {
    name: 'accountProfile',
    route: '/account',
    bucket: 'account',
  };
  const orderListPage: CanonicalPage = {
    name: 'orderList',
    route: '/account/orders',
    bucket: 'account',
  };
  const orderPage: CanonicalPage = {
    name: 'orderDetail',
    route: `/account/orders/${orderId ?? ''}`,
    bucket: 'account',
  };
  const addressesPage: CanonicalPage = {
    name: 'addresses',
    route: '/account/addresses',
    bucket: 'account',
  };
  const memberPages = [profilePage, orderListPage, orderPage, addressesPage];
  if (memberPages.some(selected)) {
    const login =
      customer === undefined
        ? { ok: false, detail: 'the dataset has no seeded customer' }
        : await logIn(session.page, baseUrl, customer);
    if (login.ok) {
      await visit(profilePage);
      await visit(orderListPage);
      await visitUnless(
        orderPage,
        orderId === undefined ? 'the seeded customer has no order' : undefined,
      );
      await visit(addressesPage);
    } else {
      for (const page of memberPages) skip(page, `could not log in: ${login.detail}`);
    }
  }
  return skipped;
}
