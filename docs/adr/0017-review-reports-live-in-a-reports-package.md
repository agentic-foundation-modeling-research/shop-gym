# Review reports live in `packages/reports`, and `docs/` keeps only Markdown

We review plans, specs and proposals with teammates as interactive HTML pages, but the record of a decision is the Markdown in `docs/`. The two have different jobs, so they live in different places: Review reports are committed as HTML fragments in `packages/reports/pages/`, and the `@shop-gym/reports` package serves them with an index and one shared style (`shopgym report`, alias `pnpm reports`). `docs/` keeps Markdown, plus the images that the Markdown uses. The scripts that build a report stay outside the repository; the package only serves finished HTML.

## Considered Options

- Commit full HTML documents under `docs/reports/`: each report then carries its own fonts, colors and theme code, so reports drift apart in style, and `docs/` mixes the record with pages that go out of date after the review.
- Host reports outside the repository (a Quick site or Artifacts): reviewers need a login or a link that someone must keep current, and the report is not versioned next to the Markdown it shows.
- Build reports from Markdown inside the repository: one generator cannot cover pages as different as a review form and a dataset survey, and the builders change with each report.

## Consequences

- A report file is a fragment: a `<title>` and a `<meta name="description">` first, then its own styles, markup and scripts. The site shell adds the document, the shared stylesheet, the theme switch and the top bar. A full document, or a file without these two head tags, is rejected.
- Report styles use the shared tokens, so every report has light and dark themes. A change to a token or a shared component changes all reports; check each report after such a change.
- `cli` gets one more dependency, `@shop-gym/reports`, which has no workspace dependencies of its own. The layering of ADR 0002 still holds.
- A report is not kept up to date after its review. When the Markdown changes later, the Markdown wins.
