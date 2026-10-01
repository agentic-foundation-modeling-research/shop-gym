/**
 * Locations of the templates seeded into every generated shop.
 *
 * The storefront template is a standalone React Router 7 SSR app that
 * installs with `pnpm install --ignore-workspace`; `templates/` is shipped
 * with the package so the path resolves from both `src/` and `dist/`.
 */

import { fileURLToPath } from 'node:url';

/** Absolute path of the storefront template directory (no trailing slash). */
export const STOREFRONT_TEMPLATE_DIR = fileURLToPath(
  new URL('../templates/storefront', import.meta.url),
);
