import { createServer as createHttpServer } from 'node:http';
import { createYoga } from 'graphql-yoga';
import { createSandboxSchema } from './schema.js';

export interface ServerOptions {
  port?: number;
  host?: string;
}

/**
 * Creates an HTTP server that exposes the ShopBackend GraphQL endpoint at `/graphql`.
 */
export function createServer(options: ServerOptions = {}) {
  const { port = 4000, host = '127.0.0.1' } = options;
  const yoga = createYoga({ schema: createSandboxSchema(), graphqlEndpoint: '/graphql' });
  const http = createHttpServer(yoga);

  return {
    listen: () =>
      new Promise<void>((resolve) => {
        http.listen(port, host, () => resolve());
      }),
    close: () =>
      new Promise<void>((resolve, reject) => {
        http.close((err) => (err ? reject(err) : resolve()));
      }),
    url: `http://${host}:${port}/graphql`,
  };
}
