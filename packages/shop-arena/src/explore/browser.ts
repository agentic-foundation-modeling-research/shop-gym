/**
 * A fresh browser for every Iteration of Storefront exploration.
 *
 * Each Iteration gets its own BrowserSession, so it starts with no cookies,
 * storage or cart from earlier Iterations. The Browser tools in `tools` act
 * on the browser of the current Iteration.
 */

import type { Tool } from '@shop-gym/agent';
import { BrowserSession, browserTools } from '@shop-gym/browser';
import { z } from 'zod';

/** How long the start page and the cart read may take. */
const START_TIMEOUT_MS = 30_000;

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
  /** The storefront origin. A site path given to `navigate`, such as `/cart`, opens on it. */
  readonly baseUrl: string;
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

  private constructor(
    private readonly options: IterationBrowserOptions,
    session: BrowserSession,
  ) {
    this.session = session;
    this.sessionTools = toolsByName(session);
    this.tools = [...this.sessionTools.values()].map((tool) => ({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
      execute: (params, ctx) => this.currentTool(tool.name).execute(params, ctx),
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
    }
    this.started = true;
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

function launchSession(options: IterationBrowserOptions): Promise<BrowserSession> {
  return BrowserSession.launch({ episodeId: options.episodeId, baseUrl: options.baseUrl });
}

function toolsByName(session: BrowserSession): ReadonlyMap<string, Tool> {
  return new Map(browserTools(session).map((tool) => [tool.name, tool]));
}

/** The first line of an error message; Playwright appends a call log after it. */
function firstLine(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.split('\n')[0] ?? message;
}
