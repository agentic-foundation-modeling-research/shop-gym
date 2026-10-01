import { afterEach, describe, expect, it, vi } from 'vitest';
import { z } from 'zod';

import { CliError } from './context.js';
import { describe as describeError, main } from './main.js';

describe('describe', () => {
  it('renders zod issues, CliError and errno errors on one line', () => {
    const zod = z.object({ name: z.string() }).safeParse({ name: 1 });
    expect(zod.success).toBe(false);
    if (!zod.success) {
      expect(describeError(zod.error)).toMatch(/^name: /);
    }
    expect(describeError(new CliError('bad flag'))).toBe('bad flag');
    const enoent = Object.assign(new Error('ENOENT: no such file'), { code: 'ENOENT' });
    expect(describeError(enoent)).toBe('ENOENT: no such file');
    expect(describeError('plain')).toBe('plain');
  });

  it('keeps the stack for unexpected errors', () => {
    expect(describeError(new TypeError('boom'))).toContain('\n    at ');
  });
});

describe('main', () => {
  afterEach(() => vi.restoreAllMocks());

  it('prints usage for --help and rejects unknown commands', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => undefined);
    const stderr = vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
    expect(await main(['--help'])).toBe(0);
    expect(await main(['frobnicate'])).toBe(1);
    expect(String(stderr.mock.calls[0]?.[0])).toContain('unknown command "frobnicate"');
  });

  it('reports a command failure as one line', async () => {
    const stderr = vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
    expect(await main(['trace'])).toBe(1);
    expect(stderr.mock.calls.map((c) => String(c[0]))).toEqual([
      'shopgym trace: missing <iter_dir>\n',
    ]);
  });
});
