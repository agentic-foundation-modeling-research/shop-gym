/**
 * The Standard sub-manual: one checked-in Sub-manual that describes, by the
 * Shopify standard, the pages Storefront exploration cannot observe
 * (account, checkout, order confirmation), the announcement bar and Reviews
 * rules, and the behavior the backend supports. Manual merge copies it
 * unchanged into every shop as `parts/standard.md`, next to the six cut
 * Sub-manuals.
 */

import { fileURLToPath } from 'node:url';

export const STANDARD_SUB_MANUAL_PATH = fileURLToPath(
  new URL('./standard_sub_manual.md', import.meta.url),
);

/** File name of the Standard sub-manual under `manual/parts/`. */
export const STANDARD_PART_FILE = 'standard.md';
