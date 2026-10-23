/** `LlmClient` backed by pi-ai through an isolated `ModelRuntime`. */

import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import type { UserMessage } from '@earendil-works/pi-ai';
import type { ModelRuntime } from '@earendil-works/pi-coding-agent';
import type { Credentials } from '@shop-gym/core';

import { type CompleteRequest, type Completion, type LlmClient, LlmError } from '../../llm.js';
import { promptText } from '../../types.js';
import { joinText, promptImages, toUsage } from './convert.js';
import { createPiModelRuntime, resolveModel } from './model-runtime.js';

/** Options for `PiLlmClient`. */
export interface PiLlmClientOptions {
  readonly credentials: Credentials;
  /** Directory for pi's `models.json`. Omitted means a fresh temp dir. */
  readonly configDir?: string;
}

/** Single completions through pi-ai with ShopGym's routing and keys. */
export class PiLlmClient implements LlmClient {
  private runtime: Promise<ModelRuntime> | undefined;

  constructor(private readonly options: PiLlmClientOptions) {}

  async complete(request: CompleteRequest): Promise<Completion> {
    const runtime = await this.modelRuntime();
    const model = resolveModel(runtime, request.model);
    const images = promptImages(request.prompt);
    const user: UserMessage = {
      role: 'user',
      content:
        images.length === 0
          ? promptText(request.prompt)
          : [{ type: 'text', text: promptText(request.prompt) }, ...images],
      timestamp: Date.now(),
    };
    const message = await runtime.completeSimple(
      model,
      {
        ...(request.systemPrompt !== undefined ? { systemPrompt: request.systemPrompt } : {}),
        messages: [user],
      },
      {
        ...(request.signal !== undefined ? { signal: request.signal } : {}),
        ...(request.model.thinking !== undefined && request.model.thinking !== 'off'
          ? { reasoning: request.model.thinking }
          : {}),
      },
    );
    if (message.stopReason === 'error' || message.stopReason === 'aborted') {
      throw new LlmError(message.errorMessage ?? `model stopped with ${message.stopReason}`);
    }
    return {
      text: joinText(message.content),
      model: message.model,
      stopReason: message.stopReason,
      usage: toUsage(message.usage),
    };
  }

  private modelRuntime(): Promise<ModelRuntime> {
    this.runtime ??= (async () => {
      const configDir =
        this.options.configDir ?? (await fs.mkdtemp(path.join(os.tmpdir(), 'shopgym-pi-llm-')));
      return createPiModelRuntime(configDir, this.options.credentials);
    })();
    return this.runtime;
  }
}
