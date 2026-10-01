/**
 * Services and resolved settings shared by every gen step.
 *
 * `GenContext` is a flat object: the validated config, resolved paths, the
 * LLM client and agent runtime, the image backend, and optional test
 * seams for the build loop and hosting smoke test. Per-step logging and
 * cancellation arrive through the pipeline `StepContext`, not here.
 */

import * as path from 'node:path';

import type { AgentEvent, AgentRuntime, LlmClient, ModelRef, ToolSet } from '@shop-gym/agent';
import { type Credentials, loadCredentials } from '@shop-gym/core';

import { fileTools } from '../explore/files.js';
import { parseModel } from '../explore/pipeline.js';
import { repoRoot } from './build/seed.js';
import type { SidecarLaunch } from './build/sidecar.js';
import type { SchemaIntrospector } from './build/verifiers/index.js';
import type { CommandRunner } from './build/verifiers/subprocess.js';
import { DEFAULT_OUTPUT_ROOT, type GenConfig } from './config.js';
import { type ImageBackend, createImageBackend } from './data_synth/images/backend.js';

/** What a caller provides to `generateShop` besides the config. */
export interface GenDeps {
  readonly llm: LlmClient;
  readonly runtime: AgentRuntime;
  /** Defaults to `loadCredentials(<repo root>, process.env)`. */
  readonly credentials?: Credentials;
  /** Overrides the backend named by `config.imageBackend`. */
  readonly images?: ImageBackend;
  /** Tools handed to the build agent; defaults to the file tools. */
  readonly tools?: ToolSet;
  readonly log?: (line: string) => void;
  readonly signal?: AbortSignal;
  /** Agent events from the build loop, keyed by iteration id. */
  readonly onEvent?: (iterId: string, event: AgentEvent) => void;
  /** Test seams. */
  readonly fetch?: typeof fetch;
  readonly commandRunner?: CommandRunner;
  readonly sidecarLaunch?: SidecarLaunch;
  readonly introspect?: SchemaIntrospector;
}

export interface GenContext {
  readonly config: GenConfig;
  /** Absolute shop directory (`outputs/shops/<name>` by default). */
  readonly shopDir: string;
  /** Absolute Shop Manual input directories. */
  readonly manualDirs: readonly string[];
  readonly credentials: Credentials;
  readonly llm: LlmClient;
  readonly runtime: AgentRuntime;
  readonly model: ModelRef;
  readonly buildModel: ModelRef;
  readonly images: ImageBackend;
  readonly tools: ToolSet;
  readonly onEvent?: (iterId: string, event: AgentEvent) => void;
  readonly commandRunner?: CommandRunner;
  readonly sidecarLaunch?: SidecarLaunch;
  readonly introspect?: SchemaIntrospector;
}

export function createGenContext(config: GenConfig, deps: GenDeps): GenContext {
  const credentials = deps.credentials ?? loadCredentials(repoRoot(), process.env);
  const shopDir = path.resolve(config.outDir ?? path.join(DEFAULT_OUTPUT_ROOT, config.name));
  const fetchImpl = deps.fetch ?? fetch;
  return {
    config,
    shopDir,
    manualDirs: config.manualDirs.map((dir) => path.resolve(dir)),
    credentials,
    llm: deps.llm,
    runtime: deps.runtime,
    model: parseModel(config.model),
    buildModel: parseModel(config.buildModel ?? config.model),
    images:
      deps.images ??
      createImageBackend(config.imageBackend, {
        cacheDir: path.join(shopDir, '.shop_gen', 'image_cache'),
        credentials,
        fetch: fetchImpl,
      }),
    tools: deps.tools ?? fileTools(),
    ...(deps.onEvent !== undefined ? { onEvent: deps.onEvent } : {}),
    ...(deps.commandRunner !== undefined ? { commandRunner: deps.commandRunner } : {}),
    ...(deps.sidecarLaunch !== undefined ? { sidecarLaunch: deps.sidecarLaunch } : {}),
    ...(deps.introspect !== undefined ? { introspect: deps.introspect } : {}),
  };
}
