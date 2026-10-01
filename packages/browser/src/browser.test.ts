import * as http from 'node:http';
import type { AddressInfo } from 'node:net';

import type { Tool, ToolContext, ToolResult } from '@shop-gym/agent';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { probe } from './probe.js';
import { BrowserSession } from './session.js';
import { browserTools } from './tools.js';

const HOME = `<!doctype html><html><head><title>Fixture Shop</title></head><body>
<h1>Fixture Shop</h1>
<nav><ul>
  <li><a href="/second">Second page</a></li>
  <li><a href="/">Home</a></li>
  <li><a href="#top">Top</a></li>
</ul></nav>
<form action="/search" method="get"><input name="q" aria-label="Search"><button type="submit">Search</button></form>
<label>Size <select onchange="document.getElementById('out').textContent='size:'+this.value">
  <option value="s">Small</option><option value="m">Medium</option>
</select></label>
<button onclick="document.getElementById('out').textContent='toggled'">Toggle</button>
<a href="#h" onmouseover="document.getElementById('out').textContent='hovered'">Hover me</a>
<p id="out"></p>
<div style="height:3000px"></div>
<p>Bottom text</p>
<script>
  document.addEventListener('keydown', (e) => { document.getElementById('out').textContent = 'key:' + e.key; });
  setTimeout(() => { const p = document.createElement('p'); p.textContent = 'Late text'; document.body.appendChild(p); }, 300);
</script>
</body></html>`;

const SECOND =
  '<!doctype html><html><head><title>Second</title></head><body><h1>Second heading</h1></body></html>';

interface SeenRequest {
  readonly url: string;
  readonly episode: string | undefined;
}

const seen: SeenRequest[] = [];
let baseUrl = '';
let server: http.Server;
let session: BrowserSession;
let tools: Tool[];

const CTX: ToolContext = {
  cwd: process.cwd(),
  callId: 'call-1',
  signal: new AbortController().signal,
};

function call(name: string, params: unknown = {}): Promise<ToolResult> {
  const tool = tools.find((t) => t.name === name);
  if (tool === undefined) {
    throw new Error(`no tool ${name}`);
  }
  return tool.execute(params, CTX);
}

function textOf(result: ToolResult): string {
  return result.content.flatMap((c) => (c.type === 'text' ? [c.text] : [])).join('\n');
}

/** The ref on the first snapshot line matching `pattern`. */
function refOf(snapshot: string, pattern: RegExp): string {
  const line = snapshot.split('\n').find((l) => pattern.test(l));
  const ref = line?.match(/\[ref=((?:f\d+)?e\d+)\]/)?.[1];
  if (ref === undefined) {
    throw new Error(`no ref for ${pattern} in snapshot`);
  }
  return ref;
}

async function snapshotText(): Promise<string> {
  return textOf(await call('snapshot'));
}

beforeAll(async () => {
  server = http.createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    const episode = req.headers['x-shopgym-episode'];
    seen.push({ url: url.pathname, episode: Array.isArray(episode) ? episode[0] : episode });
    res.setHeader('content-type', 'text/html');
    if (url.pathname === '/second') {
      res.end(SECOND);
    } else if (url.pathname === '/search') {
      res.end(`<title>Search results</title><p>Results for ${url.searchParams.get('q')}</p>`);
    } else {
      res.end(HOME);
    }
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  session = await BrowserSession.launch({ episodeId: 'ep-42', baseUrl });
  tools = browserTools(session, { timeoutMs: 3000 });
}, 60_000);

