import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ReportFormatError, listReports, parseReport, readReport } from './catalog.js';

const HEAD =
  '<title>Plan &amp; review</title>\n<meta name="description" content="Why &quot;A&quot; wins.">\n';

describe('parseReport', () => {
  it('splits the head block from the body and decodes entities', () => {
    const page = parseReport('r.html', `${HEAD}<style>p{}</style>\n<main>hi</main>\n`);
    expect(page).toEqual({
      title: 'Plan & review',
      description: 'Why "A" wins.',
      body: '<style>p{}</style>\n<main>hi</main>\n',
    });
  });

  it('accepts attributes in any order and other meta tags in the head block', () => {
    const html =
      "<title>T</title><meta charset=\"utf-8\"><meta content='D' name='description'><p>x</p>";
    expect(parseReport('r.html', html)).toMatchObject({
      title: 'T',
      description: 'D',
      body: '<p>x</p>',
    });
  });

  it('reads the title only from the head block, not from inline SVG', () => {
    const html = '<meta name="description" content="D">\n<svg><title>Chart</title></svg>';
    expect(() => parseReport('r.html', html)).toThrow(
      /r\.html: must start with a non-empty <title>/,
    );
  });

  it('rejects a report without a description', () => {
    expect(() => parseReport('r.html', '<title>T</title><main></main>')).toThrow(ReportFormatError);
  });

  it('rejects a full document', () => {
    expect(() => parseReport('r.html', `<!doctype html><html><head>${HEAD}</head></html>`)).toThrow(
      /is a full document/,
    );
  });
});

describe('listReports and readReport', () => {
  let dir: string;

  beforeEach(async () => {
    dir = await fs.mkdtemp(path.join(os.tmpdir(), 'reports-catalog-'));
  });
  afterEach(async () => {
    await fs.rm(dir, { recursive: true, force: true });
  });

  const write = (file: string, title: string): Promise<void> =>
    fs.writeFile(
      path.join(dir, file),
      `<title>${title}</title><meta name="description" content="d">`,
    );

  it('lists reports newest first and skips other file names', async () => {
    await write('2026-10-01-old.html', 'Old');
    await write('2026-11-04-b.html', 'B');
    await write('2026-11-04-a.html', 'A');
    await write('notes.html', 'Not a report');
    await fs.writeFile(path.join(dir, 'README.md'), '# readme');

    const reports = await listReports(dir);

    expect(reports.map((r) => [r.file, r.date, r.title])).toEqual([
      ['2026-11-04-a.html', '2026-11-04', 'A'],
      ['2026-11-04-b.html', '2026-11-04', 'B'],
      ['2026-10-01-old.html', '2026-10-01', 'Old'],
    ]);
  });

  it('returns undefined for a missing file or a name that is not a report name', async () => {
    await write('notes.html', 'Not a report');
    expect(await readReport(dir, '2026-11-04-missing.html')).toBeUndefined();
    expect(await readReport(dir, 'notes.html')).toBeUndefined();
    expect(await readReport(dir, '../2026-11-04-x.html')).toBeUndefined();
  });

  it('names the file that breaks the page contract', async () => {
    await fs.writeFile(path.join(dir, '2026-11-04-bad.html'), '<main>no head</main>');
    await expect(listReports(dir)).rejects.toThrow(/^2026-11-04-bad\.html: /);
  });
});
