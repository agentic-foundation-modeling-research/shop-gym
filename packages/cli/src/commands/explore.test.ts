import { describe, expect, it } from 'vitest';

import { CliError, DEFAULT_MODEL } from '../context.js';
import { parseExploreArgs } from './explore.js';

describe('parseExploreArgs', () => {
  it('parses the url and every option', () => {
    expect(
      parseExploreArgs([
        'https://shop.example',
        '--out',
        'o',
        '--model',
        'p/m',
        '--max-iters',
        '3',
        '--timeout',
        '1000',
        '--from',
        'merge',
        '--force-resume',
      ]),
    ).toEqual({
      help: false,
      url: 'https://shop.example',
      outDir: 'o',
      model: 'p/m',
      maxIters: 3,
      timeoutMs: 1000,
      from: 'merge',
      forceResume: true,
    });
  });

  it('defaults the model and omits unset options', () => {
    expect(parseExploreArgs(['https://shop.example'])).toEqual({
      help: false,
      url: 'https://shop.example',
      model: DEFAULT_MODEL,
      forceResume: false,
    });
  });

  it('rejects an unknown --from step with the allowed list', () => {
    expect(() => parseExploreArgs(['u', '--from', 'build'])).toThrow(
      '--from must be one of prefetch, explore, merge, synthesize, got "build"',
    );
  });

  it('rejects a missing url, extra positionals and unknown options as CliError', () => {
    expect(() => parseExploreArgs([])).toThrow(CliError);
    expect(() => parseExploreArgs(['a', 'b'])).toThrow('unexpected argument "b"');
    expect(() => parseExploreArgs(['a', '--bogus'])).toThrow(CliError);
    expect(() => parseExploreArgs(['a', '--max-iters', 'x'])).toThrow(
      '--max-iters must be a positive integer',
    );
  });

  it('returns help without validating positionals', () => {
    expect(parseExploreArgs(['--help']).help).toBe(true);
  });
});
