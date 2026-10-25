/** `shopgym guru build|explore|solve|eval --config <path>`: benchmark stages. */

import { PiRuntime } from '@shop-gym/agent';
import { parseModel } from '@shop-gym/shop-arena';
import {
  type GuruConfig,
  benchmarksDir,
  build,
  createPiBrowserAgent,
  createPiJudge,
  evaluate,
  exploreStage,
  loadGuruConfig,
  shopOutDir,
  solve,
} from '@shop-gym/shop-guru';

import { flag, integerOption, parse, parseEnum, stringOption } from '../args.js';
import { CliError, cliCredentials, findRepoRoot } from '../context.js';
import { logLine } from '../progress.js';

const STAGES = ['build', 'explore', 'solve', 'eval'] as const;

export type GuruStage = (typeof STAGES)[number];

export const USAGE = `Usage: shopgym guru <stage> --config <path> [options]

Stages:
  build      Generate seed tasks from the dataset and write benchmarks/
  explore    Discover extra tasks with an agent and merge them in
  solve      Run every benchmark task once without grading
  eval       Run, grade and aggregate every benchmark task

Options:
  --config <path>              Guru config JSON (required)
  --shop <name>                Override the config's shop name
  --skills <a,b>               Restrict solve/eval to these skills
  --model <provider/id>        Override the solver and explorer model
  --judge-model <provider/id>  Override the judge model
  --concurrency <n>            Episodes in flight at once
  --headless | --no-headless   Browser visibility for solve/eval
  -h, --help                   Show this help

Prints the output directory on the last line of stdout (eval: the run
directory, then the pass rate).`;

export interface GuruOverrides {
  readonly shop?: string;
  readonly model?: string;
  readonly judgeModel?: string;
  readonly concurrency?: number;
  readonly headless?: boolean;
}

export interface GuruArgs {
  readonly help: boolean;
  readonly stage: GuruStage;
  readonly configPath: string;
  readonly skills?: readonly string[];
  readonly overrides: GuruOverrides;
}

export function parseGuruArgs(argv: readonly string[]): GuruArgs {
  const args = parse(argv, {
    config: { type: 'string' },
    shop: { type: 'string' },
    skills: { type: 'string' },
    model: { type: 'string' },
    'judge-model': { type: 'string' },
    concurrency: { type: 'string' },
    headless: { type: 'boolean' },
    'no-headless': { type: 'boolean' },
    help: { type: 'boolean', short: 'h' },
  });
  if (flag(args, 'help')) {
    return { help: true, stage: 'build', configPath: '', overrides: {} };
  }
  const [stageRaw, ...extra] = args.positionals;
  if (stageRaw === undefined) {
    throw new CliError(`missing <stage>; expected one of ${STAGES.join(', ')}`);
  }
  if (extra.length > 0) {
    throw new CliError(`unexpected argument ${JSON.stringify(extra[0])}`);
  }
  const stage = parseEnum('<stage>', stageRaw, STAGES);
  const configPath = stringOption(args, 'config');
  if (configPath === undefined) {
    throw new CliError('--config is required');
  }
  if (flag(args, 'headless') && flag(args, 'no-headless')) {
    throw new CliError('--headless and --no-headless are mutually exclusive');
  }
  const skillsRaw = stringOption(args, 'skills');
  const skills = skillsRaw
    ?.split(',')
    .map((s) => s.trim())
    .filter((s) => s !== '');
  const shop = stringOption(args, 'shop');
  const model = stringOption(args, 'model');
  const judgeModel = stringOption(args, 'judge-model');
  const concurrency = integerOption(args, 'concurrency');
  const headless = flag(args, 'headless') ? true : flag(args, 'no-headless') ? false : undefined;
  return {
    help: false,
    stage,
    configPath,
    ...(skills !== undefined && skills.length > 0 ? { skills } : {}),
    overrides: {
      ...(shop !== undefined ? { shop } : {}),
      ...(model !== undefined ? { model } : {}),
      ...(judgeModel !== undefined ? { judgeModel } : {}),
      ...(concurrency !== undefined ? { concurrency } : {}),
      ...(headless !== undefined ? { headless } : {}),
    },
  };
}

/** Apply CLI overrides on top of a loaded config. */
export function applyOverrides(config: GuruConfig, overrides: GuruOverrides): GuruConfig {
  return {
    ...config,
    ...(overrides.shop !== undefined ? { shop: overrides.shop } : {}),
    ...(overrides.model !== undefined ? { model: parseModel(overrides.model) } : {}),
    ...(overrides.judgeModel !== undefined ? { judgeModel: parseModel(overrides.judgeModel) } : {}),
    ...(overrides.concurrency !== undefined ? { concurrency: overrides.concurrency } : {}),
    ...(overrides.headless !== undefined ? { headless: overrides.headless } : {}),
  };
}

export async function run(argv: readonly string[]): Promise<number> {
  const args = parseGuruArgs(argv);
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  const config = applyOverrides(await loadGuruConfig(args.configPath), args.overrides);
  const credentials = cliCredentials(findRepoRoot());
  const skills = args.skills !== undefined ? { skills: args.skills } : {};
  switch (args.stage) {
    case 'build': {
      const result = await build(config);
      logLine(`${result.tasks.length} tasks kept, ${result.dropped.length} dropped`);
      console.log(benchmarksDir(shopOutDir(config)));
      return 0;
    }
    case 'explore': {
      const result = await exploreStage(config, { runtime: new PiRuntime({ credentials }) });
      logLine(
        `${result.tasks.length} tasks accepted, ${result.rejected.length} rejected, ${result.dropped.length} dropped`,
      );
      console.log(result.outDir);
      return 0;
    }
    case 'solve': {
      const agent = createPiBrowserAgent(config, credentials);
      const result = await solve(config, { agent, ...skills });
      logLine(`${result.results.length} episodes`);
      console.log(result.runDir);
      return 0;
    }
    case 'eval': {
      const agent = createPiBrowserAgent(config, credentials);
      const judge = createPiJudge(config, credentials);
      const result = await evaluate(config, { agent, judge, ...skills });
      const { passed, total, errors } = result.aggregate;
      logLine(`passed ${passed}/${total} (${errors} errors)`);
      console.log(result.runDir);
      console.log(result.aggregate.passRate.toFixed(4));
      return 0;
    }
  }
}
