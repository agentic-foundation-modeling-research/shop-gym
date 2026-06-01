#!/usr/bin/env node
import { loadShopData } from './data/loader.js';
import { createSandboxServer } from './server.js';

const USAGE = 'Usage: shop-backend <data-dir> [port] [--cart-store <path>]';

interface ParsedArgs {
  readonly dataDir: string;
  readonly port: number | null;
  readonly cartStorePath: string | undefined;
}

function parseArgs(argv: readonly string[]): ParsedArgs {
  const positional: string[] = [];
  let cartStorePath: string | undefined;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--cart-store') {
      const value = argv[i + 1];
      if (value === undefined) {
        throw new Error(`Missing value for --cart-store. ${USAGE}`);
      }
      cartStorePath = value;
      i += 1;
      continue;
    }
    if (arg?.startsWith('--cart-store=')) {
      cartStorePath = arg.slice('--cart-store='.length);
      continue;
    }
    if (arg !== undefined) {
      positional.push(arg);
    }
  }

  const [dataDir, portArg] = positional;
  if (dataDir === undefined) {
    throw new Error(USAGE);
  }
  const port = portArg === undefined ? null : Number(portArg);
  if (port !== null && !Number.isFinite(port)) {
    throw new Error(`Invalid port: '${portArg}'`);
  }
  return { dataDir, port, cartStorePath };
}

async function main(): Promise<void> {
  let parsed: ParsedArgs;
  try {
    parsed = parseArgs(process.argv.slice(2));
  } catch (err) {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  }

  const port = parsed.port ?? Number(process.env.PORT ?? 4000);
  if (!Number.isFinite(port)) {
    console.error(`Invalid port: '${process.env.PORT}'`);
    process.exit(1);
  }

  const data = loadShopData(parsed.dataDir);
  console.log(
    `Loaded SandboxShop '${data.store.name}' from ${parsed.dataDir}: ` +
      `${data.products.length} products, ${data.collections.length} collections, ` +
      `${data.pages.length} pages, ${data.blogs.length} blogs, ${data.policies.length} policies`,
  );
  if (parsed.cartStorePath !== undefined) {
    console.log(`Cart state persisted at ${parsed.cartStorePath}`);
  }

  const server = createSandboxServer({
    data,
    dataDir: parsed.dataDir,
    port,
    ...(parsed.cartStorePath !== undefined ? { cartStorePath: parsed.cartStorePath } : {}),
  });
  await server.listen();
  console.log(`shop-backend listening at ${server.url}`);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
