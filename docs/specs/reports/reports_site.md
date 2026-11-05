# Review Reports Site

## Overview

`@shop-gym/reports` is a small local website for Review reports: HTML pages
that we make from Markdown work in `docs/` so that teammates can review it. The
package holds the committed reports, one shared stylesheet and theme script,
and a server that shows an index and each report inside one site shell.
`shopgym report` (alias `pnpm reports`) runs it.

The usual flow:

```
docs/*.md  --(builder, outside the repo)-->  packages/reports/pages/<date>-<slug>.html
                                                         |
                                                   shopgym report
                                                         |
                                     review with teammates in the browser
                                                         |
                       decisions go back into docs/*.md (specs, ADRs, GLOSSARY.md)
```

## Terminology

- **Review report** - an HTML page made from Markdown work for review. See
  `GLOSSARY.md`.
- **Report fragment** - the committed form of a report: a head block of
  `<title>` and `<meta>` tags, then the report body. It has no doctype and no
  `<html>`, `<head>` or `<body>` tags.
- **Site shell** - the document that the server writes around every page: the
  doctype, fonts, `assets/report.css`, `assets/theme.js` and the top bar.

## Current Status

Implemented in `packages/reports` and `packages/cli/src/commands/report.ts`:

- `catalog.ts`: `REPORT_FILE_RE`, `parseReport`, `readReport`, `listReports`
  and `ReportFormatError`.
- `shell.ts`: the site shell, the index page and the not-found page.
- `server.ts`: `createReportServer({pagesDir?, assetsDir?, port?, host?})`,
  default `127.0.0.1:4100`.
- `assets/report.css` and `assets/theme.js`: the tokens, components and the
  System / Light / Dark switch.
- Two reports in `pages/`: the Source bundles spec review and the shopping
  dataset survey.
- Tests: the catalog and the server against temporary directories, and a check
  that every committed report follows the format.

## Desired Status

Unchanged from the current status. New reports are new files in `pages/`; the
package itself changes only when the shared style needs a new component.

## Proposal

### Report format

- The file name is `YYYY-MM-DD-<slug>.html`, with a lowercase kebab-case slug.
  The date sorts the index, newest first; reports with the same date sort by
  file name.
- The file starts with a head block: a non-empty `<title>` and a non-empty
  `<meta name="description">`, in any order, with optional other `<meta>`
  tags. Only this leading block is read, so an SVG `<title>` in the body is
  not taken as the report title.
- Everything after the head block is the body. It holds the report's own
  `<style>`, markup and `<script>`, and it uses the shared tokens for every
  color, so both themes work.
- A report is self-contained: inline SVG or `data:` URIs, no external
  scripts. Browser storage calls are wrapped in `try`/`catch`.

### Server

| Request | Response |
| ------- | -------- |
| `GET /` | the index: title, date and description of every report |
| `GET /<YYYY-MM-DD-slug>.html` | the report body inside the site shell |
| `GET /assets/<name>` with `.css`, `.js`, `.svg` or `.png` | the asset |
| a report that breaks the format | 500, text that names the file and the problem |
| any other path | 404 page |
| a method other than `GET` | 405 with `allow: GET` |

Rules:

- A path is matched against the report name pattern or the asset pattern
  before any file access. Neither pattern allows `/` or `..` in the name, so a
  request cannot read a file outside `pages/` and `assets/`.
- Files are read on each request: an edited report shows on reload, and there
  is no cache (`cache-control: no-store`).
- The server binds to `127.0.0.1` by default. `--host 0.0.0.0` shares it on
  the local network.

### Shared style

`assets/report.css` defines color tokens (`--bg`, `--surface`, `--ink`,
`--muted`, `--line`, `--accent`, `--ok`, `--warn`, `--bad` and their soft
backgrounds), eight chart series tokens (`--series-1` to `--series-8`), font
tokens (`--head` Schibsted Grotesk, `--sans` IBM Plex Sans, `--mono` IBM Plex
Mono), and layout and component classes (`.shell`, `.toc`, `.hero`,
`section`, `.card`, `.prose`, `.table-wrap`, `.chip`, `.note`, `.btn`,
`.seg`). The dark values are defined twice, under
`prefers-color-scheme: dark` without `data-theme="light"`, and under
`data-theme="dark"`, so the theme switch wins in both directions.

`assets/theme.js` cycles System, Light and Dark, stores the choice in
`localStorage` when it can, and sets `data-theme` on the root element before
the first paint.

## Alternative

- Full HTML documents under `docs/reports/`: rejected, see ADR 0017.
- A static site generator over the Markdown: rejected, because report pages
  differ too much (a review form with stored marks, a survey with charts) for
  one template, and the builders change with each report.

## Execution Table

| # | Item | Status |
| - | ---- | ------ |
| 1 | Catalog: file name pattern, head block parser, list and read | done |
| 2 | Site shell, index page, not-found page | done |
| 3 | Server with strict path patterns and fresh reads | done |
| 4 | Shared stylesheet and theme switch | done |
| 5 | `shopgym report` and `pnpm reports` | done |
| 6 | Move the Source bundles review and the dataset survey into `pages/` | done |
| 7 | Move the task generation review from `docs/reports/` (PR #55) into `pages/` | open |

## Appendix

Commands:

```bash
pnpm -r build
pnpm reports                          # http://127.0.0.1:4100
pnpm reports --port 8100 --host 0.0.0.0
pnpm --filter @shop-gym/reports test
```

The package uses only Node built-ins (`node:http`, `node:fs/promises`). Fonts
load from Google Fonts; without a network the pages fall back to system
fonts.
