import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { type ReportServer, createReportServer } from './server.js';

const REPORT = `<title>Dataset survey</title>
<meta name="description" content="What each dataset holds.">
<style>.x { color: var(--ink); }</style>
<main class="shell"><p>Body text</p></main>
`;

const SECRET = 'file outside the served directories';

describe('createReportServer', () => {
  let root: string;
  let pagesDir: string;
  let server: ReportServer;

  beforeEach(async () => {
    root = await fs.mkdtemp(path.join(os.tmpdir(), 'reports-server-'));
    pagesDir = path.join(root, 'pages');
    const assetsDir = path.join(root, 'assets');
    await fs.mkdir(pagesDir);
    await fs.mkdir(assetsDir);
    await fs.writeFile(path.join(pagesDir, '2026-11-04-dataset-survey.html'), REPORT);
    await fs.writeFile(path.join(assetsDir, 'report.css'), 'body {}');
    await fs.writeFile(path.join(root, 'secret.txt'), SECRET);
    server = createReportServer({ pagesDir, assetsDir, port: 0 });
    await server.listen();
  });

  afterEach(async () => {
    await server.close();
    await fs.rm(root, { recursive: true, force: true });
  });

  const get = (pathname: string, init?: RequestInit): Promise<Response> =>
    fetch(`${server.url}${pathname}`, init);

  it('lists every report on the index page', async () => {
    const res = await get('/');
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('text/html; charset=utf-8');
    const html = await res.text();
    expect(html).toContain('href="/2026-11-04-dataset-survey.html"');
    expect(html).toContain('Dataset survey');
    expect(html).toContain('What each dataset holds.');
    expect(html).toContain('1 report, newest first');
  });

  it('serves a report inside the site shell', async () => {
    const res = await get('/2026-11-04-dataset-survey.html');
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html.startsWith('<!doctype html>')).toBe(true);
    expect(html).toContain('<title>Dataset survey</title>');
    expect(html).toContain('<meta name="description" content="What each dataset holds.">');
    expect(html).toContain('<link rel="stylesheet" href="/assets/report.css">');
    expect(html).toContain('<time class="site-crumb" datetime="2026-11-04">');
    expect(html).toContain('<main class="shell"><p>Body text</p></main>');
    expect(html.match(/<title>/g)).toHaveLength(1);
  });

  it('reads files on each request', async () => {
    await fs.writeFile(
      path.join(pagesDir, '2026-11-04-dataset-survey.html'),
      REPORT.replace('Body text', 'Edited text'),
    );
    expect(await (await get('/2026-11-04-dataset-survey.html')).text()).toContain('Edited text');
    await fs.writeFile(path.join(pagesDir, '2026-11-05-new.html'), REPORT);
    expect(await (await get('/')).text()).toContain('2 reports, newest first');
  });

  it('serves shared assets with their content type', async () => {
    const res = await get('/assets/report.css');
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('text/css; charset=utf-8');
    expect(await res.text()).toBe('body {}');
  });

  it.each([
    '/2026-11-04-missing.html',
    '/assets/missing.css',
    '/assets/notes.txt',
    '/secret.txt',
    '/assets/..%2Fsecret.txt',
    '/assets/%2e%2e/secret.txt',
    '/pages/2026-11-04-dataset-survey.html',
  ])('answers 404 for %s', async (pathname) => {
    const res = await get(pathname);
    expect(res.status).toBe(404);
    expect(await res.text()).not.toContain(SECRET);
  });

  it('answers 405 for methods other than GET', async () => {
    const res = await get('/', { method: 'POST' });
    expect(res.status).toBe(405);
    expect(res.headers.get('allow')).toBe('GET');
  });

  it('answers 500 with the problem when a report breaks the page contract', async () => {
    await fs.writeFile(path.join(pagesDir, '2026-11-04-dataset-survey.html'), '<main></main>');
    const res = await get('/2026-11-04-dataset-survey.html');
    expect(res.status).toBe(500);
    expect(await res.text()).toMatch(/^2026-11-04-dataset-survey\.html: must start with/);
  });
});
