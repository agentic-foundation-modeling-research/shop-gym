/**
 * Browser tools for an `AgentRuntime`.
 *
 * Every tool acts on the session's page and reports what happened as text.
 * Element tools take a `ref` from the latest `snapshot`. Action tools end
 * with the page's URL and title so the model knows where it is without a
 * full snapshot. Failures (bad ref, timeout, invalid URL) come back as
 * `isError: true` results; `execute` never throws.
 */

import type { Tool, ToolResult } from '@shop-gym/agent';
import { type Static, type TSchema, Type } from '@sinclair/typebox';
import type { Page } from 'playwright';

import type { BrowserSession } from './session.js';
import { formatSnapshot, pageSummary, refLocator, snapshotPage } from './snapshot.js';

/** Options for `browserTools`. */
export interface BrowserToolsOptions {
  /** Timeout for navigations, element actions, and waits. Defaults to 10000. */
  readonly timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 10_000;

const REF = Type.String({ description: 'Element ref from the latest snapshot, e.g. "e12".' });

function textResult(text: string): ToolResult {
  return { content: [{ type: 'text', text }] };
}

function errorResult(error: unknown): ToolResult {
  const message = error instanceof Error ? error.message : String(error);
  // Playwright appends a multi-line call log; the first line carries the cause.
  const firstLine = message.split('\n')[0] ?? message;
  return { content: [{ type: 'text', text: `Error: ${firstLine}` }], isError: true };
}

function defineTool<P extends TSchema>(
  name: string,
  description: string,
  parameters: P,
  run: (params: Static<P>) => Promise<ToolResult>,
): Tool<P> {
  return {
    name,
    description,
    parameters,
    async execute(params) {
      try {
        return await run(params);
      } catch (error) {
        return errorResult(error);
      }
    },
  };
}

function resolveUrl(url: string, baseUrl: string | undefined): string {
  try {
    return new URL(url, baseUrl).toString();
  } catch {
    const against = baseUrl === undefined ? '' : ` against ${baseUrl}`;
    throw new Error(`Cannot resolve URL "${url}"${against}.`);
  }
}

/**
 * Returns `done` followed by the page summary once the document has loaded.
 * A page still loading after `timeoutMs` is reported as-is rather than
 * failing the action that already succeeded.
 */
async function afterAction(page: Page, timeoutMs: number, done: string): Promise<ToolResult> {
  await page.waitForLoadState('domcontentloaded', { timeout: timeoutMs }).catch(() => undefined);
  return textResult(`${done}\n${await pageSummary(page)}`);
}

/**
 * Builds the browser tool set for one session.
 *
 * `evaluate` is included only when the session was launched with
 * `evaluateEnabled`. `finish` records its arguments on `session.finished`.
 */
export function browserTools(session: BrowserSession, options: BrowserToolsOptions = {}): Tool[] {
  const { page } = session;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const after = (done: string) => afterAction(page, timeoutMs, done);

  const tools: Tool[] = [
    defineTool(
      'navigate',
      'Open a URL in the current tab. Relative URLs resolve against the shop base URL.',
      Type.Object({
        url: Type.String({ description: 'Absolute URL, or a path like "/collections/all".' }),
      }),
      async ({ url }) => {
        const target = resolveUrl(url, session.baseUrl);
        await page.goto(target, { timeout: timeoutMs, waitUntil: 'domcontentloaded' });
        return after(`Navigated to ${target}`);
      },
    ),
    defineTool('back', 'Go back to the previous page in history.', Type.Object({}), async () => {
      const response = await page.goBack({ timeout: timeoutMs, waitUntil: 'domcontentloaded' });
      if (response === null) {
        throw new Error('No previous page in history.');
      }
      return after('Went back');
    }),
    defineTool(
      'click',
      'Click an element (link, button, checkbox, menu item) by its ref.',
      Type.Object({ ref: REF }),
      async ({ ref }) => {
        await (await refLocator(page, ref)).click({ timeout: timeoutMs });
        return after(`Clicked ${ref}`);
      },
    ),
    defineTool(
      'type',
      'Replace the text of an input or textarea by its ref. Set submit to press Enter afterwards.',
      Type.Object({
        ref: REF,
        text: Type.String({ description: 'Text to enter; replaces the current value.' }),
        submit: Type.Optional(Type.Boolean({ description: 'Press Enter after typing.' })),
      }),
      async ({ ref, text, submit }) => {
        const locator = await refLocator(page, ref);
        await locator.fill(text, { timeout: timeoutMs });
        if (submit) {
          await locator.press('Enter', { timeout: timeoutMs });
        }
        return after(`Typed into ${ref}${submit ? ' and pressed Enter' : ''}`);
      },
    ),
    defineTool(
      'select',
      'Choose an option in a <select> dropdown by its ref.',
      Type.Object({
        ref: REF,
        value: Type.String({ description: 'Option value or visible label.' }),
      }),
      async ({ ref, value }) => {
        await (await refLocator(page, ref)).selectOption(value, { timeout: timeoutMs });
        return after(`Selected "${value}" in ${ref}`);
      },
    ),
    defineTool(
      'press',
      'Press a keyboard key on the focused element, e.g. "Enter", "Escape", "Tab", "ArrowDown".',
      Type.Object({
        key: Type.String({ description: 'Key name as in Playwright, e.g. "Enter".' }),
      }),
      async ({ key }) => {
        await page.keyboard.press(key);
        return after(`Pressed ${key}`);
      },
    ),
    defineTool(
      'hover',
      'Move the mouse over an element by its ref, e.g. to open a hover menu.',
      Type.Object({ ref: REF }),
      async ({ ref }) => {
        await (await refLocator(page, ref)).hover({ timeout: timeoutMs });
        return after(`Hovered ${ref}`);
      },
    ),
    defineTool(
      'scroll',
      'Scroll the page up or down by most of a screen, or scroll an element into view by its ref.',
      Type.Object({
        direction: Type.Optional(Type.Union([Type.Literal('up'), Type.Literal('down')])),
        ref: Type.Optional(REF),
      }),
      async ({ direction, ref }) => {
        if (ref !== undefined) {
          await (await refLocator(page, ref)).scrollIntoViewIfNeeded({ timeout: timeoutMs });
          return after(`Scrolled ${ref} into view`);
        }
        if (direction === undefined) {
          throw new Error('scroll needs a direction or a ref.');
        }
        const step = Math.round((page.viewportSize()?.height ?? 800) * 0.8);
        await page.evaluate(`window.scrollBy(0, ${direction === 'down' ? step : -step})`);
        return after(`Scrolled ${direction}`);
      },
    ),
    defineTool(
      'wait',
      'Wait for text to appear on the page, or for a fixed number of milliseconds.',
      Type.Object({
        text: Type.Optional(Type.String({ description: 'Wait until this text is visible.' })),
        ms: Type.Optional(Type.Integer({ minimum: 0, description: 'Milliseconds to wait.' })),
      }),
      async ({ text, ms }) => {
        if (text !== undefined) {
          await page.getByText(text).first().waitFor({ state: 'visible', timeout: timeoutMs });
          return after(`"${text}" is visible`);
        }
        if (ms === undefined) {
          throw new Error('wait needs text or ms.');
        }
        await page.waitForTimeout(Math.min(ms, timeoutMs));
        return after(`Waited ${Math.min(ms, timeoutMs)} ms`);
      },
    ),
    defineTool(
      'snapshot',
      'Get the current URL, title, and accessibility tree of the page. Each element line carries a [ref=eN] to use with click, type, select, hover, and scroll. Refs change when the page changes, so take a new snapshot after acting.',
      Type.Object({}),
      async () => textResult(formatSnapshot(await snapshotPage(page))),
    ),
    defineTool(
      'screenshot',
      'Take a PNG screenshot of the visible viewport. Use it for layout and images; use snapshot for text and refs.',
      Type.Object({}),
      async () => {
        const png = await page.screenshot({ type: 'png' });
        return {
          content: [
            { type: 'text', text: `Screenshot of ${page.url()}` },
            { type: 'image', data: png.toString('base64'), mimeType: 'image/png' },
          ],
        };
      },
    ),
    defineTool(
      'finish',
      'End the task. Give the answer when the task asked for information, or set infeasible with a reason when it cannot be done on this site.',
      Type.Object({
        answer: Type.Optional(
          Type.String({ description: 'Final answer, if the task asked for one.' }),
        ),
        infeasible: Type.Optional(
          Type.Boolean({ description: 'True when the task cannot be completed here.' }),
        ),
        reason: Type.Optional(
          Type.String({ description: 'Why it is infeasible, or a brief note.' }),
        ),
      }),
      async ({ answer, infeasible, reason }) => {
        session.finished = {
          infeasible: infeasible ?? false,
          ...(answer === undefined ? {} : { answer }),
          ...(reason === undefined ? {} : { reason }),
        };
        return textResult(`Finished (infeasible=${session.finished.infeasible}).`);
      },
    ),
  ];

  if (session.evaluateEnabled) {
    tools.push(
      defineTool(
        'evaluate',
        'Evaluate a JavaScript expression in the page and return its JSON-serialized value.',
        Type.Object({ expression: Type.String({ description: 'E.g. "document.title".' }) }),
        async ({ expression }) => {
          const value = await page.evaluate<unknown>(expression);
          return textResult(JSON.stringify(value) ?? 'undefined');
        },
      ),
    );
  }

  return tools;
}
