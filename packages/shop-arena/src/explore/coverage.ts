/**
 * Coverage check: which storefront areas the prefetch evidenced but no
 * done Plan task explored and the plan did not explicitly omit.
 */

import { existsSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { type TaskList, taskById } from '@shop-gym/harness';

interface Area {
  readonly name: string;
  readonly taskIds: readonly string[];
  readonly omissionAliases: readonly string[];
}

const AREAS: readonly Area[] = [
  {
    name: 'homepage_sections',
    taskIds: ['homepage_sections'],
    omissionAliases: ['homepage', 'hero', 'sections', 'newsletter', 'popups'],
  },
  {
    name: 'header_navigation',
    taskIds: ['header_navigation', 'homepage_sections'],
    omissionAliases: ['site_shell', 'header'],
  },
  { name: 'footer', taskIds: ['footer', 'homepage_sections'], omissionAliases: ['site_shell'] },
  { name: 'cart', taskIds: ['cart_drawer', 'cart_page'], omissionAliases: ['cart_drawer_or_page'] },
  { name: 'search_predictive', taskIds: ['search_predictive'], omissionAliases: ['predictive'] },
  {
    name: 'search_results',
    taskIds: ['search_results', 'search_predictive'],
    omissionAliases: ['results_layout', 'search'],
  },
  {
    name: 'product_detail',
    taskIds: ['product_variants', 'product_gallery', 'product_extras', 'product_detail'],
    omissionAliases: ['product', 'gallery', 'variant_selectors'],
  },
  {
    name: 'collection',
    taskIds: ['collection_filters', 'collection_layout', 'collection_listing'],
    omissionAliases: ['collection_listing', 'filters', 'sort', 'pagination', 'listing_layout'],
  },
  { name: 'info_about', taskIds: ['info_pages'], omissionAliases: ['about', 'info_pages'] },
  { name: 'info_contact', taskIds: ['info_pages'], omissionAliases: ['contact', 'info_pages'] },
  { name: 'info_faq', taskIds: ['info_pages'], omissionAliases: ['faq', 'info_pages'] },
  {
    name: 'info_shipping',
    taskIds: ['info_pages'],
    omissionAliases: ['shipping', 'shipping_policy', 'info_pages'],
  },
  {
    name: 'info_returns',
    taskIds: ['info_pages'],
    omissionAliases: ['returns', 'returns_policy', 'refund_policy', 'info_pages'],
  },
  {
    name: 'info_privacy',
    taskIds: ['info_pages'],
    omissionAliases: ['privacy', 'privacy_policy', 'info_pages'],
  },
  {
    name: 'info_tos',
    taskIds: ['info_pages'],
    omissionAliases: ['tos', 'terms_of_service', 'info_pages'],
  },
];

const INFO_FILES: ReadonlyArray<readonly [string, string]> = [
  ['pages/about.html', 'info_about'],
  ['pages/contact.html', 'info_contact'],
  ['pages/faq.html', 'info_faq'],
  ['policies/shipping-policy.html', 'info_shipping'],
  ['policies/refund-policy.html', 'info_returns'],
  ['policies/privacy-policy.html', 'info_privacy'],
  ['policies/terms-of-service.html', 'info_tos'],
];

function present(dir: string, name: string): boolean {
  return existsSync(join(dir, name));
}

function nonEmpty(dir: string, name: string): boolean {
  const path = join(dir, name);
  return existsSync(path) && statSync(path).size > 0;
}

/** Areas the prefetched files prove to exist on the storefront. */
export function evidencedAreas(prefetchDir: string): Set<string> {
  const areas = new Set<string>();
  if (present(prefetchDir, 'index.html')) {
    areas.add('homepage_sections');
    areas.add('header_navigation');
    areas.add('footer');
  }
  if (present(prefetchDir, 'cart.js') || present(prefetchDir, 'cart.html')) areas.add('cart');
  if (present(prefetchDir, 'search_suggest.json')) areas.add('search_predictive');
  if (present(prefetchDir, 'search.html')) areas.add('search_results');
  if (nonEmpty(prefetchDir, 'products.json')) areas.add('product_detail');
  if (nonEmpty(prefetchDir, 'collections.json')) areas.add('collection');
  for (const [file, area] of INFO_FILES) {
    if (present(prefetchDir, file)) areas.add(area);
  }
  return areas;
}

/** Slugs listed under `## Omitted*` in `plan.md`. */
export function parseOmittedAreas(planMd: string): Set<string> {
  const omitted = new Set<string>();
  let inOmitted = false;
  for (const line of planMd.split(/\r?\n/)) {
    const heading = /^##\s+(.*)$/.exec(line);
    if (heading !== null) {
      inOmitted = (heading[1] ?? '').trim().toLowerCase().startsWith('omitted');
      continue;
    }
    const stripped = line.trim();
    if (inOmitted && stripped.startsWith('- ')) {
      const slug =
        stripped
          .slice(2)
          .split(/\s+(?:—|-)\s+/)[0]
          ?.trim() ?? '';
      if (slug !== '') omitted.add(slug);
    }
  }
  return omitted;
}

/** Whether a done Plan task covers `spec`, by the rule of `coverageGaps`. */
function coveredByTask(spec: Area, tasks: TaskList): boolean {
  const own = taskById(tasks, spec.name);
  if (own !== undefined) return own.status === 'done';
  return tasks.some((task) => task.status === 'done' && spec.taskIds.includes(task.id));
}

/**
 * Evidenced areas that no done Plan task covers and `omitted` does not
 * name.
 *
 * Only a done Plan task covers an area, so a pending, in-progress, or
 * blocked task (an area left unfinished, failed, or skipped) leaves it a
 * gap. When the plan has a Plan task with the area's own name, only that
 * task can cover the area. Otherwise any done task of the area can.
 */
export function coverageGaps(
  prefetchDir: string,
  tasks: TaskList,
  omitted: ReadonlySet<string>,
): string[] {
  const gaps: string[] = [];
  for (const area of evidencedAreas(prefetchDir)) {
    const spec = AREAS.find((candidate) => candidate.name === area);
    if (spec === undefined) continue;
    const covered =
      coveredByTask(spec, tasks) ||
      omitted.has(area) ||
      spec.omissionAliases.some((alias) => omitted.has(alias));
    if (!covered) gaps.push(area);
  }
  return gaps.sort();
}
