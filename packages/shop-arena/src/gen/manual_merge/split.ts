/**
 * Splits the merged manual into the six per-area sub-manuals the build
 * agent reads (`manual/parts/<part>.md`). Sections route by exact H2 name.
 */

import { CANONICAL_SECTIONS, parseManualSections } from './prose.js';

export const MANUAL_PARTS = [
  'homepage',
  'navigation',
  'product',
  'collections',
  'cart_and_search',
  'info_pages',
] as const;

export type ManualPart = (typeof MANUAL_PARTS)[number];

const PART_HEADINGS: Readonly<Record<ManualPart, string>> = {
  homepage: 'Homepage',
  navigation: 'Navigation',
  product: 'Product',
  collections: 'Collections',
  cart_and_search: 'Cart & Search',
  info_pages: 'Info Pages',
};

const SECTION_TO_PART: Readonly<Record<string, readonly ManualPart[]>> = {
  Overview: [],
  'Site shell': ['navigation'],
  Homepage: ['homepage'],
  'Collections & navigation': ['collections'],
  'Product page': ['product'],
  Cart: ['cart_and_search'],
  Search: ['cart_and_search'],
  Internationalization: ['navigation'],
  'Floating UX': ['homepage'],
  'Policy & info pages': ['info_pages'],
  'UX Patterns Summary': [],
};

const REQUIRED_ANY_OF = [
  'Homepage',
  'Product page',
  'Collections & navigation',
  'Cart',
  'Policy & info pages',
];

/**
 * Renders the six sub-manuals.
 *
 * @param manual Merged `manual.md` text.
 * @param warn Receives a line for every section that is not in the routing map.
 * @throws Error when none of the structural sections is present.
 */
export function splitManual(
  manual: string,
  warn: (line: string) => void = () => undefined,
): Record<ManualPart, string> {
  const sections = parseManualSections(manual);
  if (!REQUIRED_ANY_OF.some((name) => sections.has(name))) {
    throw new Error(
      `merged manual is missing every required structural section (${REQUIRED_ANY_OF.join(', ')}); refusing to split into empty sub-manuals`,
    );
  }
  for (const name of sections.keys()) {
    if (!(name in SECTION_TO_PART)) {
      warn(
        `split_manual_parts: section ${JSON.stringify(name)} is not routed; it stays in manual.md only`,
      );
    }
  }
  const parts = {} as Record<ManualPart, string>;
  for (const part of MANUAL_PARTS) {
    const lines = [`# Sub-Manual - ${PART_HEADINGS[part]}`, ''];
    let routed = 0;
    for (const name of CANONICAL_SECTIONS) {
      const body = sections.get(name);
      if (body === undefined || body.trim() === '' || !SECTION_TO_PART[name]?.includes(part)) {
        continue;
      }
      lines.push(`## ${name}`, '', body.trimEnd(), '');
      routed += 1;
    }
    if (routed === 0) {
      lines.push('_(no sections from the merged manual route to this part)_');
    }
    parts[part] = `${lines.join('\n').trimEnd()}\n`;
  }
  return parts;
}