afterAll(async () => {
  await session.close();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

beforeEach(async () => {
  seen.length = 0;
  const result = await call('navigate', { url: '/' });
  expect(result.isError).toBeUndefined();
});

describe('BrowserSession', () => {
  it('sends the episode header on every request', () => {
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.every((r) => r.episode === 'ep-42')).toBe(true);
  });

  it('exports storage state', async () => {
    const state = await session.storageState();
    expect(Array.isArray(state.cookies)).toBe(true);
  });

  it('defaults to a 1280x800 viewport', () => {
    expect(session.page.viewportSize()).toEqual({ width: 1280, height: 800 });
  });
});

describe('snapshot', () => {
  it('reports URL, title, and ref-tagged elements', async () => {
    const text = await snapshotText();
    expect(text).toContain(`URL: ${baseUrl}/`);
    expect(text).toContain('Title: Fixture Shop');
    expect(text).toMatch(/link "Second page" \[ref=(?:f\d+)?e\d+\]/);
    expect(text).toMatch(/textbox "Search" \[ref=(?:f\d+)?e\d+\]/);
  });
});

describe('element tools', () => {
  it('click follows a link by ref and reports the new page', async () => {
    const ref = refOf(await snapshotText(), /link "Second page"/);
    const result = await call('click', { ref });
    expect(result.isError).toBeUndefined();
    expect(textOf(result)).toContain(`URL: ${baseUrl}/second`);
    expect(textOf(result)).toContain('Title: Second');
  });

  it('back returns to the previous page', async () => {
    await call('click', { ref: refOf(await snapshotText(), /link "Second page"/) });
    const result = await call('back');
    expect(textOf(result)).toContain('Title: Fixture Shop');
  });

  it('type with submit fills the input and submits the form', async () => {
    const ref = refOf(await snapshotText(), /textbox "Search"/);
    const result = await call('type', { ref, text: 'hello', submit: true });
    expect(textOf(result)).toContain(`URL: ${baseUrl}/search?q=hello`);
  });

  it('select picks an option by value', async () => {
    const ref = refOf(await snapshotText(), /combobox "Size"/);
    await call('select', { ref, value: 'm' });
    expect((await probe(session, '#out')).texts).toEqual(['size:m']);
  });

  it('press sends a key to the page', async () => {
    await call('press', { key: 'x' });
    expect((await probe(session, '#out')).texts).toEqual(['key:x']);
  });

  it('hover triggers mouseover on the element', async () => {
    const ref = refOf(await snapshotText(), /link "Hover me"/);
    await call('hover', { ref });
    expect((await probe(session, '#out')).texts).toEqual(['hovered']);
  });

  it('scroll moves the viewport and brings refs into view', async () => {
    await call('scroll', { direction: 'down' });
    expect(await session.page.evaluate<number>('window.scrollY')).toBeGreaterThan(0);
    const ref = refOf(await snapshotText(), /paragraph .*Bottom text/);
    const result = await call('scroll', { ref });
    expect(result.isError).toBeUndefined();
    expect(await session.page.evaluate<number>('window.scrollY')).toBeGreaterThan(1000);
  });

  it('wait resolves once the text is visible', async () => {
    const result = await call('wait', { text: 'Late text' });
    expect(result.isError).toBeUndefined();
    expect((await probe(session, 'text=Late text')).count).toBe(1);
  });

  it('rejects a ref that is not in the latest snapshot', async () => {
    const result = await call('click', { ref: 'e999' });
    expect(result.isError).toBe(true);
    expect(textOf(result)).toContain('e999 is not in the latest snapshot');
  });

  it('reports an unresolvable URL as an error', async () => {
    const result = await call('navigate', { url: 'http://[bad' });
    expect(result.isError).toBe(true);
    expect(textOf(result)).toMatch(/^Error: Cannot resolve URL/);
  });
});

describe('screenshot', () => {
  it('returns a PNG image block', async () => {
    const result = await call('screenshot');
    const image = result.content.find((c) => c.type === 'image');
    expect(image?.type).toBe('image');
    if (image?.type !== 'image') {
      return;
    }
    expect(image.mimeType).toBe('image/png');
    expect(Buffer.from(image.data, 'base64').subarray(0, 4)).toEqual(
      Buffer.from([0x89, 0x50, 0x4e, 0x47]),
    );
  });
});

describe('finish', () => {
  it('records the answer on the session', async () => {
    expect(session.finished).toBeUndefined();
    await call('finish', { answer: '42' });
    expect(session.finished).toEqual({ answer: '42', infeasible: false });
    await call('finish', { infeasible: true, reason: 'no such product' });
    expect(session.finished).toEqual({ infeasible: true, reason: 'no such product' });
  });
});

describe('probe', () => {
  it('counts matches and reads their text', async () => {
    const result = await probe(session, 'nav li');
    expect(result.count).toBe(3);
    expect(result.texts).toEqual(['Second page', 'Home', 'Top']);
    expect(result.visible).toBe(true);
  });

  it('reports nothing matched', async () => {
    expect(await probe(session, '#missing')).toEqual({ count: 0, texts: [], visible: false });
  });
});

describe('evaluate', () => {
  it('is absent unless the session enables it', () => {
    expect(tools.map((t) => t.name)).not.toContain('evaluate');
  });

  it('runs an expression when enabled', async () => {
    const enabled = await BrowserSession.launch({
      episodeId: 'ep-eval',
      baseUrl,
      evaluateEnabled: true,
    });
    try {
      const evaluate = browserTools(enabled).find((t) => t.name === 'evaluate');
      expect(evaluate).toBeDefined();
      await enabled.page.goto(baseUrl);
      const result = await evaluate?.execute({ expression: 'document.title' }, CTX);
      expect(result === undefined ? '' : textOf(result)).toBe('"Fixture Shop"');
    } finally {
      await enabled.close();
    }
  }, 30_000);
});
