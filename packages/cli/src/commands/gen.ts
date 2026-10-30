/** `shopgym gen <manual_dir>... --name <shop>`: generate a SandboxShop. */

import { PiLlmClient, PiRuntime } from '@shop-gym/agent';
import {
  GEN_STEPS,
  type GenConfigInput,
  type GenStepName,
  generateShop,
} from '@shop-gym/shop-arena';

import { enumOption, flag, integerOption, parse, stringOption } from '../args.js';
import { CliError, DEFAULT_MODEL, cliCredentials, findRepoRoot } from '../context.js';
import { logEvent, logLine } from '../progress.js';

const IMAGE_BACKENDS = ['placeholder', 'openai'] as const;

/** Build agent model when `--build-model` is absent, even if `--model` is set. */
const DEFAULT_BUILD_MODEL = 'openai/gpt-6-sol';

export const USAGE = `Usage: shopgym gen <manual_dir>... --name <shop> [options]

Generate a SandboxShop from one or more Shop Manual directories.

Options:
  --name <slug>                 Shop name (required; lowercase slug)
  --out <dir>                   Shop directory (default: outputs/shops/<name>)
  --gen-backend                 Let the build agent extend the backend copy
  --from <step>                 Rerun from this step: ${GEN_STEPS.join(' | ')}
  --model <provider/id>         Model for the synthesis steps (default: ${DEFAULT_MODEL})
  --build-model <provider/id>   Model for the build agent (default: ${DEFAULT_BUILD_MODEL})
  --image-backend <name>        ${IMAGE_BACKENDS.join(' | ')} (default: placeholder)
  --max-iters <n>               Executor iterations for the build loop
  --collections <n>             Collections to synthesize
  --products-per-collection <n> Products per collection
  --images-per-product <n>      Images per product (0-4)
  --concurrency <n>             Parallel LLM calls in synthesis
  --force-resume                Resume a build run that ended in a refused status
  -h, --help                    Show this help

Prints the shop directory on the last line of stdout.`;

export interface GenArgs {
  readonly help: boolean;
  readonly config: GenConfigInput;
}

export function parseGenArgs(argv: readonly string[]): GenArgs {
  const args = parse(argv, {
    name: { type: 'string' },
    out: { type: 'string' },
    'gen-backend': { type: 'boolean' },
    from: { type: 'string' },
    model: { type: 'string' },
    'build-model': { type: 'string' },
    'image-backend': { type: 'string' },
    'max-iters': { type: 'string' },
    collections: { type: 'string' },
    'products-per-collection': { type: 'string' },
    'images-per-product': { type: 'string' },
    concurrency: { type: 'string' },
    'force-resume': { type: 'boolean' },
    help: { type: 'boolean', short: 'h' },
  });
  if (flag(args, 'help')) {
    return { help: true, config: { name: '', manualDirs: [], model: DEFAULT_MODEL } };
  }
  if (args.positionals.length === 0) {
    throw new CliError('missing <manual_dir>');
  }
  const name = stringOption(args, 'name');
  if (name === undefined) {
    throw new CliError('--name is required');
  }
  const outDir = stringOption(args, 'out');
  const from: GenStepName | undefined = enumOption(args, 'from', GEN_STEPS);
  const imageBackend = enumOption(args, 'image-backend', IMAGE_BACKENDS);
  const maxIters = integerOption(args, 'max-iters');
  const concurrency = integerOption(args, 'concurrency');
  const collections = integerOption(args, 'collections');
  const productsPerCollection = integerOption(args, 'products-per-collection');
  const imagesPerProduct = imagesOption(args.values['images-per-product']);
  return {
    help: false,
    config: {
      name,
      manualDirs: [...args.positionals],
      model: stringOption(args, 'model') ?? DEFAULT_MODEL,
      buildModel: stringOption(args, 'build-model') ?? DEFAULT_BUILD_MODEL,
      genBackend: flag(args, 'gen-backend'),
      forceResume: flag(args, 'force-resume'),
      catalog: {
        ...(collections !== undefined ? { collections } : {}),
        ...(productsPerCollection !== undefined ? { productsPerCollection } : {}),
        ...(imagesPerProduct !== undefined ? { imagesPerProduct } : {}),
      },
      ...(outDir !== undefined ? { outDir } : {}),
      ...(from !== undefined ? { from } : {}),
      ...(imageBackend !== undefined ? { imageBackend } : {}),
      ...(maxIters !== undefined ? { maxIters } : {}),
      ...(concurrency !== undefined ? { concurrency } : {}),
    },
  };
}

/** `--images-per-product` allows zero, unlike the other counts. */
function imagesOption(raw: string | boolean | undefined): number | undefined {
  if (typeof raw !== 'string') {
    return undefined;
  }
  if (!/^\d+$/.test(raw)) {
    throw new CliError(
      `--images-per-product must be a non-negative integer, got ${JSON.stringify(raw)}`,
    );
  }
  return Number(raw);
}

export async function run(argv: readonly string[]): Promise<number> {
  const args = parseGenArgs(argv);
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  const credentials = cliCredentials(findRepoRoot());
  const result = await generateShop(args.config, {
    llm: new PiLlmClient({ credentials }),
    runtime: new PiRuntime({ credentials }),
    credentials,
    log: logLine,
    onEvent: logEvent,
  });
  console.log(result.shopDir);
  return 0;
}
