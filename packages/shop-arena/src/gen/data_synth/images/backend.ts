/**
 * Product image backends. `placeholder` renders deterministic PNGs offline;
 * `openai` calls the Images API with a content-hash cache so re-runs never
 * pay for the same prompt twice.
 */

import type { Credentials } from '@shop-gym/core';

import { OpenAiImageBackend } from './openai.js';
import { PlaceholderImageBackend } from './placeholder.js';

export interface ImageRequest {
  readonly handle: string;
  /** 0-based image index within the product. */
  readonly index: number;
  readonly title: string;
  /** Product type or collection title; drives the placeholder palette. */
  readonly category: string;
  readonly width: number;
  readonly height: number;
}

export interface ImageBackend {
  readonly name: string;
  /** File extension including the dot (`.png`). */
  readonly extension: string;
  render(request: ImageRequest, signal: AbortSignal): Promise<Uint8Array>;
}

export type ImageBackendName = 'placeholder' | 'openai';

export interface ImageBackendOptions {
  readonly cacheDir: string;
  readonly credentials: Credentials;
  readonly fetch: typeof fetch;
}

export function createImageBackend(
  name: ImageBackendName,
  options: ImageBackendOptions,
): ImageBackend {
  switch (name) {
    case 'placeholder':
      return new PlaceholderImageBackend();
    case 'openai':
      return new OpenAiImageBackend(options);
  }
}
