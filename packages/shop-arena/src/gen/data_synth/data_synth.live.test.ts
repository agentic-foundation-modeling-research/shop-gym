/**
 * Live `synth_identity` against a real model. Needs credentials and
 * network, so it only runs with `SHOPGYM_LIVE=1`. Model defaults to the
 * gen default; override with `SHOPGYM_LIVE_MODEL=<provider>/<id>`.
 */

import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { PiLlmClient } from '@shop-gym/agent';
import { FakeRuntime } from '@shop-gym/agent/testing';
import { loadCredentials } from '@shop-gym/core';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { repoRoot } from '../build/seed.js';
import { DEFAULT_MODEL, parseGenConfig } from '../config.js';
import { createGenContext } from '../context.js';
import { writeManualFixture } from '../testing.js';
import { createSynthContext } from './context.js';
import { synthIdentity } from './identity.js';
import { synthStore } from './store.js';

const LIVE = process.env.SHOPGYM_LIVE === '1';

describe.skipIf(!LIVE)('data_synth (live)', () => {
  let root: string;
  beforeAll(async () => {
    root = await fs.mkdtemp(path.join(os.tmpdir(), 'data-synth-live-'));
  });
  afterAll(async () => {
    await fs.rm(root, { recursive: true, force: true });
  });

  it('synthesizes identity and store from the manual fixture', { timeout: 300_000 }, async () => {
    const shopDir = path.join(root, 'shop');
    await writeManualFixture(path.join(shopDir, 'manual'));
    const credentials = loadCredentials(repoRoot(), process.env);
    const config = parseGenConfig({
      name: 'live',
      manualDirs: [path.join(shopDir, 'manual')],
      outDir: shopDir,
      model: process.env.SHOPGYM_LIVE_MODEL ?? DEFAULT_MODEL,
    });
    const context = createGenContext(config, {
      llm: new PiLlmClient({ credentials }),
      runtime: new FakeRuntime(),
      credentials,
    });
    const log: string[] = [];
    const sc = createSynthContext({
      outDir: shopDir,
      context,
      log: (l) => log.push(l),
      signal: new AbortController().signal,
    });
    const identity = await synthIdentity(sc);
    expect(identity.currency).toBe('USD');
    expect(identity.descriptor.length).toBeGreaterThan(3);
    const store = await synthStore(sc, identity);
    expect(store.domain).toMatch(/\.(example|test|invalid)$/);
    console.log(JSON.stringify({ identity, store }, null, 2));
  });
});
