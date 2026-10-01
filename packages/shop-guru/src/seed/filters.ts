/**
 * Selection heuristics shared by the seed generators: which collections are
 * customer-facing, which products make good targets, which pages are policies.
 */

import type { Collection, Page, Product } from '@shop-gym/shop-backend';

const GENERIC_COLLECTION_TITLES: ReadonlySet<string> = new Set([
  'all',
  'sale',
  'new arrival',
  'new arrivals',
  'gift card',
  'gift cards',
  'best seller',
  'best sellers',
  'featured',
]);

const GENERIC_COLLECTION_TOKENS: readonly string[] = [
  'promo',
  'eligible',
  'test collection',
  'internal',
  'staff only',
  'wholesale',
  'draft',
  'automation',
];

const MIN_PRODUCT_TITLE_LENGTH = 4;
const MAX_PRODUCT_TITLE_LENGTH = 120;

/** True for catch-all or back-office collections an agent should not be sent to. */
export function isGenericCollection(title: string): boolean {
  const low = title.trim().toLowerCase();
  return (
    GENERIC_COLLECTION_TITLES.has(low) || GENERIC_COLLECTION_TOKENS.some((t) => low.includes(t))
  );
}

/** Non-generic collections with at least `minProducts` member handles. */
export function collectionsWithMinProducts(
  collections: readonly Collection[],
  minProducts: number,
): Collection[] {
  return collections.filter(
    (c) => c.product_handles.length >= minProducts && !isGenericCollection(c.title),
  );
}

/** Products with a sensible title and at least one available variant. */
export function isTaskCandidate(product: Product): boolean {
  const length = product.title.trim().length;
  if (length < MIN_PRODUCT_TITLE_LENGTH || length > MAX_PRODUCT_TITLE_LENGTH) {
    return false;
  }
  return product.variants.some((v) => v.available);
}

/**
 * Pages whose title or handle starts a word with one of `patterns`
 * (`ship` matches `shipping-info` but not `sponsorship`).
 */
export function pagesMatching(pages: readonly Page[], patterns: readonly string[]): Page[] {
  const regexes = patterns.map((p) => new RegExp(`\\b${escapeRegExp(p.toLowerCase())}`));
  return pages.filter((page) => {
    const hay = `${page.title.toLowerCase()} ${page.handle.toLowerCase().replaceAll('-', ' ')}`;
    return regexes.some((r) => r.test(hay));
  });
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
