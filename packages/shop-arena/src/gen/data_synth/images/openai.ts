/**
 * OpenAI Images API backend with a content-hash byte cache. The cache key
 * covers the rendered prompt, model, size, quality, and prompt version, so
 * a changed prompt file invalidates it while re-runs reuse it.
 */

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { renderPlaceholders } from '../../build/prompts.js';
import { exists, writeBytes } from '../../io.js';
import type { ImageBackend, ImageBackendOptions, ImageRequest } from './backend.js';

const PROMPTS_DIR = fileURLToPath(new URL('../prompts/', import.meta.url));
const PROMPT_VERSION = 1;
const DEFAULT_BASE_URL = 'https://api.openai.com/v1';
const DEFAULT_MODEL = 'gpt-image-1';
const DEFAULT_SIZE = '1024x1024';
const DEFAULT_QUALITY = 'medium';
const RETRY_DELAYS_MS = [1_000, 4_000];

export class ImageGenerationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ImageGenerationError';
  }
}

export interface OpenAiImageOptions extends ImageBackendOptions {
  readonly model?: string;
  readonly size?: string;
  readonly quality?: string;
}

/** Fills `image.md` for one product. */
export function renderImagePrompt(title: string, category: string): string {
  const template = readFileSync(path.join(PROMPTS_DIR, 'image.md'), 'utf-8');
  return renderPlaceholders(template, { title, category }).trim();
}

export class OpenAiImageBackend implements ImageBackend {
  readonly name = 'openai';
  readonly extension = '.png';
  private readonly options: OpenAiImageOptions;

  constructor(options: OpenAiImageOptions) {
    this.options = options;
  }

  async render(request: ImageRequest, signal: AbortSignal): Promise<Uint8Array> {
    const prompt = renderImagePrompt(request.title, request.category);
    const model = this.options.model ?? DEFAULT_MODEL;
    const size = this.options.size ?? DEFAULT_SIZE;
    const quality = this.options.quality ?? DEFAULT_QUALITY;
    const key = createHash('sha256')
      .update(JSON.stringify({ prompt, model, size, quality, promptVersion: PROMPT_VERSION }))
      .digest('hex');
    const cached = path.join(this.options.cacheDir, `${key}.png`);
    if (await exists(cached)) {
      return fs.readFile(cached);
    }
    const bytes = await this.generate({ model, prompt, size, quality, n: 1 }, signal);
    await writeBytes(cached, bytes);
    return bytes;
  }

  private async generate(body: Record<string, unknown>, signal: AbortSignal): Promise<Buffer> {
    const apiKey = this.options.credentials.openaiApiKey;
    if (apiKey === undefined) {
      throw new ImageGenerationError(
        'OPENAI_API_KEY is not set; use imageBackend "placeholder" or add it to .env',
      );
    }
    const url = `${(this.options.credentials.openaiBaseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, '')}/images/generations`;
    let lastError = 'no attempt made';
    for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt += 1) {
      if (attempt > 0) {
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS_MS[attempt - 1]));
      }
      let response: Response;
      try {
        response = await this.options.fetch(url, {
          method: 'POST',
          headers: { 'content-type': 'application/json', authorization: `Bearer ${apiKey}` },
          body: JSON.stringify(body),
          signal,
        });
      } catch (err) {
        if (signal.aborted) throw err;
        lastError = `network error: ${err instanceof Error ? err.message : String(err)}`;
        continue;
      }
      if (response.status === 429 || response.status >= 500) {
        lastError = `HTTP ${response.status}`;
        continue;
      }
      if (!response.ok) {
        throw new ImageGenerationError(
          `images/generations failed: HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`,
        );
      }
      const payload = (await response.json()) as { data?: { b64_json?: string }[] };
      const b64 = payload.data?.[0]?.b64_json;
      if (b64 === undefined) {
        throw new ImageGenerationError('images/generations reply has no data[0].b64_json');
      }
      return Buffer.from(b64, 'base64');
    }
    throw new ImageGenerationError(`images/generations failed after retries: ${lastError}`);
  }
}
