/**
 * Default pi-backed dependencies for the pipeline stages. Credentials come
 * from `loadCredentials` and never leave memory.
 */

import { PiLlmClient, PiRuntime } from '@shop-gym/agent';
import type { Credentials } from '@shop-gym/core';

import type { GuruConfig } from './config.js';
import type { Judge } from './grade/grade.js';
import { type AgentUnderTest, RuntimeBrowserAgent } from './solve/agent.js';

/** The reference agent under test: pi runtime over the UI-only browser tools. */
export function createPiBrowserAgent(config: GuruConfig, credentials: Credentials): AgentUnderTest {
  return new RuntimeBrowserAgent({
    runtime: new PiRuntime({ credentials }),
    model: config.model,
    name: 'pi-browser',
  });
}

/** Judge backed by pi's single-shot client, on `judgeModel` or `model`. */
export function createPiJudge(config: GuruConfig, credentials: Credentials): Judge {
  return { client: new PiLlmClient({ credentials }), model: config.judgeModel ?? config.model };
}
