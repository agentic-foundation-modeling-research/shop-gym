/**
 * The build loop: seeds the storefront and backend templates into a run,
 * starts the backend sidecar over the run's dataset, and drives the harness
 * plan-exec loop with the build prompts and verifier set. The storefront
 * sidecar is built and started by the first storefront verifier that needs
 * it and restarted when the copy changes.
 *
 * ```
 * <runDir>/
 *   AGENTS.md  prompts/  plan.md  iters/  run.json      (harness)
 *   build.json                                          (port, flags, template fingerprints)
 *   sidecar.log  storefront.log                         (sidecar stdout/stderr)
 *   artifact/
 *     data/ manual/            immutable seed (`artifactSeedDir`)
 *     storefront/ backend/     template copies the agent edits
 * ```
 *
 * A non-empty `runDir` is resumed: `build.json` supplies the port and flags
 * so the rendered prompts match the originals the harness checks.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { AgentEvent, AgentRuntime, ModelRef, ToolSet } from '@shop-gym/agent';
import {
  type PlanExecLoopConfig,
  type PlanExecLoopResult,
  Workspace,
  runPlanExecLoop,
} from '@shop-gym/harness';

import { loadBuildPrompts } from './prompts.js';
import { type TemplateFingerprint, seedTemplate } from './seed.js';
import { BackendSidecar, type SidecarLaunch, freePort } from './sidecar.js';
import { type StorefrontLaunch, StorefrontSidecar } from './storefront_sidecar.js';
import {
  OwnedFilesVerifier,
  type SchemaIntrospector,
  type StorefrontJudge,
  buildVerifiers,
} from './verifiers/index.js';
import type { CommandRunner } from './verifiers/subprocess.js';

export const BUILD_JSON = 'build.json';
export const SIDECAR_LOG = 'sidecar.log';
export const STOREFRONT_LOG = 'storefront.log';
export const STOREFRONT_DIRNAME = 'storefront';
export const BACKEND_DIRNAME = 'backend';
export const DATA_DIRNAME = 'data';
export const MANUAL_DIRNAME = 'manual';
const DEFAULT_TIMEOUT_MS = 3_600_000;

export interface BuildLoopOptions {
  readonly runDir: string;
  /** Immutable inputs: `data/` (served by the sidecar) and optionally `manual/`. */
  readonly seedDir: string;
  readonly storefrontTemplateDir: string;
  readonly backendTemplateDir: string;
  /** Plan `gen_backend` first and run the backend verifiers. */
  readonly genBackend: boolean;
  readonly runtime: AgentRuntime;
  readonly model: ModelRef;
  readonly tools: ToolSet;
  readonly maxIters: number;
  readonly timeoutMs?: number;
  /** Sidecar port; a free port is picked when omitted. */
  readonly backendPort?: number;
  /** Resume a run whose prior status would otherwise be refused. */
  readonly force?: boolean;
  /** Visual judge for the storefront verifiers; `visual_judge` is skipped when omitted. */
  readonly judge?: StorefrontJudge;
  readonly onEvent?: (iterId: string, event: AgentEvent) => void;
  /** Test seams. */
  readonly commandRunner?: CommandRunner;
  readonly sidecarLaunch?: SidecarLaunch;
  readonly storefrontLaunch?: StorefrontLaunch;
  readonly introspect?: SchemaIntrospector;
}

/** Persisted as `build.json` (camelCase) and read back on resume. */
export interface BuildRunInfo {
  readonly genBackend: boolean;
  readonly backendPort: number;
  readonly backendUrl: string;
  readonly templates: {
    readonly storefront: TemplateFingerprint;
    readonly backend: TemplateFingerprint;
  };
}

export interface BuildLoopResult extends PlanExecLoopResult {
  readonly build: BuildRunInfo;
}

