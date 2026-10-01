/**
 * Isolated pi model routing.
 *
 * Each run gets its own pi config directory holding a `models.json` with
 * only the base-URL overrides from ShopGym's credentials. API keys never
 * touch disk: they are injected into the `ModelRuntime` after creation.
 * Nothing under `~/.pi` is read.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import type { Api, Model } from '@earendil-works/pi-ai';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import type { Credentials } from '@shop-gym/core';

import type { ModelRef } from '../../types.js';

/** Shape of the `providers` block ShopGym writes to pi's `models.json`. */
export interface ModelsConfig {
  readonly providers: Readonly<Record<string, { readonly baseUrl: string }>>;
}

/** The requested model is not in pi's catalog for that provider. */
export class UnknownModelError extends Error {
  constructor(ref: ModelRef) {
    super(`pi has no model "${ref.id}" for provider "${ref.provider}"`);
    this.name = 'UnknownModelError';
  }
}

/** Provider base-URL overrides derived from credentials. Keys are omitted. */
export function buildModelsConfig(credentials: Credentials): ModelsConfig {
  const providers: Record<string, { baseUrl: string }> = {};
  if (credentials.anthropicBaseUrl !== undefined) {
    providers.anthropic = { baseUrl: credentials.anthropicBaseUrl };
  }
  if (credentials.openaiBaseUrl !== undefined) {
    providers.openai = { baseUrl: credentials.openaiBaseUrl };
  }
  return { providers };
}

/**
 * The key pi should send for `provider`.
 *
 * When the provider is routed through a gateway (`*_BASE_URL` set) the
 * gateway key wins over the provider's own key.
 */
export function providerApiKey(provider: string, credentials: Credentials): string | undefined {
  switch (provider) {
    case 'anthropic':
      return (
        (credentials.anthropicBaseUrl !== undefined ? credentials.piProxyApiKey : undefined) ??
        credentials.anthropicApiKey ??
        credentials.anthropicAuthToken
      );
    case 'openai':
      return (
        (credentials.openaiBaseUrl !== undefined ? credentials.piProxyApiKey : undefined) ??
        credentials.openaiApiKey
      );
    default:
      return undefined;
  }
}

/**
 * Create a `ModelRuntime` confined to `configDir`.
 *
 * Writes `configDir/models.json` and registers runtime API keys for every
 * provider the credentials cover.
 */
export async function createPiModelRuntime(
  configDir: string,
  credentials: Credentials,
): Promise<ModelRuntime> {
  await fs.mkdir(configDir, { recursive: true });
  const modelsPath = path.join(configDir, 'models.json');
  await fs.writeFile(modelsPath, `${JSON.stringify(buildModelsConfig(credentials), null, 2)}\n`);
  const runtime = await ModelRuntime.create({
    authPath: path.join(configDir, 'auth.json'),
    modelsPath,
    refreshOnCreate: false,
  });
  for (const provider of ['anthropic', 'openai']) {
    const apiKey = providerApiKey(provider, credentials);
    if (apiKey !== undefined) {
      await runtime.setRuntimeApiKey(provider, apiKey);
    }
  }
  return runtime;
}

/** Look up `ref` in the runtime's catalog. */
export function resolveModel(runtime: ModelRuntime, ref: ModelRef): Model<Api> {
  const model = runtime.getModel(ref.provider, ref.id);
  if (model === undefined) {
    throw new UnknownModelError(ref);
  }
  return model;
}
