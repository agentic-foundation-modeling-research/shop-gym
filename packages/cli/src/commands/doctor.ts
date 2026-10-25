/** `shopgym doctor`: check the local toolchain and report remedies. */

import { execFile } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { promisify } from 'node:util';

import { STOREFRONT_TEMPLATE_DIR, build } from '@shop-gym/shop-arena';
import { chromium } from 'playwright';

import { flag, parse } from '../args.js';
import { CliError, cliCredentials, findRepoRoot } from '../context.js';
import { type DoctorFacts, formatReport, runChecks } from '../doctor/checks.js';

export const USAGE = `Usage: shopgym doctor

Check pnpm, Node, Playwright Chromium, both templates and credentials.
Exits 1 when any check fails.`;

const execFileAsync = promisify(execFile);

export async function run(argv: readonly string[]): Promise<number> {
  const args = parse(argv, { help: { type: 'boolean', short: 'h' } });
  if (flag(args, 'help')) {
    console.log(USAGE);
    return 0;
  }
  if (args.positionals.length > 0) {
    throw new CliError(`unexpected argument ${JSON.stringify(args.positionals[0])}`);
  }
  const results = runChecks(await gatherFacts());
  process.stdout.write(formatReport(results));
  return results.every((r) => r.ok) ? 0 : 1;
}

async function gatherFacts(): Promise<DoctorFacts> {
  const repoRoot = findRepoRoot();
  const envPath = path.join(repoRoot, '.env');
  const backendDir = build.defaultBackendTemplateDir();
  return {
    nodeVersion: process.versions.node,
    pnpmVersion: await pnpmVersion(),
    chromium: chromiumFact(),
    storefrontTemplate: templateFact(STOREFRONT_TEMPLATE_DIR),
    backendTemplate: templateFact(backendDir),
    envFile: { path: envPath, exists: fs.existsSync(envPath) },
    credentialKeys: Object.keys(cliCredentials(repoRoot)).sort(),
  };
}

async function pnpmVersion(): Promise<string | undefined> {
  try {
    const { stdout } = await execFileAsync('pnpm', ['--version'], { timeout: 10_000 });
    return stdout.trim();
  } catch {
    return undefined;
  }
}

function chromiumFact(): DoctorFacts['chromium'] {
  const executable = chromium.executablePath();
  return executable === '' ? undefined : { path: executable, exists: fs.existsSync(executable) };
}

function templateFact(dir: string): DoctorFacts['storefrontTemplate'] {
  return { dir, exists: fs.existsSync(path.join(dir, 'package.json')) };
}
