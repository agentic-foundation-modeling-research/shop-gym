/** `shopgym explore <url>`: produce a Shop Manual from a live storefront. */

import { EXPLORE_STEPS, type ExploreStep, exploreStorefront } from '@shop-gym/shop-arena';

import { enumOption, flag, integerOption, parse, stringOption } from '../args.js';
import { CliError, DEFAULT_MODEL, cliCredentials, findRepoRoot } from '../context.js';
import { logEvent, logLine } from '../progress.js';

export const USAGE = `Usage: shopgym explore <url> [options]

Explore a live storefront and write an anonymized Shop Manual.

Options:
  --out <dir>          Run directory (default: outputs/shop_manuals/<domain>/<run_id>)
  --model <provider/id>  Model for the explore agent (default: ${DEFAULT_MODEL})
  --max-iters <n>      Executor iterations for the explore step
  --timeout <ms>       Per-iteration wall clock budget
  --from <step>        Rerun from this step: ${EXPLORE_STEPS.join(' | ')}
  --force-resume       Resume a run that ended in a refused status
  -h, --help           Show this help

Prints the manual path on the last line of stdout.`;

export interface ExploreArgs {
  readonly help: boolean;
  readonly url: string;
  readonly outDir?: string;
  readonly model: string;
  readonly maxIters?: number;
  readonly timeoutMs?: number;
  readonly from?: ExploreStep;
  readonly forceResume: boolean;
}

export function parseExploreArgs(argv: readonly string[]): ExploreArgs {
  const args = parse(argv, {
    out: { type: 'string' },
    model: { type: 'string' },
    'max-iters': { type: 'string' },
    timeout: { type: 'string' },
    from: { type: 'string' },
    'force-resume': { type: 'boolean' },
    help: { type: 'boolean', short: 'h' },
  });
  if (flag(args, 'help')) {
    return { help: true, url: '', model: DEFAULT_MODEL, forceResume: false };
  }
  const [url, ...extra] = args.positionals;
  if (url === undefined) {
    throw new CliError('missing <url>');
  }
  if (extra.length > 0) {
    throw new CliError(`unexpected argument ${JSON.stringify(extra[0])}`);
  }
  const outDir = stringOption(args, 'out');
  const maxIters = integerOption(args, 'max-iters');
  const timeoutMs = integerOption(args, 'timeout');
  const from = enumOption(args, 'from', EXPLORE_STEPS);
  return {
    help: false,
    url,
    model: stringOption(args, 'model') ?? DEFAULT_MODEL,
    forceResume: flag(args, 'force-resume'),
    ...(outDir !== undefined ? { outDir } : {}),
    ...(maxIters !== undefined ? { maxIters } : {}),
    ...(timeoutMs !== undefined ? { timeoutMs } : {}),
    ...(from !== undefined ? { from } : {}),
  };
}

export async function run(argv: readonly string[]): Promise<number> {
  const args = parseExploreArgs(argv);
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  const { help: _help, ...options } = args;
  const result = await exploreStorefront({
    ...options,
    credentials: cliCredentials(findRepoRoot()),
    log: logLine,
    onEvent: logEvent,
  });
  logLine(`explore finished with status ${result.finalStatus}; run dir ${result.runDir}`);
  console.log(result.manualPath);
  return result.finalStatus === 'completed' ? 0 : 1;
}
