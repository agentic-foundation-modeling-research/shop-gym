#!/usr/bin/env node
import { createServer } from './server.js';

async function main(): Promise<void> {
  const port = Number(process.env.PORT ?? 4000);
  const server = createServer({ port });
  await server.listen();
  // biome-ignore lint/suspicious/noConsoleLog: CLI needs to output server URL
  console.log(`shop-backend listening at ${server.url}`);
}

main().catch((err: unknown) => {
  // biome-ignore lint/suspicious/noConsoleLog: CLI error handler
  console.error(err);
  process.exit(1);
});
