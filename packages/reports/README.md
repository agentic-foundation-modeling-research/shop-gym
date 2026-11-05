# @shop-gym/reports

A small local website for the HTML reports we review with teammates. It serves
an index of every report and shows each report inside one shared site shell, so
all reports have the same fonts, colors, top bar and light / dark theme.

Reports and Markdown docs do different jobs:

- `docs/` holds the Markdown: plans, specs, ADRs, proposals and final designs.
- `packages/reports/pages/` holds the HTML that we make from that Markdown for
  a review. After the review, the decisions go back into the Markdown in
  `docs/`.

The scripts that build a report stay outside the repository. This package only
serves the finished HTML.

```bash
pnpm -r build
pnpm reports                     # -> http://127.0.0.1:4100
pnpm reports --port 8100         # another port
pnpm reports --host 0.0.0.0      # share it on the local network
pnpm --filter @shop-gym/reports test
```

The server reads files on each request, so an edited report shows when you
reload the page. Only `GET` is allowed, and only report files and the files in
`assets/` are served.

## Add a report

1. Name the file `YYYY-MM-DD-<slug>.html` (lowercase letters, digits and
   hyphens) and put it in `pages/`. The date sorts the index, newest first.
2. Write an HTML fragment, not a full document: no doctype and no `<html>`,
   `<head>` or `<body>` tags. The file starts with its head block, a `<title>`
   and a `<meta name="description">`. The index shows both.
3. Put the report's own `<style>`, markup and `<script>` after the head block.
4. Keep the report self-contained: inline SVG or `data:` URIs for images, no
   external scripts.

```html
<title>Shopping Dataset Survey</title>
<meta name="description" content="What the public shopping datasets contain, with one real record from each.">
<style>
  .bars rect { fill: var(--series-1); }
</style>
<div class="shell">
  <nav class="toc">...</nav>
  <main>
    <header class="hero">...</header>
    <section id="coverage">...</section>
  </main>
</div>
```

The shell adds the doctype, the fonts, `assets/report.css`, `assets/theme.js`,
and the top bar with the site name, the report date and the theme switch. A
file that breaks these rules gets a 500 page that names the file and the
problem, and `src/pages.test.ts` fails on it.

## Shared style

`assets/report.css` defines the tokens and the components. Use them in report
styles instead of literal colors, so a report works in both themes:

- Colors: `--bg`, `--surface`, `--surface-2`, `--ink`, `--muted`, `--faint`,
  `--line`, `--line-strong`, `--grid`, `--accent`, `--ok`, `--warn`, `--bad`
  (each status color also has a `-soft` background), `--code`.
- Chart series, in this order: `--series-1` to `--series-8`.
- Fonts: `--head`, `--sans`, `--mono`.
- Layout: `.shell` (one column, or a `.toc` beside `main`), `.hero`, `.lede`,
  `section`, `.sec-head`, `.card`, `.grid`, `.tiles`, `.prose` for rendered
  Markdown, `.table-wrap` for wide tables.
- Small parts: `.chip` (`.accent`, `.ok`, `.warn`, `.bad`), `.note` (`.info`,
  `.ok`, `.bad`), `.btn` (`.primary`), `.seg`, `.kicker`, `.legend`,
  `.swatch`.

A report that keeps state in the browser (for example review marks) must wrap
every `localStorage` call in `try`/`catch`, because storage can be blocked.
