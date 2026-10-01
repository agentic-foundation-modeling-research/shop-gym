/**
 * One Playwright browser context per episode.
 *
 * Every request the context makes carries `x-shopgym-episode: <id>` so the
 * sandbox backend can keep per-episode state (login, cart, orders) apart
 * while many episodes share one hosted shop.
 */

import { type Browser, type BrowserContext, type Page, chromium } from 'playwright';

/** What the agent reported through the `finish` tool. */
export interface FinishResult {
  readonly answer?: string;
  readonly infeasible: boolean;
  readonly reason?: string;
}

/** Options for `BrowserSession.launch`. */
export interface BrowserSessionOptions {
  /** Sent as `x-shopgym-episode` on every request. */
  readonly episodeId: string;
  /** Resolves relative `navigate` URLs. */
  readonly baseUrl?: string;
  /** Defaults to `true`. */
  readonly headless?: boolean;
  /** Defaults to 1280x800. */
  readonly viewport?: { readonly width: number; readonly height: number };
  /** Record a video of every page into this directory. */
  readonly video?: { readonly dir: string };
  /** Write a Playwright trace zip to this path on `close()`. */
  readonly trace?: { readonly path: string };
  /** Offer the `evaluate` tool. Keep off for solvers. Defaults to `false`. */
  readonly evaluateEnabled?: boolean;
}

/** The storage state of a context, as returned by `BrowserContext.storageState`. */
export type StorageState = Awaited<ReturnType<BrowserContext['storageState']>>;

/** A chromium browser, one context, and one page bound to an episode. */
export class BrowserSession {
  readonly episodeId: string;
  readonly baseUrl: string | undefined;
  readonly evaluateEnabled: boolean;
  readonly context: BrowserContext;
  readonly page: Page;
  /** Set by the `finish` tool; `undefined` until the agent finishes. */
  finished: FinishResult | undefined;

  private readonly browser: Browser;
  private readonly tracePath: string | undefined;

  private constructor(
    options: BrowserSessionOptions,
    browser: Browser,
    context: BrowserContext,
    page: Page,
  ) {
    this.episodeId = options.episodeId;
    this.baseUrl = options.baseUrl;
    this.evaluateEnabled = options.evaluateEnabled ?? false;
    this.browser = browser;
    this.context = context;
    this.page = page;
    this.tracePath = options.trace?.path;
  }

  /** Launches chromium and opens one context and page for the episode. */
  static async launch(options: BrowserSessionOptions): Promise<BrowserSession> {
    const browser = await chromium.launch({ headless: options.headless ?? true });
    const context = await browser.newContext({
      viewport: options.viewport ?? { width: 1280, height: 800 },
      extraHTTPHeaders: { 'x-shopgym-episode': options.episodeId },
      ...(options.video ? { recordVideo: { dir: options.video.dir } } : {}),
    });
    if (options.trace) {
      await context.tracing.start({ screenshots: true, snapshots: true });
    }
    const page = await context.newPage();
    return new BrowserSession(options, browser, context, page);
  }

  /** Cookies and local storage of the context, for graders. */
  storageState(): Promise<StorageState> {
    return this.context.storageState();
  }

  /** Stops tracing and video (if enabled) and closes the browser. */
  async close(): Promise<void> {
    if (this.tracePath !== undefined) {
      await this.context.tracing.stop({ path: this.tracePath });
    }
    // Closing the context flushes any video files before the browser exits.
    await this.context.close();
    await this.browser.close();
  }
}
