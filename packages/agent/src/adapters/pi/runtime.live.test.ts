/**
 * Live conformance of the pi adapter. Needs credentials and network, so it
 * only runs with `SHOPGYM_LIVE=1`. Model defaults to openai/gpt-5.5; override
 * with `SHOPGYM_LIVE_MODEL=<provider>/<id>`.
 */

import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadCredentials } from '@shop-gym/core';
import { beforeAll, describe, expect, it } from 'vitest';

import { z } from 'zod';
import { completeJson } from '../../llm.js';
import { conformanceCases } from '../../testing/conformance.js';
import { PiLlmClient } from './llm.js';
import { PiRuntime } from './runtime.js';

const LIVE = process.env.SHOPGYM_LIVE === '1';
const REPO_ROOT = fileURLToPath(new URL('../../../../..', import.meta.url));
const [provider = 'openai', id = 'gpt-5.5'] = (
  process.env.SHOPGYM_LIVE_MODEL ?? 'openai/gpt-5.5'
).split('/', 2);
const MODEL = { provider, id };

describe.skipIf(!LIVE)('PiRuntime (live)', () => {
  let cwd: string;
  let runtime: PiRuntime;
  beforeAll(async () => {
    cwd = await fs.mkdtemp(path.join(os.tmpdir(), 'pi-live-'));
    runtime = new PiRuntime({ credentials: loadCredentials(REPO_ROOT, process.env) });
  });

  for (const conformanceCase of conformanceCases) {
    it(conformanceCase.name, { timeout: 120_000 }, () =>
      conformanceCase.run({ cwd, model: MODEL, runtime: () => runtime }),
    );
  }

  it('writes events.jsonl into logDir', { timeout: 120_000 }, async () => {
    const logDir = path.join(cwd, 'log');
    const result = await runtime.run({
      cwd,
      systemPrompt: 'You are a test agent.',
      prompt: 'Reply with the word OK.',
      tools: [],
      model: MODEL,
      signal: new AbortController().signal,
      logDir,
    });
    expect(result.status).toBe('completed');
    const events = await fs.readFile(path.join(logDir, 'events.jsonl'), 'utf-8');
    expect(events).toContain('"message_end"');
  });
});

describe.skipIf(!LIVE)('PiLlmClient (live)', () => {
  it('completes JSON constrained by a schema', { timeout: 120_000 }, async () => {
    const client = new PiLlmClient({ credentials: loadCredentials(REPO_ROOT, process.env) });
    const { value, completion } = await completeJson(
      client,
      { model: MODEL, prompt: 'What is 2 + 2? Put the number in "answer".' },
      z.object({ answer: z.number() }),
    );
    expect(value.answer).toBe(4);
    expect(completion.usage.output).toBeGreaterThan(0);
  });
});
