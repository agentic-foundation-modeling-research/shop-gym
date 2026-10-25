import { describe, expect, it } from 'vitest';

import { CliError } from '../context.js';
import { formatTable, parseHostArgs } from './host.js';

describe('parseHostArgs', () => {
  it('parses start with an optional port and --force', () => {
    expect(parseHostArgs(['start', 'shop'])).toEqual({
      help: false,
      action: 'start',
      shop: 'shop',
      force: false,
    });
    expect(parseHostArgs(['start', 'shop', '4100', '--force'])).toEqual({
      help: false,
      action: 'start',
      shop: 'shop',
      port: 4100,
      force: true,
    });
  });

  it('parses stop, stop all and restart', () => {
    expect(parseHostArgs(['stop', 'all'])).toEqual({ help: false, action: 'stop', shop: 'all' });
    expect(parseHostArgs(['restart', 's'])).toEqual({ help: false, action: 'restart', shop: 's' });
  });

  it('parses list with -a / --all', () => {
    expect(parseHostArgs(['list'])).toEqual({ help: false, action: 'list', all: false });
    expect(parseHostArgs(['list', '-a'])).toEqual({ help: false, action: 'list', all: true });
    expect(parseHostArgs(['list', '--all'])).toEqual({ help: false, action: 'list', all: true });
  });

  it('rejects unknown actions, missing shops, bad ports and stray arguments', () => {
    expect(() => parseHostArgs([])).toThrow('missing <action>');
    expect(() => parseHostArgs(['logs', 's'])).toThrow(
      '<action> must be one of start, stop, restart, list, got "logs"',
    );
    expect(() => parseHostArgs(['start'])).toThrow('missing <shop> for start');
    expect(() => parseHostArgs(['start', 's', 'abc'])).toThrow('[port] must be a positive integer');
    expect(() => parseHostArgs(['stop', 's', '1'])).toThrow('unexpected argument "1"');
    expect(() => parseHostArgs(['list', 's'])).toThrow(CliError);
  });
});

describe('formatTable', () => {
  it('prints a hint when nothing is tracked', () => {
    expect(formatTable([], false)).toContain('try: shopgym host list -a');
    expect(formatTable([], true)).toContain('no shops running or published');
  });

  it('aligns columns', () => {
    const text = formatTable(
      [
        {
          name: 'a',
          status: 'running',
          storefrontUrl: 'http://127.0.0.1:1',
          backendUrl: 'http://127.0.0.1:2',
          pids: '10/11',
        },
        { name: 'longer', status: 'available', storefrontUrl: '-', backendUrl: '-', pids: '-' },
      ],
      false,
    );
    expect(text.split('\n')[0]).toMatch(/^SHOP {4}STATUS {5}STOREFRONT {10}BACKEND {13}PIDS$/);
    expect(text).toContain('longer  available  -');
  });
});
