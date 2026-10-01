import { describe, expect, it } from 'vitest';
import { z } from 'zod';

import {
  type CompleteRequest,
  type Completion,
  type LlmClient,
  LlmJsonError,
  completeJson,
  extractJson,
} from './llm.js';

const USAGE = { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, costUsd: 0 };

class ScriptedClient implements LlmClient {
  readonly requests: CompleteRequest[] = [];
  constructor(private readonly replies: string[]) {}
  async complete(request: CompleteRequest): Promise<Completion> {
    this.requests.push(request);
    const text = this.replies.shift();
    if (text === undefined) {
      throw new Error('no reply scripted');
    }
    return { text, model: 'm', stopReason: 'stop', usage: USAGE };
  }
}

const request: CompleteRequest = {
  model: { provider: 'openai', id: 'gpt-5.5' },
  prompt: 'rate it',
};

describe('extractJson', () => {
  it('parses bare JSON', () => {
    expect(extractJson('{"a": 1}')).toEqual({ a: 1 });
  });

  it('parses a fenced block with a language tag', () => {
    expect(extractJson('Sure:\n```json\n[1, 2]\n```\n')).toEqual([1, 2]);
  });

  it('skips prose before the value', () => {
    expect(extractJson('Here you go: {"ok": true}')).toEqual({ ok: true });
  });

  it('raises LlmJsonError with the raw text when nothing parses', () => {
    expect(() => extractJson('nope')).toThrow(LlmJsonError);
  });
});

describe('completeJson', () => {
  const schema = z.object({ score: z.number().int().min(0).max(10) });

  it('appends the JSON schema to the prompt and validates the reply', async () => {
    const client = new ScriptedClient(['{"score": 7}']);
    const { value, completion } = await completeJson(client, request, schema);
    expect(value).toEqual({ score: 7 });
    expect(completion.usage).toEqual(USAGE);
    const sent = client.requests[0]?.prompt;
    expect(typeof sent === 'string' && sent.startsWith('rate it\n\n')).toBe(true);
    expect(sent).toContain('"score"');
  });

  it('keeps image attachments when the prompt has content', async () => {
    const client = new ScriptedClient(['{"score": 1}']);
    const images = [{ data: 'AAAA', mimeType: 'image/png' }];
    await completeJson(client, { ...request, prompt: { text: 'look', images } }, schema);
    const sent = client.requests[0]?.prompt;
    expect(typeof sent === 'object' && sent.images).toEqual(images);
  });

  it('raises LlmJsonError when the reply violates the schema', async () => {
    const client = new ScriptedClient(['{"score": 42}']);
    await expect(completeJson(client, request, schema)).rejects.toBeInstanceOf(LlmJsonError);
  });
});
