# @shop-gym/browser

The browser layer: one Playwright session per episode, the tools an
`AgentRuntime` uses to drive it, and a probe for graders.

- `session.ts` - `BrowserSession.launch({episodeId, baseUrl?, headless?,
  viewport?, video?, trace?, evaluateEnabled?})` starts chromium with one
  context whose every request carries `x-shopgym-episode: <episodeId>`, so
  the sandbox backend can keep episode state apart. Exposes `page`,
  `context`, `storageState()`, `finished`, and `close()` (writes the trace
  zip and flushes video when enabled).
- `snapshot.ts` - `snapshotPage(page)` returns the URL, title, and
  Playwright's AI aria snapshot, a YAML tree where every element carries
  `[ref=eN]`. `refLocator(page, ref)` resolves a ref through Playwright's
  `aria-ref=` selector and fails fast on a stale or malformed ref.
- `tools.ts` - `browserTools(session, {timeoutMs?})` returns `Tool[]`:
  `navigate`, `back`, `click`, `type`, `select`, `press`, `hover`, `scroll`,
  `wait`, `snapshot`, `screenshot` (PNG image block), `finish` (records
  `{answer, infeasible, reason}` on `session.finished`), and `evaluate` only
  when the session has `evaluateEnabled`. Action tools answer with the new
  URL and title; failures return `isError: true` instead of throwing.
- `probe.ts` - `probe(session, selector)` reports `{count, texts, visible}`
  for a Playwright selector on the current page.

```bash
pnpm --filter @shop-gym/browser exec playwright install chromium   # once per machine
pnpm --filter @shop-gym/browser test                               # headless, local fixture server
```
