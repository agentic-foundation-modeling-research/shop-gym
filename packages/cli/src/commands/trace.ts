/** `shopgym trace <iter_dir>`: render one harness iteration as plain text. */

import { renderIterDir } from '@shop-gym/harness';

import { flag, parse } from '../args.js';
import { CliError } from '../context.js';

export const USAGE = `Usage: shopgym trace <iter_dir> [--full]

Render a harness iteration directory (iters/<id>/) as indented plain text.

Options:
  --full       Do not truncate long text blocks
  -h, --help   Show this help`;

export interface TraceArgs {
  readonly help: boolean;
  readonly iterDir: string;
  readonly full: boolean;
}

export function parseTraceArgs(argv: readonly string[]): TraceArgs {
  const args = parse(argv, {
    full: { type: 'boolean' },
    help: { type: 'boolean', short: 'h' },
  });
  if (flag(args, 'help')) {
    return { help: true, iterDir: '', full: false };
  }
  const [iterDir, ...extra] = args.positionals;
  if (iterDir === undefined) {
    throw new CliError('missing <iter_dir>');
  }
  if (extra.length > 0) {
    throw new CliError(`unexpected argument ${JSON.stringify(extra[0])}`);
  }
  return { help: false, iterDir, full: flag(args, 'full') };
}

export async function run(argv: readonly string[]): Promise<number> {
  const args = parseTraceArgs(argv);
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  const text = await renderIterDir(
    args.iterDir,
    args.full ? { maxChars: Number.POSITIVE_INFINITY } : {},
  );
  process.stdout.write(text);
  return 0;
}
