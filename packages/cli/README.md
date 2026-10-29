# @shop-gym/cli

`shopgym` is the single command-line entry point for ShopGym: storefront
exploration, shop generation, hosting published shops, ShopGuru benchmarks,
trajectory inspection and an environment check.

```bash
pnpm -r build                          # produces packages/cli/dist/main.js
node packages/cli/dist/main.js --help  # every `shopgym <cmd>` below is run this way
```

Every subcommand prints progress to stderr (one line per event) and reserves
stdout for its result (a path, URL or number), so output can be piped.
Expected failures (bad flags, missing files, invalid configs) are reported as a
single `shopgym <cmd>: <message>` line with exit code 1.

Credentials are read from `<repoRoot>/.env` and the shell environment; the
repository root is the nearest ancestor of the current directory that contains
`pnpm-workspace.yaml`. The default model is `openai/gpt-5.5`; pass `--model
<provider>/<id>` to override. The `gen` build agent is the exception: see below.

## Subcommands

### `shopgym explore <url>`

Explores a live storefront and writes a shop manual.

```
shopgym explore <url> [--out <dir>] [--model <ref>] [--max-iters <n>]
                      [--timeout <ms>] [--from <step>] [--force-resume]
```

`--from` must be one of `prefetch`, `explore`, `merge`, `synthesize`. Prints the
manual path on stdout; exits 1 when the run does not finish with status
`completed`.

### `shopgym gen <manual_dir>... --name <name>`

Generates a SandboxShop from one or more shop manuals.

```
shopgym gen <manual_dir>... --name <name> [--out <dir>] [--gen-backend]
            [--from <step>] [--model <ref>] [--build-model <ref>]
            [--image-backend placeholder|openai] [--max-iters <n>]
            [--collections <n>] [--products-per-collection <n>]
            [--images-per-product <n>] [--concurrency <n>] [--force-resume]
```

`--from` must be one of `manual_merge`, `data_synth`, `data_validation`,
`build`, `final_eval`, `publish`. `--model` drives data synthesis, manual merge
and the judges. The build agent runs on `--build-model`, default
`openai/gpt-6-sol`, also when `--model` is set. Prints the published shop
directory on stdout.

### `shopgym host start|stop|restart|list`

Hosts a published shop (`outputs/shops/<name>/` or any directory containing
`shop.json`): the `shop_backend` GraphQL server over `<shop>/data/` plus the
storefront wired to it, both detached.

```
shopgym host start <shop> [port] [--force]   # storefront on [port] or a free port
shopgym host stop <shop>|all
shopgym host restart <shop>                  # stop + start on the same storefront port
shopgym host list [-a|--all]                 # running shops; -a adds published ones
```

- `start` refuses a shop whose `shop.json` does not record
  `finalStatus: completed` unless `--force` is given, refuses a bound port, and
  refuses a shop that is already tracked (use `restart`).
- The first start runs `pnpm install --ignore-workspace` and `pnpm build` in
  `<shop>/backend/` and `<shop>/storefront/`; later starts skip both while the
  recorded template content hashes and `publishedAt` still match `shop.json`.
- The storefront is launched with `NODE_ENV=production`, `PORT`,
  `PUBLIC_STORE_DOMAIN` / `SHOP_BACKEND_URL` (the backend URL) and a random
  `SESSION_SECRET` unless one is set in the environment.
- `stop` sends SIGTERM to each process group, SIGKILL after 3 s, and removes
  the state file. `list` reports `running`, `partial` (one process died),
  `dead` or `available`.

State lives under `<repoRoot>/.run/shops/<name>/`:

```
.run/shops/<name>/
  state.json       # {name, shopDir, startedAt, backend: {pid, port, url, logPath}, storefront: {...}}
  build.json       # {publishedAt, storefront: <contentHash>, backend: <contentHash>} of the last build
  build.log        # pnpm install / pnpm build output
  backend.log      # shop_backend stdout+stderr
  storefront.log   # storefront stdout+stderr
```

`pnpm shop:host ...` at the repository root is an alias for `shopgym host ...`.

### `shopgym guru build|explore|solve|eval --config <path>`

Runs one ShopGuru stage with the given config file.

```
shopgym guru <stage> --config <path> [--shop <name>] [--skills a,b]
             [--model <ref>] [--judge-model <ref>] [--concurrency <n>]
             [--headless|--no-headless]
```

Flags override the corresponding config fields. stdout carries the benchmarks
directory (`build`), the explore output directory (`explore`), the run
directory (`solve`), or the run directory followed by the pass rate (`eval`).

### `shopgym trace <iter_dir> [--full]`

Renders `trajectory.json` (and `metadata.json` when present) from a harness
iteration directory as plain text. Long payloads are clipped unless `--full`.

### `shopgym doctor`

Checks Node (>= 20.12), pnpm, Playwright's Chromium, both templates and the
credentials found in `.env` / the environment. Only key names are printed,
never values. Exits 1 when any check fails and prints a remedy per failure.

## Development

```bash
pnpm --filter @shop-gym/cli build
pnpm --filter @shop-gym/cli test                       # unit tests, no network
SHOPGYM_SLOW_TESTS=1 pnpm --filter @shop-gym/cli test  # also publishes and hosts a fixture shop
```
