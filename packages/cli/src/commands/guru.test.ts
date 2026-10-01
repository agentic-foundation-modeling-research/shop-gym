import type { GuruConfig } from '@shop-gym/shop-guru';
import { describe, expect, it } from 'vitest';

import { CliError } from '../context.js';
import { applyOverrides, parseGuruArgs } from './guru.js';

describe('parseGuruArgs', () => {
  it('parses the stage, config and overrides', () => {
    expect(
      parseGuruArgs([
        'eval',
        '--config',
        'c.json',
        '--shop',
        's',
        '--skills',
        'exact, browse,',
        '--model',
        'p/m',
        '--judge-model',
        'p/j',
        '--concurrency',
        '2',
        '--no-headless',
      ]),
    ).toEqual({
      help: false,
      stage: 'eval',
      configPath: 'c.json',
      skills: ['exact', 'browse'],
      overrides: { shop: 's', model: 'p/m', judgeModel: 'p/j', concurrency: 2, headless: false },
    });
  });

  it('leaves overrides empty when nothing is passed', () => {
    expect(parseGuruArgs(['build', '--config', 'c'])).toEqual({
      help: false,
      stage: 'build',
      configPath: 'c',
      overrides: {},
    });
    expect(parseGuruArgs(['solve', '--config', 'c', '--headless']).overrides).toEqual({
      headless: true,
    });
  });

  it('rejects unknown stages, a missing config and conflicting headless flags', () => {
    expect(() => parseGuruArgs(['grade', '--config', 'c'])).toThrow(
      '<stage> must be one of build, explore, solve, eval, got "grade"',
    );
    expect(() => parseGuruArgs(['build'])).toThrow('--config is required');
    expect(() => parseGuruArgs(['build', '--config', 'c', '--headless', '--no-headless'])).toThrow(
      CliError,
    );
  });
});

describe('applyOverrides', () => {
  const config = {
    shop: 'a',
    model: { provider: 'x', id: 'y' },
    concurrency: 1,
    headless: true,
  } as GuruConfig;

  it('parses model refs and keeps untouched fields', () => {
    expect(
      applyOverrides(config, { model: 'openai/gpt', judgeModel: 'p/j', headless: false }),
    ).toEqual({
      shop: 'a',
      model: { provider: 'openai', id: 'gpt' },
      judgeModel: { provider: 'p', id: 'j' },
      concurrency: 1,
      headless: false,
    });
  });

  it('rejects a model without a provider', () => {
    expect(() => applyOverrides(config, { model: 'gpt' })).toThrow('provider/model-id');
  });
});
