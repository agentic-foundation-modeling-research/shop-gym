#!/usr/bin/env node
import { loadShopData } from './data/loader.js';
import { createSandboxServer } from './server.js';

const USAGE = 'Usage: shop-backend <data-dir> [port]';

async function main(): Promise<void> {
  const [dataDir, portArg] = process.argv.slice(2);
  if (dataDir === undefined) {
    console.error(USAGE);
    process.exit(1);
  }

  const port = portArg !== undefined ? Number(portArg) : Number(process.env.PORT ?? 4000);
  if (!Number.isFinite(port)) {
    console.error(`Invalid port: '${portArg}'`);
    process.exit(1);
  }

  const data = loadShopData(dataDir);
  console.log(
    `Loaded SandboxShop '${data.store.name}' from ${dataDir}: ` +
      `${data.products.length} products, ${data.collections.length} collections, ` +
      `${data.pages.length} pages, ${data.blogs.length} blogs, ${data.policies.length} policies`,
  );

  const server = createSandboxServer({ data, dataDir, port });
  await server.listen();
  console.log(`shop-backend listening at ${server.url}`);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
