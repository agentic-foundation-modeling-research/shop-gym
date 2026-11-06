/**
 * A fresh browser for every Iteration of Storefront exploration.
 *
 * Each Iteration gets its own BrowserSession, so it starts with no cookies,
 * storage or cart from earlier Iterations. The Browser tools in `tools` act
 * on the browser of the current Iteration. Their `snapshot` shows a long
 * accessibility tree in parts, so a few snapshots of a long page do not
 * fill the model's context.
 */

import type { Tool } from '@shop-gym/agent';
import {
  BrowserSession,
  type PageSnapshot,
  browserTools,
  formatSnapshot,
  snapshotPage,
} from '@shop-gym/browser';
import { Type } from '@sinclair/typebox';
import { z } from 'zod';

/** How long the start page and the cart read may take. */
const START_TIMEOUT_MS = 30_000;

/** Characters of the accessibility tree that one `snapshot` result shows. */
const SNAPSHOT_MAX_CHARS = 50_000;

const SNAPSHOT_PARAMETERS = Type.Object({
  offset: Type.Optional(
    Type.Integer({
      minimum: 0,
      description: 'Character offset into the tree, from the note of a cut snapshot.',
    }),
  ),
});

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
    this.tools = [...this.sessionTools.values()].map((tool) =>
      tool.name === 'snapshot'
        ? this.snapshotTool(tool.description)
        : {
            name: tool.name,
            description: tool.description,
            parameters: tool.parameters,
            execute: (params, ctx) => this.currentTool(tool.name).execute(params, ctx),
          },
    );
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

  /** `snapshot` of the current page that shows a long tree in parts. */
  private snapshotTool(description: string): Tool<typeof SNAPSHOT_PARAMETERS> {
    return {
      name: 'snapshot',
      description: `${description} A tree longer than ${SNAPSHOT_MAX_CHARS} characters comes in parts; the note after a part gives the offset of the next one.`,
      parameters: SNAPSHOT_PARAMETERS,
      execute: async ({ offset }) => {
        try {
          const snapshot = await snapshotPage(this.session.page);
          return { content: [{ type: 'text', text: snapshotPart(snapshot, offset ?? 0) }] };
        } catch (error) {
          return { content: [{ type: 'text', text: `Error: ${firstLine(error)}` }], isError: true };
        }
      },
    };
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

/**
 * The snapshot text for the tree from `offset`.
 *
 * A tree that fits shows whole. A longer tree shows in parts of at most
 * `SNAPSHOT_MAX_CHARS` characters. A part ends at the end of a line, so it
 * does not split an element line or a ref. Only a line longer than the
 * limit is cut inside the line. A note after each part gives the range
 * that the part shows and the offset of the next part.
 */
function snapshotPart(snapshot: PageSnapshot, offset: number): string {
  const { aria } = snapshot;
  const start = partStart(aria, offset);
  if (start === 0 && aria.length <= SNAPSHOT_MAX_CHARS) {
    return formatSnapshot(snapshot);
  }
  const limit = start + SNAPSHOT_MAX_CHARS;
  if (limit >= aria.length) {
    const part = formatSnapshot({ ...snapshot, aria: aria.slice(start) });
    return `${part}\n\n[Last part of the snapshot: characters ${start}-${aria.length} of ${aria.length}.]`;
  }
  // Cut at the end of the last whole line. A line longer than the limit is cut at the limit.
  const newline = aria.lastIndexOf('\n', limit);
  const end = newline > start ? newline : limit;
  const next = newline > start ? newline + 1 : limit;
  const part = formatSnapshot({ ...snapshot, aria: aria.slice(start, end) });
  const note = [
    `Snapshot cut: this part shows characters ${start}-${end} of ${aria.length}.`,
    `To see the rest, call snapshot with offset ${next}.`,
    'Scrolling does not change the snapshot, because it always covers the whole page.',
    'Refs from every part stay valid until the page changes.',
  ].join(' ');
  return `${part}\n\n[${note}]`;
}

/**
 * Where the part for `offset` starts. An offset inside a line moves to the
 * start of the next line. Thus a part does not start with half a ref, even
 * when the page changed after the last part. An offset inside a line longer
 * than `SNAPSHOT_MAX_CHARS` does not move, because the parts cut such a line.
 */
function partStart(aria: string, offset: number): number {
  const start = Math.min(offset, aria.length);
  if (start === 0 || aria[start - 1] === '\n') {
    return start;
  }
  const lineStart = aria.lastIndexOf('\n', start - 1) + 1;
  const newline = aria.indexOf('\n', start);
  const lineEnd = newline === -1 ? aria.length : newline;
  return lineEnd - lineStart > SNAPSHOT_MAX_CHARS ? start : Math.min(lineEnd + 1, aria.length);
}

function toolsByName(session: BrowserSession): ReadonlyMap<string, Tool> {
  return new Map(browserTools(session).map((tool) => [tool.name, tool]));
}

/** The first line of an error message; Playwright appends a call log after it. */
function firstLine(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.split('\n')[0] ?? message;
}
