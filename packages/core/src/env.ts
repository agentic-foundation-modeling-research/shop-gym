/**
 * Explicit credential loading.
 *
 * Nothing in ShopGym reads `process.env` at import time. Entry points call
 * `loadCredentials` once and pass the result down. Values exported in the
 * shell take precedence over the project `.env`; empty values count as
 * unset so a copied `.env.example` with blank keys behaves like no file.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { parseEnv } from 'node:util';

/** Provider credentials and routing known to ShopGym. */
export interface Credentials {
  readonly anthropicApiKey?: string;
  readonly anthropicAuthToken?: string;
  readonly anthropicBaseUrl?: string;
  readonly openaiApiKey?: string;
  readonly openaiBaseUrl?: string;
  /** Key for the proxy that `*_BASE_URL` points at, when one is used. */
  readonly piProxyApiKey?: string;
}

const KEYS = {
  anthropicApiKey: 'ANTHROPIC_API_KEY',
  anthropicAuthToken: 'ANTHROPIC_AUTH_TOKEN',
  anthropicBaseUrl: 'ANTHROPIC_BASE_URL',
  openaiApiKey: 'OPENAI_API_KEY',
  openaiBaseUrl: 'OPENAI_BASE_URL',
  piProxyApiKey: 'PI_PROXY_API_KEY',
} as const satisfies Record<keyof Credentials, string>;

/**
 * Load credentials from `<projectRoot>/.env` merged under `env`.
 *
 * @param projectRoot Directory containing the optional `.env` file.
 * @param env Variables that take precedence, normally `process.env`.
 * @returns Credentials with only the non-empty keys present.
 */
export function loadCredentials(projectRoot: string, env: NodeJS.ProcessEnv): Credentials {
  const envFile = path.join(projectRoot, '.env');
  const fromFile = fs.existsSync(envFile) ? parseEnv(fs.readFileSync(envFile, 'utf-8')) : {};

  const credentials: { -readonly [K in keyof Credentials]?: string } = {};
  for (const [field, name] of Object.entries(KEYS) as [keyof Credentials, string][]) {
    const value = nonEmpty(env[name]) ?? nonEmpty(fromFile[name]);
    if (value !== undefined) {
      credentials[field] = value;
    }
  }
  return credentials;
}

function nonEmpty(value: string | undefined): string | undefined {
  return value === undefined || value.trim() === '' ? undefined : value;
}
