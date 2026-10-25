# Browser Session and Tools

## Overview

`@shop-gym/browser` is the one place ShopGym drives a web browser. It gives
every episode its own Playwright context tagged with an episode id, exposes
that context to an `AgentRuntime` as a small set of `Tool`s built on aria
snapshots with stable element refs, and offers graders a read-only probe.
It replaces `pi-playwright`, Playwright MCP, and the BrowserGym observation
code used by v1.0.

## Terminology

- **BrowserSession** - a chromium browser, one context, and one page bound
  to an episode id.
- **Episode header** - `x-shopgym-episode: <id>`, sent on every request so
  the sandbox backend keeps per-episode state apart (redesign §5.6.4).
- **Aria snapshot** - Playwright's YAML rendering of the accessibility tree.
  In AI mode every element line carries `[ref=eN]`.
- **Ref** - the `eN` token for one element in the latest snapshot; resolved
  through Playwright's `aria-ref=eN` selector engine.
- **Probe** - a Playwright selector evaluated on the current page without
  waiting, returning counts and texts.

## Current Status

Implemented in `packages/browser` (milestone M3 of the v1.1 redesign):

- `BrowserSession.launch`, `storageState`, `close`, `finished`.
- `snapshotPage`, `formatSnapshot`, `pageSummary`, `refLocator`.
- `browserTools` with 13 tools (12 plus the gated `evaluate`).
- `probe`.
- A vitest suite against a local `node:http` fixture, headless chromium.

Nothing consumes the package yet; harness (M2), arena explore (M8) and guru
solve / validate (M9) are the planned callers.

## Desired Status

Unchanged from the current status. Future work lives in the callers: the
solver prompt that explains refs, trajectory screenshots, and the backend
that honours the episode header.

## Proposal

### Session

```ts
BrowserSession.launch({
  episodeId: string; baseUrl?: string; headless?: boolean;        // headless defaults to true
  viewport?: {width, height};                                     // defaults to 1280x800
  video?: {dir: string}; trace?: {path: string};
  evaluateEnabled?: boolean;                                      // defaults to false
}): Promise<BrowserSession>
session.page; session.context; session.storageState(); session.close()
session.finished: {answer?, infeasible, reason?} | undefined
```

The context is created with `extraHTTPHeaders: {'x-shopgym-episode': id}`.
`close()` writes the trace zip, closes the context (which flushes video),
then the browser.

### Snapshot and refs

`snapshotPage(page)` calls `page.ariaSnapshot({mode: 'ai'})`, the same
native mechanism Playwright MCP uses: no DOM instrumentation, no `bid`
attributes. Refs are stable for elements that did not change between
snapshots. `refLocator(page, ref)` validates the shape (`e12`, or `f3e12` once the
page has navigated into a re-created frame), checks
`page.locator('aria-ref=' + ref).count() > 0`, and throws a message telling
the model to take a new snapshot; actions never wait out a timeout on a
stale ref.

### Tools

`browserTools(session, {timeoutMs?})` (default 10 s per action) returns:

| Tool | Parameters | Effect |
| --- | --- | --- |
| `navigate` | `url` | `goto` (relative URLs resolve against `baseUrl`) |
| `back` | - | `goBack`; error when history is empty |
| `click` | `ref` | click |
| `type` | `ref`, `text`, `submit?` | `fill`, then Enter when `submit` |
| `select` | `ref`, `value` | `selectOption` by value or label |
| `press` | `key` | keyboard press on the focused element |
| `hover` | `ref` | hover |
| `scroll` | `direction?` / `ref?` | wheel by 80% of the viewport, or scroll the ref into view |
| `wait` | `text?` / `ms?` | wait for visible text, or sleep (capped at `timeoutMs`) |
| `snapshot` | - | URL, title, and the ref-tagged aria tree |
| `screenshot` | - | one text line plus a PNG image content block |
| `evaluate` | `expression` | page-side JS, JSON result; only when `evaluateEnabled` |
| `finish` | `answer?`, `infeasible?`, `reason?` | sets `session.finished` |

Rules:

- Action tools wait for `domcontentloaded` (best effort, bounded by
  `timeoutMs`) and reply with what happened plus `URL:` and `Title:`
  lines. `snapshot` is the only tool that returns refs.
- `execute` never throws. Playwright errors, stale refs, and bad URLs come
  back as `{isError: true}` with the first line of the message.
- `evaluate` is gated on the session, not on the tools call, so a solver
  session can never be handed the tool by a careless caller.
- `ToolContext.signal` is not wired into Playwright actions; the runtime
  closes the session on abort instead.

### Probe

`probe(session, selector)` returns `{count, texts, visible}`: `count` of
matches, `innerText` of each, and whether the first match is visible. It
never waits. Graders use it after the agent finished; task validation uses
it to confirm that referenced elements exist.

## Alternative

Generating refs ourselves by walking a default aria snapshot and assigning
ids to interactive roles was the fallback if the installed Playwright had
no native refs. Playwright 1.63 ships `mode: 'ai'` and the `aria-ref`
engine, so the fallback was not built: it would duplicate the engine's
element bookkeeping and drift from it.

## Execution Table

| # | Item | Status |
| - | ---- | ------ |
| 1 | `BrowserSession` with episode header, viewport, video, trace | done |
| 2 | Aria snapshot with native refs and `refLocator` | done |
| 3 | `browserTools` including gated `evaluate` and `finish` | done |
| 4 | `probe` | done |
| 5 | Fixture-server test suite, headless chromium | done |
| 6 | Wire into harness / arena explore / guru | M8, M9 |

## Appendix

Playwright surface used: `chromium.launch`, `Browser.newContext`
(`extraHTTPHeaders`, `viewport`, `recordVideo`), `BrowserContext.tracing`,
`storageState`, `Page.ariaSnapshot({mode: 'ai'})`, the `aria-ref=` selector
engine, `Locator.click` / `fill` / `press` / `selectOption` / `hover` /
`scrollIntoViewIfNeeded` / `count` / `allInnerTexts` / `isVisible`,
`Page.goto` / `goBack` / `screenshot` / `evaluate` / `waitForLoadState`,
`Keyboard.press`, `Mouse.wheel`.

Chromium is installed once per machine with
`pnpm --filter @shop-gym/browser exec playwright install chromium`.
