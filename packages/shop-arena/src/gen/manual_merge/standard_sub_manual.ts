/**
 * The Standard sub-manual: one checked-in Sub-manual that describes, by the
 * Shopify standard, the pages Storefront exploration cannot observe
 * (account, checkout, order confirmation), the announcement bar and product
 * review rules, and the behavior the backend supports. Manual merge copies it
 * into every shop as `parts/standard.md`, next to the six cut Sub-manuals,
 * and fuses the shop's observed Account and Checkout notes into the copy.
 */

import { fileURLToPath } from 'node:url';

/** Path of the checked-in Standard sub-manual that every shop gets. */
export const STANDARD_SUB_MANUAL_PATH = fileURLToPath(
  new URL('./standard_sub_manual.md', import.meta.url),
);

/** File name of the Standard sub-manual under `manual/parts/`. */
export const STANDARD_SUB_MANUAL_FILE = 'standard.md';
