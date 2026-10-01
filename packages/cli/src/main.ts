#!/usr/bin/env node
/** `shopgym` entry point: pick the subcommand, run it, report failures on one line. */

import { realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

import { ZodError } from 'zod';

import * as doctor from './commands/doctor.js';
import * as explore from './commands/explore.js';
import * as gen from './commands/gen.js';
import * as guru from './commands/guru.js';
import * as host from './commands/host.js';
import * as trace from './commands/trace.js';
import { CliError } from './context.js';

interface Command {
  readonly run: (argv: readonly string[]) => Promise<number>;
  readonly USAGE: string;
}

const COMMANDS: Readonly<Record<string, Command>> = { explore, gen, host, guru, trace, doctor };

const USAGE = `Usage: shopgym <command> [args]

Commands:
  explore <url>                      Explore a live storefront into a Shop Manual
  gen <manual_dir>... --name <shop>  Generate a SandboxShop from Shop Manuals
  host start|stop|restart|list       Run published shops locally
  guru build|explore|solve|eval      Benchmark stages for a hosted shop
  trace <iter_dir>                   Render a harness iteration as text
  doctor                             Check the local toolchain

Run \`shopgym <command> --help\` for details.`;

export async function main(argv: readonly string[]): Promise<number> {
  const [name, ...rest] = argv;
  if (name === undefined || name === '-h' || name === '--help' || name === 'help') {
    console.log(USAGE);
    return 0;
  }
  const command = COMMANDS[name];
  if (command === undefined) {
    process.stderr.write(`shopgym: unknown command ${JSON.stringify(name)}\n\n${USAGE}\n`);
    return 1;
  }
  try {
    return await command.run(rest);
  } catch (error) {
    process.stderr.write(`shopgym ${name}: ${describe(error)}\n`);
    return 1;
  }
}

/** One-line description; the stack is appended only for unexpected errors. */
export function describe(error: unknown): string {
  if (error instanceof ZodError) {
    return error.issues.map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`).join('; ');
  }
  if (!(error instanceof Error)) {
    return String(error);
  }
  const expected =
    error instanceof CliError || typeof (error as NodeJS.ErrnoException).code === 'string';
  if (expected || error.stack === undefined) {
    return error.message;
  }
  return error.stack;
}

if (
  process.argv[1] !== undefined &&
  import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href
) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    (error: unknown) => {
      process.stderr.write(`shopgym: ${describe(error)}\n`);
      process.exit(1);
    },
  );
}
