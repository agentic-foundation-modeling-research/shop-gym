/**
 * A fresh browser for every Iteration of Storefront exploration.
 *
 * Each Iteration gets its own BrowserSession, so it starts with no cookies,
 * storage or cart from earlier Iterations. The Browser tools in `tools` act
 * on the browser of the current Iteration.
 *
 * After a tool call that loaded a page, the page is checked for bot-check
 * markers; on a bot check the tool result tells the agent not to try to
 * pass it, and `click`, `type`, `select` and `press` on that page are
 * refused. `navigate` refuses after `NAVIGATION_CAP` calls in one run.
 */

import type { Tool, ToolContext, ToolResult } from '@shop-gym/agent';
import { BrowserSession, browserTools } from '@shop-gym/browser';
import { z } from 'zod';
import { botCheckMarker } from './bot-check.js';

/** How long the start page and the cart read may take. */
const START_TIMEOUT_MS = 30_000;

/**
 * The most `navigate` calls in one run of the explore step, over all its
 * Iterations. The start page of an Iteration does not count.
 */
export const NAVIGATION_CAP = 200;

/** A bot-check page that the browser came to. */
export interface BotCheck {
  readonly url: string;
  /** The bot-check marker found in the page HTML. */
  readonly marker: string;
}

const cartSchema = z.object({
  items: z.array(z.object({ variant_id: z.number(), quantity: z.number() })),
});

/** The lines of a Shopify `/cart.js` cart. */
export type Cart = z.infer<typeof cartSchema>;

/** Where the browser of one Iteration starts. */
export interface StartState {
  /** The page URL after the start URL loaded, redirects included. */
  readonly url: string;
  /** The cart, or `null` when the shop has no cart URL or `error` is set. */
  readonly cart: Cart | null;
  /** Why the start URL or the cart could not be read, or `null`. */
  readonly error: string | null;
}

export interface IterationBrowserOptions {
  /** Sent as `x-shopgym-episode` by every browser. */
  readonly episodeId: string;
  /** The page that every Iteration starts on. */
  readonly startUrl: string;
  /** The shop's `/cart.js`, read at each start. Omit it when the shop does not serve one. */
  readonly cartUrl?: string;
}

/** A body of `/cart.js` parsed to its lines, or `null` when it is not a cart. */
export function parseCart(text: string): Cart | null {
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return null;
  }
  const result = cartSchema.safeParse(body);
  return result.success ? result.data : null;
}

export class IterationBrowser {
  /** The Browser tools. Each call goes to the browser of the current Iteration. */
  readonly tools: readonly Tool[];
  private session: BrowserSession;
  private sessionTools: ReadonlyMap<string, Tool>;
  /** The session from `launch` is unused until the first `start`. */
  private started = false;
  /** Set when the page loaded a document that no bot check has read yet. */
  private pageLoaded = false;
  /** The HTTP status of the last document of the main frame, or `null` before the first. */
  private documentStatus: number | null = null;
  private navigations = 0;
  private iterationBotCheck: BotCheck | null = null;

  private constructor(
    private readonly options: IterationBrowserOptions,
    session: BrowserSession,
  ) {
    this.session = session;
    this.sessionTools = toolsByName(session);
    this.watchPageLoads(session);
    this.tools = [...this.sessionTools.values()].map((tool) => ({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
      execute: (params, ctx) => this.execute(tool.name, params, ctx),
    }));
  }

  /** Launches the browser of the first Iteration. */
  static async launch(options: IterationBrowserOptions): Promise<IterationBrowser> {
    return new IterationBrowser(options, await launchSession(options));
  }

  /**
   * Gives the next Iteration a new browser, opens the start URL in it, and
   * returns the start state. The browser of the previous Iteration closes.
   */
  async start(): Promise<StartState> {
    if (this.started) {
      const next = await launchSession(this.options);
      await this.session.close();
      this.session = next;
      this.sessionTools = toolsByName(next);
      this.watchPageLoads(next);
    }
    this.started = true;
    this.pageLoaded = false;
    this.documentStatus = null;
    this.iterationBotCheck = null;
    const { page } = this.session;
    try {
      await page.goto(this.options.startUrl, {
        timeout: START_TIMEOUT_MS,
        waitUntil: 'domcontentloaded',
      });
    } catch (error) {
      return { url: page.url(), cart: null, error: firstLine(error) };
    }
    if (this.options.cartUrl === undefined) {
      return { url: page.url(), cart: null, error: null };
    }
    return { url: page.url(), ...(await this.readCart(this.options.cartUrl)) };
  }

  /** Closes the browser of the last Iteration. */
  close(): Promise<void> {
    return this.session.close();
  }

  /** The first bot-check page of the current Iteration, or `null` when it met none. */
  get botCheck(): BotCheck | null {
    return this.iterationBotCheck;
  }

  /** True when this run has made `NAVIGATION_CAP` `navigate` calls. */
  get navigationCapReached(): boolean {
    return this.navigations >= NAVIGATION_CAP;
  }

