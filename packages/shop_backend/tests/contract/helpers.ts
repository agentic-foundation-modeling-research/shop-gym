/**
 * Shared scaffolding for the contract suite: one server per test file over
 * the committed fixture, plain GraphQL POSTs. Read-only tests send no
 * episode header; stateful tests pass an episode id and read the episode's
 * StateSnapshot through the Control API.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadShopData } from '../../src/data/loader.js';
import { EPISODE_HEADER } from '../../src/sandbox/episode.js';
import { type StateSnapshot, stateSnapshotSchema } from '../../src/sandbox/snapshot.js';
import { type SandboxServer, createSandboxServer } from '../../src/server.js';

export const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../fixtures/sandbox_shop_v0',
);

export interface GraphQLResponse<T> {
  readonly data?: T;
  readonly errors?: readonly unknown[];
}

export interface ContractServer {
  readonly server: SandboxServer;
  /** POST `source`; `episode` selects an isolated episode via the episode header. */
  query<T>(source: string, episode?: string): Promise<GraphQLResponse<T>>;
  /** The validated StateSnapshot of `episode`, read through the Control API. */
  snapshot(episode: string): Promise<StateSnapshot>;
}

/** Start a server over the Dataset in `dataDir`, the committed fixture by default. */
export async function startContractServer(dataDir = FIXTURE_DIR): Promise<ContractServer> {
  const server = createSandboxServer({
    data: loadShopData(dataDir),
    dataDir,
    port: 0,
  });
  await server.listen();
  const baseUrl = server.url.replace(/\/graphql$/, '');
  return {
    server,
    async query<T>(source: string, episode?: string): Promise<GraphQLResponse<T>> {
      const headers: Record<string, string> = { 'content-type': 'application/json' };
      if (episode !== undefined) headers[EPISODE_HEADER] = episode;
      const response = await fetch(server.url, {
        method: 'POST',
        headers,
        body: JSON.stringify({ query: source }),
      });
      return (await response.json()) as GraphQLResponse<T>;
    },
    async snapshot(episode: string): Promise<StateSnapshot> {
      const response = await fetch(`${baseUrl}/__shopgym/episodes/${episode}/state`);
      if (response.status !== 200) {
        throw new Error(`GET state for episode ${episode} answered ${response.status}`);
      }
      return stateSnapshotSchema.parse(await response.json());
    },
  };
}
