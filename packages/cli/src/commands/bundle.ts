/** `shopgym bundle <adapter> <src> --out <dir> ...`: build a Source bundle from a dataset. */

import { PiLlmClient } from '@shop-gym/agent';
import {
  BUNDLE_ADAPTERS,
  BUNDLE_STEPS,
  type BundleOptionsInput,
  DEFAULT_MIN_EVENTS_BEFORE,
  buildBundle,
} from '@shop-gym/shop-arena';

import { enumOption, flag, integerOption, parse, parseEnum, stringOption } from '../args.js';
import { CliError, DEFAULT_MODEL, cliCredentials, findRepoRoot } from '../context.js';
import { logLine } from '../progress.js';

export const USAGE = `Usage: shopgym bundle <adapter> <src> --out <dir> --category <name> --cutoff <date>
                      --products <n> --users <n> --seed <s> [options]

Build a complete Source bundle (bundle.json, catalog/, users/, events/)
from a source dataset. The sample step picks modeled users at random,
keeps the products in their histories, and fills up with the most
reviewed products of the same categories. The complete step fills the
missing catalog fields by rules, lets an LLM name the variants and write
one User profile per modeled user, and marks each filled field in
provenance. LLM replies are cached in <dir>/.bundle/llm_cache.

Adapters: ${BUNDLE_ADAPTERS.join(', ')}
  <src> is the dataset directory with review_categories/<name>.jsonl and
  meta_categories/meta_<name>.jsonl.

Options:
  --out <dir>                 Bundle directory (required); its base name is the bundle name
  --category <name>           Dataset category, for example Video_Games (required)
  --cutoff <date>             Events before it are history, after it Task targets (required)
  --products <n>              Products to fill up to (required)
  --users <n>                 Modeled users to pick (required)
  --seed <s>                  Sampling seed (required)
  --min-events-before <n>     User events a modeled user has before the cutoff
                              (default: ${DEFAULT_MIN_EVENTS_BEFORE})
  --reviews-per-product <n>   Keep at most n reviews of a product, plus the reviews
                              of modeled users (default: no cap)
  --model <provider/id>       Model for the complete step (default: ${DEFAULT_MODEL})
  --concurrency <n>           Parallel LLM calls in the complete step
  --from <step>               Rerun from this step: ${BUNDLE_STEPS.join(' | ')}
  -h, --help                  Show this help

Prints the bundle directory on the last line of stdout.`;

export type BundleArgs =
  | { readonly help: true }
  | { readonly help: false; readonly options: BundleOptionsInput };

export function parseBundleArgs(argv: readonly string[]): BundleArgs {
  const args = parse(argv, {
    out: { type: 'string' },
    category: { type: 'string' },
    cutoff: { type: 'string' },
    products: { type: 'string' },
    users: { type: 'string' },
    seed: { type: 'string' },
    'min-events-before': { type: 'string' },
    'reviews-per-product': { type: 'string' },
    model: { type: 'string' },
    concurrency: { type: 'string' },
    from: { type: 'string' },
    help: { type: 'boolean', short: 'h' },
  });
  if (flag(args, 'help')) {
    return { help: true };
  }
  const [adapter, sourceDir, ...extra] = args.positionals;
  if (adapter === undefined) {
    throw new CliError('missing <adapter>');
  }
  if (sourceDir === undefined) {
    throw new CliError('missing <src>');
  }
  if (extra.length > 0) {
    throw new CliError(`unexpected argument ${JSON.stringify(extra[0])}`);
  }
  const required = (name: string): string => {
    const value = stringOption(args, name);
    if (value === undefined) {
      throw new CliError(`--${name} is required`);
    }
    return value;
  };
  const requiredInteger = (name: string): number => {
    const value = integerOption(args, name);
    if (value === undefined) {
      throw new CliError(`--${name} is required`);
    }
    return value;
  };
  const minEventsBefore = integerOption(args, 'min-events-before');
  const reviewsPerProduct = integerOption(args, 'reviews-per-product');
  const concurrency = integerOption(args, 'concurrency');
  const from = enumOption(args, 'from', BUNDLE_STEPS);
  return {
    help: false,
    options: {
      adapter: parseEnum('<adapter>', adapter, BUNDLE_ADAPTERS),
      sourceDir,
      outDir: required('out'),
      category: required('category'),
      cutoff: required('cutoff'),
      products: requiredInteger('products'),
      users: requiredInteger('users'),
      seed: required('seed'),
      ...(minEventsBefore !== undefined ? { minEventsBefore } : {}),
      ...(reviewsPerProduct !== undefined ? { reviewsPerProduct } : {}),
      model: stringOption(args, 'model') ?? DEFAULT_MODEL,
      ...(concurrency !== undefined ? { concurrency } : {}),
      ...(from !== undefined ? { from } : {}),
    },
  };
}

export async function run(argv: readonly string[]): Promise<number> {
  const args = parseBundleArgs(argv);
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  const credentials = cliCredentials(findRepoRoot());
  const result = await buildBundle(args.options, {
    llm: new PiLlmClient({ credentials }),
    log: logLine,
  });
  console.log(result.bundleDir);
  return 0;
}