  /**
   * Runs one Browser tool call on the current browser. A `navigate` call at
   * the cap is refused. A page action (`PAGE_ACTIONS`) on a bot-check page
   * is refused, and the result is the bot-check notice. A bot check on a
   * page that loaded since the last check adds the notice to the result.
   * The start page of an Iteration is checked at its first tool call.
   */
  private async execute(name: string, params: unknown, ctx: ToolContext): Promise<ToolResult> {
    if (name === 'navigate') {
      if (this.navigationCapReached) {
        return { content: [{ type: 'text', text: NAVIGATION_CAP_REFUSAL }], isError: true };
      }
      this.navigations += 1;
    }
    if (PAGE_ACTIONS.has(name)) {
      // The page is read again even with no new document, because a script
      // can change it in place.
      const botCheck = await this.checkPage();
      if (botCheck !== null) {
        return {
          content: [{ type: 'text', text: pageActionRefusal(name, botCheck) }],
          isError: true,
        };
      }
    }
    const result = await this.currentTool(name).execute(params, ctx);
    const botCheck = this.pageLoaded ? await this.checkPage() : null;
    if (botCheck === null) {
      return result;
    }
    return {
      ...result,
      content: [...result.content, { type: 'text', text: botCheckNotice(botCheck) }],
    };
  }

  /**
   * Reads the current page and returns its bot check, or `null` when the
   * page is not a bot check or could not be read. The first bot check of
   * an Iteration is kept for `botCheck`.
   */
  private async checkPage(): Promise<BotCheck | null> {
    this.pageLoaded = false;
    const { page } = this.session;
    let html: string;
    try {
      html = await page.content();
    } catch {
      // The page could not be read, for example because it navigates again.
      // The flag stays set, so the next tool call reads the page.
      this.pageLoaded = true;
      return null;
    }
    const marker = botCheckMarker(html, this.documentStatus);
    if (marker === undefined) {
      return null;
    }
    const botCheck = { url: page.url(), marker };
    this.iterationBotCheck ??= botCheck;
    return botCheck;
  }

  private watchPageLoads(session: BrowserSession): void {
    const { page } = session;
    page.on('response', (response) => {
      const request = response.request();
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) {
        this.documentStatus = response.status();
      }
    });
    page.on('domcontentloaded', () => {
      this.pageLoaded = true;
    });
  }

  /** The cart of this browser's cookies, or why it could not be read. */
  private async readCart(cartUrl: string): Promise<Pick<StartState, 'cart' | 'error'>> {
    let ok: boolean;
    let status: number;
    let body: string;
    try {
      const response = await this.session.context.request.get(cartUrl, {
        timeout: START_TIMEOUT_MS,
      });
      ok = response.ok();
      status = response.status();
      body = await response.text();
    } catch (error) {
      return { cart: null, error: `${cartUrl} did not load: ${firstLine(error)}` };
    }
    if (!ok) {
      return { cart: null, error: `${cartUrl} returned HTTP ${status}` };
    }
    const cart = parseCart(body);
    return cart === null
      ? { cart: null, error: `${cartUrl} did not return a cart` }
      : { cart, error: null };
  }

  private currentTool(name: string): Tool {
    const tool = this.sessionTools.get(name);
    if (tool === undefined) {
      throw new Error(`the browser of this Iteration has no tool '${name}'`);
    }
    return tool;
  }
}

/** Added to a tool result that ends on a bot-check page. */
function botCheckNotice({ url, marker }: BotCheck): string {
  return [
    `Bot check: this page is a bot check, not a page of the shop (${url}, marker "${marker}").`,
    'Do not try to pass it: do not solve it, click through it, wait for it to clear or open it again, and do not describe it in any file.',
    'If you work on a Plan task, mark it blocked: set its line in plan.md to `[!]`, append the reason "bot check" to its brief after a `;`, and end this iteration.',
    'If you write the plan, plan only from the pages that you could read.',
  ].join('\n');
}

/**
 * The Browser tools that act on the page, so they could pass a bot check:
 * they are refused on a bot-check page. `navigate` and `back` leave the
 * page and stay allowed.
 */
const PAGE_ACTIONS: ReadonlySet<string> = new Set(['click', 'type', 'select', 'press']);

/** The result of a page action on a bot-check page. */
function pageActionRefusal(tool: string, botCheck: BotCheck): string {
  return [
    `${tool} refused: the current page is a bot check, so the action did not run.`,
    botCheckNotice(botCheck),
  ].join('\n');
}

/** The result of a `navigate` call at the cap. */
const NAVIGATION_CAP_REFUSAL = [
  `navigate refused: this run has made its cap of ${NAVIGATION_CAP} navigate calls, so the page did not change.`,
  'Do not call navigate again. Finish your Plan task with what you have, or mark it `[!]` with the reason "navigation cap", and end this iteration.',
].join('\n');

function launchSession(options: IterationBrowserOptions): Promise<BrowserSession> {
  return BrowserSession.launch({ episodeId: options.episodeId });
}

function toolsByName(session: BrowserSession): ReadonlyMap<string, Tool> {
  return new Map(browserTools(session).map((tool) => [tool.name, tool]));
}

/** The first line of an error message; Playwright appends a call log after it. */
function firstLine(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.split('\n')[0] ?? message;
}
