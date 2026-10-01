/**
 * Shared scaffolding for the read-only contract suite: one server per test
 * file over the committed fixture, no episode header, plain GraphQL POSTs.
 */

import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadShopData } from '../../src/data/loader.js';
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
  query<T>(source: string): Promise<GraphQLResponse<T>>;
}

export async function startContractServer(): Promise<ContractServer> {
  const server = createSandboxServer({
    data: loadShopData(FIXTURE_DIR),
    dataDir: FIXTURE_DIR,
    port: 0,
  });
  await server.listen();
  return {
    server,
    async query<T>(source: string): Promise<GraphQLResponse<T>> {
      const response = await fetch(server.url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ query: source }),
      });
      return (await response.json()) as GraphQLResponse<T>;
    },
  };
}
