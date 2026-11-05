/**
 * The site shell: the full HTML document around each report fragment, plus
 * the index and not-found pages. Every page loads the shared
 * `/assets/report.css` and `/assets/theme.js`, so all reports share one style
 * and one light / dark / system theme switch.
 */

import type { Report } from './catalog.js';

const FONTS_URL =
  'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500' +
  '&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400' +
  '&family=Schibsted+Grotesk:wght@500;600;700&display=swap';

interface ShellParts {
  /** Plain text. */
  readonly title: string;
  /** Plain text. */
  readonly description: string;
  /** HTML shown after the site name in the top bar. */
  readonly crumb: string;
  /** HTML placed after the top bar. */
  readonly content: string;
}

/** The full document for one report: the shell around the report body. */
export function renderReportPage(report: Report): string {
  return shell({
    title: report.title,
    description: report.description,
    crumb: `<time class="site-crumb" datetime="${report.date}">${report.date}</time>`,
    content: report.body,
  });
}

/** The index page: every report, in the order given. */
export function renderIndexPage(entries: readonly Report[]): string {
  const list =
    entries.length === 0
      ? '<p class="site-empty">No reports yet. Add <code>YYYY-MM-DD-&lt;slug&gt;.html</code> to <code>packages/reports/pages/</code>.</p>'
      : `<ol class="site-list">\n${entries.map(renderEntry).join('\n')}\n</ol>`;
  return shell({
    title: 'ShopGym Reports',
    description: 'HTML reports for review with the ShopGym team.',
    crumb: '',
    content: `<main class="site-main">
<header class="site-head">
  <h1>Reports</h1>
  <p class="site-lede">Pages for review with teammates. Each report shows Markdown work from <code>docs/</code>. After the review, the decisions go back into those Markdown files.</p>
  <p class="site-count">${entries.length} ${entries.length === 1 ? 'report' : 'reports'}, newest first</p>
</header>
${list}
</main>`,
  });
}

/** The 404 page for `pathname`. */
export function renderNotFoundPage(pathname: string): string {
  return shell({
    title: 'Not found - ShopGym Reports',
    description: 'No report at this address.',
    crumb: '',
    content: `<main class="site-main">
<header class="site-head">
  <h1>Not found</h1>
  <p class="site-lede">No report at <code>${escapeHtml(pathname)}</code>. <a href="/">See all reports</a>.</p>
</header>
</main>`,
  });
}

function renderEntry(entry: Report): string {
  return `<li><a class="site-entry" href="/${entry.file}">
  <time datetime="${entry.date}">${entry.date}</time>
  <span class="site-entry-title">${escapeHtml(entry.title)}</span>
  <span class="site-entry-desc">${escapeHtml(entry.description)}</span>
</a></li>`;
}

function shell(parts: ShellParts): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>${escapeHtml(parts.title)}</title>
<meta name="description" content="${escapeHtml(parts.description)}">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<script src="/assets/theme.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="${escapeHtml(FONTS_URL)}">
<link rel="stylesheet" href="/assets/report.css">
</head>
<body>
<header class="site-bar">
  <a class="site-name" href="/">ShopGym Reports</a>
  ${parts.crumb}
  <button type="button" class="site-theme" id="theme-toggle">Theme</button>
</header>
${parts.content}
</body>
</html>
`;
}

function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}
