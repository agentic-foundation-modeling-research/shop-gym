import * as fs from 'node:fs/promises';

import { describe, expect, it } from 'vitest';

import { REPORT_FILE_RE, listReports } from './catalog.js';
import { PAGES_DIR } from './server.js';

describe('committed reports', () => {
  it('use report file names only', async () => {
    const files = (await fs.readdir(PAGES_DIR)).filter((file) => !file.startsWith('.'));
    expect(files.filter((file) => !REPORT_FILE_RE.test(file))).toEqual([]);
  });

  it('follow the report page contract', async () => {
    const reports = await listReports(PAGES_DIR);
    expect(reports.length).toBeGreaterThan(0);
  });
});
