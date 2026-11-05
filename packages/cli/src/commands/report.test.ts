import { describe, expect, it } from 'vitest';

import { parseReportArgs } from './report.js';

describe('parseReportArgs', () => {
  it('defaults to the local interface and the default port', () => {
    expect(parseReportArgs([])).toEqual({ help: false, port: 4100, host: '127.0.0.1' });
  });

  it('parses --port and --host', () => {
    expect(parseReportArgs(['--port', '8100', '--host', '0.0.0.0'])).toEqual({
      help: false,
      port: 8100,
      host: '0.0.0.0',
    });
  });

  it('rejects a bad port and extra arguments', () => {
    expect(() => parseReportArgs(['--port', 'x'])).toThrow(/--port must be a positive integer/);
    expect(() => parseReportArgs(['pages'])).toThrow(/unexpected argument "pages"/);
  });
});
