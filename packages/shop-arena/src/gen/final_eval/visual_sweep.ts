/**
 * The visual sweep: the canonical pages of a shop, captured in one browser
 * episode and judged with the build loop's rubric. Pages that need state
 * (a cart line, a logged-in customer, an existing order) set it up through
 * the same fixed browser scripts the functional sweep uses; when the
 * dataset cannot provide that state the page is recorded as skipped.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { LlmClient, ModelRef } from '@shop-gym/agent';
import type { BrowserSession } from '@shop-gym/browser';

import { addToCart, logIn, placeOrder } from '../build/verifiers/browser_steps.js';
import {
  type PageCapture,
  type PageJudgement,
  capturePage,
  judgeContext,
  judgePage,
  loadJudgeRubric,
  mapConcurrent,
} from '../build/verifiers/page_judge.js';
import { readSeededCustomer } from '../build/verifiers/storefront_target.js';
import {
  type DatasetHandles,
  type PageBucket,
  SWEEP_CAPS,
  sampleProductHandles,
  searchToken,
} from '../build/verifiers/task_routes.js';

const JUDGE_CONCURRENCY = 3;

export interface CanonicalPage {
  readonly name: string;
  readonly route: string;
  readonly bucket: PageBucket;
}

export interface SkippedPage extends CanonicalPage {
  readonly status: 'skipped';
  readonly reason: string;
}

export interface JudgedPage extends CanonicalPage {
  readonly status: 'pass' | 'fail';
  readonly judgement: PageJudgement;
}

export type VisualPageResult = SkippedPage | JudgedPage;

export interface VisualSweepOptions {
  readonly session: BrowserSession;
  readonly storefrontUrl: string;
  readonly dataDir: string;
  readonly manualDir?: string;
  readonly handles: DatasetHandles;
  readonly llm: LlmClient;
  readonly model: ModelRef;
  readonly screenshotsDir: string;
  readonly signal?: AbortSignal;
  readonly log: (line: string) => void;
}

/** Capture every canonical page, then judge them with bounded concurrency. */
export async function runVisualSweep(options: VisualSweepOptions): Promise<VisualPageResult[]> {
  const { session, storefrontUrl, handles } = options;
  const rubric = await loadJudgeRubric();
  const captures: { page: CanonicalPage; capture: PageCapture }[] = [];
  const results: VisualPageResult[] = [];
  const capture = async (page: CanonicalPage): Promise<void> => {
    options.signal?.throwIfAborted();
    options.log(`final_eval: capturing ${page.name} ${page.route}`);
    captures.push({
      page,
      capture: await capturePage({
        session,
        baseUrl: storefrontUrl,
        route: page.route,
        outDir: options.screenshotsDir,
        slug: page.name,
      }),
    });
  };
  const skip = (page: CanonicalPage, reason: string): void => {
    results.push({ ...page, status: 'skipped', reason });
  };

  const collection = handles.collections[0]?.handle;
  const productHandle = sampleProductHandles(handles, SWEEP_CAPS)[0];
  const policy = handles.policies[0];

  await capture({ name: 'home', route: '/', bucket: 'homepage' });
  const collectionPage: CanonicalPage = {
    name: 'collection',
    route: `/collections/${collection ?? ''}`,
    bucket: 'collections',
  };
  if (collection === undefined) {
    skip(collectionPage, 'the dataset has no collection');
  } else {
    await capture(collectionPage);
  }
  const productPage: CanonicalPage = {
    name: 'product',
    route: `/products/${productHandle ?? ''}`,
    bucket: 'product',
  };
  if (productHandle === undefined) {
    skip(productPage, 'the dataset has no product');
  } else {
    await capture(productPage);
  }
  await capture({
    name: 'search',
    route: `/search?q=${encodeURIComponent(searchToken(handles))}`,
    bucket: 'cart_search',
  });
  await capture({ name: 'accountLogin', route: '/account/login', bucket: 'account' });
  const policyPage: CanonicalPage = {
    name: 'policy',
    route: `/policies/${policy ?? ''}`,
    bucket: 'info_pages',
  };
  if (policy === undefined) {
    skip(policyPage, 'the dataset has no policy');
  } else {
    await capture(policyPage);
  }

  const cartPage: CanonicalPage = { name: 'cart', route: '/cart', bucket: 'cart_search' };
  const checkoutPage: CanonicalPage = {
    name: 'checkout',
    route: '/checkout',
    bucket: 'cart_search',
  };
  const thankYouPage = (orderNumber: number | undefined): CanonicalPage => ({
    name: 'thankYou',
    route: `/checkout/confirmation/${orderNumber ?? ''}`,
    bucket: 'cart_search',
  });
  const added =
    productHandle === undefined
      ? { ok: false, detail: 'the dataset has no product' }
      : await addToCart(session.page, storefrontUrl, productHandle);
  if (added.ok) {
    await capture(cartPage);
    await capture(checkoutPage);
    const order = await placeOrder(session.page, storefrontUrl, 'visual.sweep@example.com');
    if (order.orderNumber === undefined) {
      skip(thankYouPage(undefined), `could not place an order: ${order.detail}`);
    } else {
      await capture(thankYouPage(order.orderNumber));
    }
  } else {
    skip(cartPage, `could not add to cart: ${added.detail}`);
    skip(checkoutPage, `could not add to cart: ${added.detail}`);
    skip(thankYouPage(undefined), `could not add to cart: ${added.detail}`);
  }

  const profilePage: CanonicalPage = {
    name: 'accountProfile',
    route: '/account',
    bucket: 'account',
  };
  const customer = await readSeededCustomer(options.dataDir);
  const orderId =
    customer === undefined ? undefined : await seededOrderId(options.dataDir, customer.email);
  const orderPage: CanonicalPage = {
    name: 'orderDetail',
    route: `/account/orders/${orderId ?? ''}`,
    bucket: 'account',
  };
  const login =
    customer === undefined
      ? { ok: false, detail: 'the dataset has no seeded customer' }
      : await logIn(session.page, storefrontUrl, customer);
  if (login.ok) {
    await capture(profilePage);
    if (orderId === undefined) {
      skip(orderPage, 'the seeded customer has no order');
    } else {
      await capture(orderPage);
    }
  } else {
    skip(profilePage, `could not log in: ${login.detail}`);
    skip(orderPage, `could not log in: ${login.detail}`);
  }

  const judged = await mapConcurrent(
    captures,
    JUDGE_CONCURRENCY,
    async ({ page, capture: shot }) => {
      options.signal?.throwIfAborted();
      const context = await judgeContext(options.manualDir, [page.bucket]);
      const judgement = await judgePage({
        llm: options.llm,
        model: options.model,
        rubric,
        capture: shot,
        context,
        ...(options.signal !== undefined ? { signal: options.signal } : {}),
      });
      options.log(
        `final_eval: ${page.name} ${judgement.effective} (score ${judgement.verdict.score})`,
      );
      return { ...page, status: judgement.effective, judgement } satisfies JudgedPage;
    },
  );
  return [...judged, ...results];
}

/** The id of the first order in `orders.json` placed by `email`. */
async function seededOrderId(dataDir: string, email: string): Promise<string | undefined> {
  const raw = await fs.readFile(path.join(dataDir, 'orders.json'), 'utf-8').catch(() => undefined);
  if (raw === undefined) {
    return undefined;
  }
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    return undefined;
  }
  for (const order of parsed) {
    if (typeof order === 'object' && order !== null) {
      const { id, email: orderEmail } = order as { id?: unknown; email?: unknown };
      if (orderEmail === email && (typeof id === 'number' || typeof id === 'string')) {
        return String(id);
      }
    }
  }
  return undefined;
}
