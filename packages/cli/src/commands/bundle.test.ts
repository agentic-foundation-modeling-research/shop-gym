import { describe, expect, it } from 'vitest';

import { CliError, DEFAULT_MODEL } from '../context.js';
import { USAGE, parseBundleArgs } from './bundle.js';

const REQUIRED = [
  'amazon_reviews_2023',
  'outputs/sources/amazon_reviews_2023/raw',
  '--out',
  'outputs/bundles/tiny',
  '--category',
  'Video_Games',
  '--cutoff',
  '2022-07-16',
  '--products',
  '10000',
  '--users',
  '200',
  '--seed',
  '7',
];

describe('parseBundleArgs', () => {
  it('maps the positionals and every option onto the bundle options', () => {
    const args = parseBundleArgs([
      ...REQUIRED,
      '--min-events-before',
      '3',
      '--reviews-per-product',
      '50',
      '--model',
      'p/m',
      '--concurrency',
      '3',
      '--images-per-product',
      '3',
      '--from',
      'complete',
    ]);
    expect(args).toEqual({
      help: false,
      options: {
        adapter: 'amazon_reviews_2023',
        sourceDir: 'outputs/sources/amazon_reviews_2023/raw',
        outDir: 'outputs/bundles/tiny',
        category: 'Video_Games',
        cutoff: '2022-07-16',
        products: 10000,
        users: 200,
        seed: '7',
        minEventsBefore: 3,
        reviewsPerProduct: 50,
        model: 'p/m',
        concurrency: 3,
        imagesPerProduct: 3,
        from: 'complete',
      },
    });
  });

  it('applies the default model and leaves the other options to the defaults', () => {
    const args = parseBundleArgs(REQUIRED);
    expect(args.help === false && args.options.model).toBe(DEFAULT_MODEL);
    expect(args.help === false && args.options).not.toHaveProperty('concurrency');
    expect(args.help === false && args.options).not.toHaveProperty('minEventsBefore');
    expect(args.help === false && args.options).not.toHaveProperty('reviewsPerProduct');
    expect(args.help === false && args.options).not.toHaveProperty('imagesPerProduct');
  });

  it('turns the image download off with --images-per-product 0', () => {
    const args = parseBundleArgs([...REQUIRED, '--images-per-product', '0']);
    expect(args.help === false && args.options.imagesPerProduct).toBe(0);
    expect(() => parseBundleArgs([...REQUIRED, '--images-per-product', '-1'])).toThrow(CliError);
  });

  it('refuses a missing option, an unknown adapter and an unknown step', () => {
    const without = (flag: string) => {
      const at = REQUIRED.indexOf(flag);
      return [...REQUIRED.slice(0, at), ...REQUIRED.slice(at + 2)];
    };
    expect(() => parseBundleArgs(without('--seed'))).toThrow('--seed is required');
    expect(() => parseBundleArgs(without('--users'))).toThrow('--users is required');
    expect(() => parseBundleArgs(['webshop', 'src', ...REQUIRED.slice(2)])).toThrow(
      '<adapter> must be one of amazon_reviews_2023',
    );
    expect(() => parseBundleArgs([...REQUIRED, '--from', 'deploy'])).toThrow(CliError);
    expect(() => parseBundleArgs(['amazon_reviews_2023'])).toThrow('missing <src>');
  });

  it('shows help', () => {
    expect(parseBundleArgs(['--help'])).toEqual({ help: true });
    expect(USAGE).toContain('--reviews-per-product');
    expect(USAGE).toContain('--model');
    expect(USAGE).toContain('--images-per-product');
  });
});
