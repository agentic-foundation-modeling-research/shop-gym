/** `shopgym report`: serve the review reports in `packages/reports/pages/`. */

import { DEFAULT_HOST, DEFAULT_PORT, createReportServer } from '@shop-gym/reports';

import { flag, integerOption, parse, stringOption } from '../args.js';
import { CliError } from '../context.js';

export const USAGE = `Usage: shopgym report [--port <n>] [--host <addr>]

Serve the HTML reports in packages/reports/pages/ with an index page, until
Ctrl-C. Files are read on each request, so an edited report shows on reload.

Options:
  --port <n>     Port to bind (default ${DEFAULT_PORT})
  --host <addr>  Interface to bind (default ${DEFAULT_HOST}; 0.0.0.0 shares it on the network)
  -h, --help     Show this help`;

export interface ReportArgs {
  readonly help: boolean;
  readonly port: number;
  readonly host: string;
}

export function parseReportArgs(argv: readonly string[]): ReportArgs {
  const args = parse(argv, {
    port: { type: 'string' },
    host: { type: 'string' },
    help: { type: 'boolean', short: 'h' },
  });
  const [extra] = args.positionals;
  if (extra !== undefined) {
    throw new CliError(`unexpected argument ${JSON.stringify(extra)}`);
  }
  return {
    help: flag(args, 'help'),
    port: integerOption(args, 'port') ?? DEFAULT_PORT,
    host: stringOption(args, 'host') ?? DEFAULT_HOST,
  };
}

export async function run(argv: readonly string[]): Promise<number> {
  const args = parseReportArgs(argv);
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  const server = createReportServer({ port: args.port, host: args.host });
  await server.listen();
  console.log(server.url);
  process.stderr.write('Serving reports; press Ctrl-C to stop.\n');
  await interrupted();
  await server.close();
  return 0;
}

/** Resolves on the first SIGINT or SIGTERM. */
function interrupted(): Promise<void> {
  return new Promise((resolve) => {
    const stop = (): void => {
      process.off('SIGINT', stop);
      process.off('SIGTERM', stop);
      resolve();
    };
    process.on('SIGINT', stop);
    process.on('SIGTERM', stop);
  });
}
