import { describe, expect, it } from 'vitest';

import { CliError, DEFAULT_MODEL } from '../context.js';
import { parseGenArgs } from './gen.js';

describe('parseGenArgs', () => {
  it('collects manual dirs and maps every option onto the gen config', () => {
    const { config } = parseGenArgs([
      'm1',
      'm2',
      '--name',
      'shop',
      '--out',
      'o',
      '--gen-backend',
      '--from',
      'build',
      '--model',
      'p/m',
      '--build-model',
      'p/b',
      '--image-backend',
      'openai',
      '--max-iters',
      '7',
      '--collections',
      '2',
      '--products-per-collection',
      '3',
      '--images-per-product',
      '0',
      '--concurrency',
      '4',
      '--force-resume',
    ]);
    expect(config).toEqual({
      name: 'shop',
      manualDirs: ['m1', 'm2'],
      outDir: 'o',
      genBackend: true,
      from: 'build',
      model: 'p/m',
      buildModel: 'p/b',
      imageBackend: 'openai',
      maxIters: 7,
      catalog: { collections: 2, productsPerCollection: 3, imagesPerProduct: 0 },
      concurrency: 4,
      forceResume: true,
    });
  });

  it('applies the default model and leaves the catalog to zod defaults', () => {
    expect(parseGenArgs(['m', '--name', 's']).config).toEqual({
      name: 's',
      manualDirs: ['m'],
      model: DEFAULT_MODEL,
      genBackend: false,
      forceResume: false,
      catalog: {},
    });
  });

  it('validates --from against the gen steps', () => {
    expect(() => parseGenArgs(['m', '--name', 's', '--from', 'synthesize'])).toThrow(
      '--from must be one of manual_merge, data_synth, data_validation, build, final_eval, publish, got "synthesize"',
    );
  });

  it('requires --name and at least one manual dir', () => {
    expect(() => parseGenArgs(['m'])).toThrow('--name is required');
    expect(() => parseGenArgs(['--name', 's'])).toThrow('missing <manual_dir>');
  });

  it('rejects bad enum and integer values as CliError', () => {
    expect(() => parseGenArgs(['m', '--name', 's', '--image-backend', 'dalle'])).toThrow(
      '--image-backend must be one of placeholder, openai',
    );
    expect(() => parseGenArgs(['m', '--name', 's', '--collections', '0'])).toThrow(CliError);
    expect(() => parseGenArgs(['m', '--name', 's', '--images-per-product', '-1'])).toThrow(
      CliError,
    );
  });
});