export async function runBuildLoop(options: BuildLoopOptions): Promise<BuildLoopResult> {
  const artifactDir = path.join(options.runDir, 'artifact');
  const existing = await readBuildInfo(options.runDir);
  const port = existing?.backendPort ?? options.backendPort ?? (await freePort());
  const genBackend = existing?.genBackend ?? options.genBackend;
  const backendUrl = `http://127.0.0.1:${port}`;
  const prompts = await loadBuildPrompts({ backendUrl, genBackend });
  const config: PlanExecLoopConfig = {
    runDir: options.runDir,
    prompts: { planner: prompts.planner, execute: prompts.execute },
    agentsMd: prompts.agentsMd,
    artifactSeedDir: options.seedDir,
    maxIters: options.maxIters,
    timeoutMs: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    model: options.model,
    tools: options.tools,
  };

  let build = existing;
  if (build === undefined) {
    await Workspace.create(config);
    const seedOptions =
      options.commandRunner !== undefined ? { runner: options.commandRunner } : {};
    const storefront = await seedTemplate({
      templateDir: options.storefrontTemplateDir,
      destDir: path.join(artifactDir, STOREFRONT_DIRNAME),
      ...seedOptions,
    });
    const backend = await seedTemplate({
      templateDir: options.backendTemplateDir,
      destDir: path.join(artifactDir, BACKEND_DIRNAME),
      ...seedOptions,
    });
    await writeStorefrontEnv(path.join(artifactDir, STOREFRONT_DIRNAME), backendUrl);
    build = { genBackend, backendPort: port, backendUrl, templates: { storefront, backend } };
    await fs.writeFile(
      path.join(options.runDir, BUILD_JSON),
      `${JSON.stringify(build, null, 2)}\n`,
    );
  }

  const sidecar = new BackendSidecar({
    backendDir: path.join(artifactDir, BACKEND_DIRNAME),
    dataDir: path.join(artifactDir, DATA_DIRNAME),
    port,
    logPath: path.join(options.runDir, SIDECAR_LOG),
    ...(options.sidecarLaunch !== undefined ? { launch: options.sidecarLaunch } : {}),
  });
  const storefront = new StorefrontSidecar({
    storefrontDir: path.join(artifactDir, STOREFRONT_DIRNAME),
    backendUrl,
    port: await freePort(),
    logPath: path.join(options.runDir, STOREFRONT_LOG),
    ...(options.storefrontLaunch !== undefined ? { launch: options.storefrontLaunch } : {}),
  });
  const ownedFiles = new OwnedFilesVerifier();
  const verifiers = buildVerifiers({
    genBackend,
    sidecar,
    ownedFiles,
    storefront: {
      sidecar: storefront,
      dataDir: path.join(artifactDir, DATA_DIRNAME),
      manualDir: path.join(artifactDir, MANUAL_DIRNAME),
      ...(options.judge !== undefined ? { judge: options.judge } : {}),
    },
    ...(options.commandRunner !== undefined ? { runner: options.commandRunner } : {}),
    ...(options.introspect !== undefined ? { introspect: options.introspect } : {}),
  });

  await sidecar.start();
  try {
    await ownedFiles.prime(artifactDir);
    const result = await runPlanExecLoop(
      {
        ...config,
        verifiers,
        onEvent: (iterId, event) => {
          options.onEvent?.(iterId, event);
          if (event.kind === 'message' && event.role === 'assistant' && event.stopReason) {
            void sidecar.restartIfChanged();
          }
        },
      },
      options.runtime,
      { force: existing === undefined || options.force === true },
    );
    return { ...result, build };
  } finally {
    await storefront.stop();
    await sidecar.stop();
  }
}

/** The run's `build.json`, or `undefined` when the run has not been seeded. */
export async function readBuildInfo(runDir: string): Promise<BuildRunInfo | undefined> {
  const raw = await fs.readFile(path.join(runDir, BUILD_JSON), 'utf-8').catch(() => undefined);
  return raw === undefined ? undefined : (JSON.parse(raw) as BuildRunInfo);
}

/** Point the storefront copy at the sidecar; the template's server reads `.env`. */
async function writeStorefrontEnv(storefrontDir: string, backendUrl: string): Promise<void> {
  await fs.writeFile(
    path.join(storefrontDir, '.env'),
    `PUBLIC_STORE_DOMAIN=${backendUrl}\nSHOP_BACKEND_URL=${backendUrl}\n`,
  );
}
