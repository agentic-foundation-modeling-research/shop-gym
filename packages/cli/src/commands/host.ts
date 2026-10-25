/** `shopgym host start|stop|restart|list`: run published shops locally. */

import { flag, parse, parseEnum, parseInteger } from '../args.js';
import { CliError, findRepoRoot } from '../context.js';
import {
  type ShopRow,
  defaultHostDeps,
  listShops,
  restartShop,
  startShop,
  stopAll,
  stopShop,
} from '../host/host.js';

const ACTIONS = ['start', 'stop', 'restart', 'list'] as const;

export type HostAction = (typeof ACTIONS)[number];

export const USAGE = `Usage: shopgym host <action> [args]

Actions:
  start <shop> [port] [--force]   Install/build if needed, then start backend + storefront
  stop <shop>|all                 Stop a shop (or every tracked shop)
  restart <shop>                  Stop, then start again on the same storefront port
  list [-a|--all]                 Running shops; -a adds published shops not running

<shop> is a directory or a name under outputs/shops/. State and logs live in
.run/shops/<name>/. --force hosts a shop whose shop.json final status is not
"completed".`;

export type HostArgs =
  | { readonly help: true }
  | {
      readonly help: false;
      readonly action: 'start';
      readonly shop: string;
      readonly port?: number;
      readonly force: boolean;
    }
  | { readonly help: false; readonly action: 'stop' | 'restart'; readonly shop: string }
  | { readonly help: false; readonly action: 'list'; readonly all: boolean };

export function parseHostArgs(argv: readonly string[]): HostArgs {
  const args = parse(argv, {
    all: { type: 'boolean', short: 'a' },
    force: { type: 'boolean' },
    help: { type: 'boolean', short: 'h' },
  });
  if (flag(args, 'help')) {
    return { help: true };
  }
  const [actionRaw, shop, portRaw, ...extra] = args.positionals;
  if (actionRaw === undefined) {
    throw new CliError(`missing <action>; expected one of ${ACTIONS.join(', ')}`);
  }
  const action = parseEnum('<action>', actionRaw, ACTIONS);
  if (extra.length > 0) {
    throw new CliError(`unexpected argument ${JSON.stringify(extra[0])}`);
  }
  if (action === 'list') {
    if (shop !== undefined) {
      throw new CliError(`unexpected argument ${JSON.stringify(shop)}`);
    }
    return { help: false, action, all: flag(args, 'all') };
  }
  if (shop === undefined) {
    throw new CliError(`missing <shop> for ${action}`);
  }
  if (action === 'start') {
    const port = portRaw === undefined ? undefined : parseInteger('[port]', portRaw);
    return {
      help: false,
      action,
      shop,
      force: flag(args, 'force'),
      ...(port !== undefined ? { port } : {}),
    };
  }
  if (portRaw !== undefined) {
    throw new CliError(`unexpected argument ${JSON.stringify(portRaw)}`);
  }
  return { help: false, action, shop };
}

export async function run(argv: readonly string[]): Promise<number> {
  const args = parseHostArgs(argv);
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  const repoRoot = findRepoRoot();
  switch (args.action) {
    case 'start': {
      const state = await startShop(
        {
          repoRoot,
          shop: args.shop,
          force: args.force,
          ...(args.port !== undefined ? { port: args.port } : {}),
        },
        defaultHostDeps,
      );
      console.log(`${state.name} storefront=${state.storefront.url} backend=${state.backend.url}`);
      return 0;
    }
    case 'stop': {
      if (args.shop === 'all') {
        const names = await stopAll(repoRoot);
        console.log(names.length === 0 ? '(nothing to stop)' : `stopped ${names.join(', ')}`);
        return 0;
      }
      const stopped = await stopShop(repoRoot, args.shop);
      console.log(stopped ? `stopped ${args.shop}` : `${args.shop}: not tracked`);
      return 0;
    }
    case 'restart': {
      const state = await restartShop(repoRoot, args.shop, defaultHostDeps);
      console.log(`${state.name} storefront=${state.storefront.url} backend=${state.backend.url}`);
      return 0;
    }
    case 'list': {
      const rows = await listShops(repoRoot, args.all);
      process.stdout.write(formatTable(rows, args.all));
      return 0;
    }
  }
}

export function formatTable(rows: readonly ShopRow[], all: boolean): string {
  if (rows.length === 0) {
    return all
      ? '(no shops running or published under outputs/shops/)\n'
      : '(no shops running; try: shopgym host list -a)\n';
  }
  const header = {
    name: 'SHOP',
    status: 'STATUS',
    storefrontUrl: 'STOREFRONT',
    backendUrl: 'BACKEND',
    pids: 'PIDS',
  };
  const columns = ['name', 'status', 'storefrontUrl', 'backendUrl', 'pids'] as const;
  const widths = columns.map((c) => Math.max(header[c].length, ...rows.map((r) => r[c].length)));
  const line = (row: Record<(typeof columns)[number], string>) =>
    columns
      .map((c, i) => row[c].padEnd(widths[i] ?? 0))
      .join('  ')
      .trimEnd();
  return `${[line(header), ...rows.map(line)].join('\n')}\n`;
}
