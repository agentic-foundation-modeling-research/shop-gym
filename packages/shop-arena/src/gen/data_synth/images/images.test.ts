import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { ImageRequest } from './backend.js';
import { ImageGenerationError, OpenAiImageBackend } from './openai.js';
import { PlaceholderImageBackend, renderPlaceholder } from './placeholder.js';

const REQUEST: ImageRequest = {
  handle: 'oak-bowl',
  index: 0,
  title: 'Oak Bowl',
  category: 'Bowl',
  width: 64,
  height: 64,
};
const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

describe('placeholder backend', () => {
  it('renders the same PNG for the same request and differs per index', async () => {
    const a = renderPlaceholder(REQUEST);
    expect(a.subarray(0, 8).equals(PNG_MAGIC)).toBe(true);
    expect(renderPlaceholder(REQUEST).equals(a)).toBe(true);
    expect(renderPlaceholder({ ...REQUEST, index: 1 }).equals(a)).toBe(false);
    const backend = new PlaceholderImageBackend();
    expect(backend.extension).toBe('.png');
    expect(Buffer.from(await backend.render(REQUEST)).equals(a)).toBe(true);
  });
});

describe('openai backend', () => {
  let cacheDir: string;
  beforeEach(async () => {
    cacheDir = await fs.mkdtemp(path.join(os.tmpdir(), 'image-cache-'));
  });
  afterEach(async () => {
    await fs.rm(cacheDir, { recursive: true, force: true });
  });

  it('posts the images request with the credentials and caches by content hash', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const bytes = Buffer.from('fake-png');
    const fakeFetch: typeof fetch = async (input, init) => {
      calls.push({ url: String(input), init: init ?? {} });
      return new Response(JSON.stringify({ data: [{ b64_json: bytes.toString('base64') }] }), {
        status: 200,
      });
    };
    const backend = new OpenAiImageBackend({
      cacheDir,
      credentials: { openaiApiKey: 'test-key', openaiBaseUrl: 'https://images.example/v1' },
      fetch: fakeFetch,
    });
    const first = await backend.render(REQUEST, new AbortController().signal);
    expect(Buffer.from(first).equals(bytes)).toBe(true);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe('https://images.example/v1/images/generations');
    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(headers.authorization).toBe('Bearer test-key');
    const body = JSON.parse(String(calls[0]?.init.body)) as Record<string, unknown>;
    expect(body.n).toBe(1);
    expect(String(body.prompt)).toContain('Oak Bowl');
    expect(body.model).toBeTypeOf('string');
    await backend.render(REQUEST, new AbortController().signal);
    expect(calls).toHaveLength(1);
    expect((await fs.readdir(cacheDir)).length).toBe(1);
  });

  it('fails fast without an API key', async () => {
    const backend = new OpenAiImageBackend({ cacheDir, credentials: {}, fetch });
    await expect(backend.render(REQUEST, new AbortController().signal)).rejects.toBeInstanceOf(
      ImageGenerationError,
    );
  });
});
