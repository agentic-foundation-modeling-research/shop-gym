/**
 * @fileoverview Real-data breadcrumb primitive.
 *
 * Two render modes share the same DOM shape
 * (`<nav aria-label="Breadcrumb"><ol>…</ol></nav>`):
 *
 * - {@link Breadcrumbs.FromCollections} — feeds a product page. Picks the
 *   primary collection by intersecting `product.collections` with a
 *   shop-supplied nav-priority list, falling back to the first
 *   collection membership. Final crumb is the product title (no link).
 * - {@link Breadcrumbs.FromMatches} — feeds collection / page routes.
 *   Walks `useMatches()` and applies a per-route-id `crumbBuilder` so
 *   each route owns its own crumb shape (label + optional href).
 *
 * Both modes are deliberately **data-only**: there is no
 * `product_type` parsing, no handle-prefix heuristic, no fabricated
 * mid-crumb. Per `docs/specs/shop_arena/template_navigation_primitives.md`
 * §N6 (and `shop-ui-fixes` #9), every link is provably backed by real
 * storefront data — the consumer constructs the data, this primitive
 * only renders it.
 *
 * Owns structure and ARIA only — class names and the separator glyph
 * are consumer-supplied, and CSS lives in the consumer's stylesheet
 * (the spec splits structure from styling: structure here, styling
 * out there).
 */

import {Fragment} from 'react';
import type {ReactNode} from 'react';
import {Link, type UIMatch} from 'react-router';

/**
 * A single rendered breadcrumb.
 *
 * `label` is the visible text. `href` is optional: a crumb without an
 * `href` renders as plain text and is treated as the current page
 * (the trailing crumb in a typical breadcrumb trail).
 */
export interface Crumb {
  readonly label: string;
  readonly href?: string;
}

/**
 * Sentinel "Home" crumb prepended by {@link Breadcrumbs.FromCollections}.
 *
 * Exposed so {@link Breadcrumbs.FromMatches} consumers can prepend the
 * same crumb without re-deriving the label/href, keeping the two modes
 * visually identical.
 */
export const HOME_CRUMB: Crumb = {label: 'Home', href: '/'};

/**
 * Default visual separator between crumbs. Plain text so it inherits
 * the surrounding typography; consumers can pass an icon node via the
 * `separator` prop when the design calls for one.
 */
const DEFAULT_SEPARATOR: ReactNode = '/';

/**
 * Shape of an item in {@link BreadcrumbsFromCollectionsProps.collections}.
 *
 * Intentionally narrow — only the fields the breadcrumb actually
 * reads — so a consumer can pass any collection-like payload (the
 * Storefront `Collection` type is a structural superset).
 */
export interface CollectionRef {
  readonly handle: string;
  readonly title: string;
}

/**
 * Props for {@link Breadcrumbs.FromCollections}.
 */
export interface BreadcrumbsFromCollectionsProps {
  /**
   * Collections this product belongs to. Typically `product.collections.nodes`
   * from the Storefront API.
   */
  readonly collections: readonly CollectionRef[];
  /** Title of the product the breadcrumb terminates on. */
  readonly productTitle: string;
  /**
   * Ordered list of collection handles considered "primary" for nav
   * purposes. Usually derived from the storefront's main menu so the
   * breadcrumb mirrors the user's likely entry path.
   */
  readonly navPriority: readonly string[];
  /** Optional separator node rendered between crumbs. */
  readonly separator?: ReactNode;
}

/**
 * Build the crumb list for a product page.
 *
 * Pure function — exported so the primary-collection picking rule is
 * unit-testable (and so a consumer that wants the data without the
 * rendering can reuse it).
 *
 * Picks the primary collection as `collections.find(c =>
 * navPriority.includes(c.handle)) ?? collections[0]`. When the product
 * is in zero collections the breadcrumb degrades to `Home → product`,
 * which is the correct minimum (no fabricated mid-crumb).
 */
export function buildCollectionCrumbs(
  collections: readonly CollectionRef[],
  productTitle: string,
  navPriority: readonly string[],
): Crumb[] {
  const crumbs: Crumb[] = [HOME_CRUMB];
  const priority = new Set(navPriority);
  // `find` returns the first match in document order; that is fine for
  // the "intersect with priority list" rule because the priority order
  // is encoded in `priority` membership, not in `collections` order.
  const primary =
    collections.find((c) => priority.has(c.handle)) ?? collections[0];
  if (primary) {
    crumbs.push({
      label: primary.title,
      href: `/collections/${primary.handle}`,
    });
  }
  crumbs.push({label: productTitle});
  return crumbs;
}

/**
 * Props for {@link Breadcrumbs.FromMatches}.
 */
export interface BreadcrumbsFromMatchesProps {
  /** Output of `useMatches()` from `react-router`. */
  readonly matches: readonly UIMatch[];
  /**
   * Maps a route id (the `id` field on a `UIMatch`) to a function that
   * returns a {@link Crumb} for that match, or `null` to skip it.
   *
   * Routes without a builder are silently skipped — this is what lets
   * the same `<Breadcrumbs.FromMatches>` call site work across pages
   * that share a layout but have different crumb requirements.
   */
  readonly crumbBuilders: Readonly<
    Record<string, (match: UIMatch) => Crumb | null>
  >;
  /** Optional separator node rendered between crumbs. */
  readonly separator?: ReactNode;
}

/**
 * Build the crumb list for a route hierarchy.
 *
 * Pure function — exported for the same reasons as
 * {@link buildCollectionCrumbs}.
 */
export function buildMatchCrumbs(
  matches: readonly UIMatch[],
  crumbBuilders: Readonly<
    Record<string, (match: UIMatch) => Crumb | null>
  >,
): Crumb[] {
  const crumbs: Crumb[] = [];
  for (const match of matches) {
    const builder = crumbBuilders[match.id];
    if (!builder) continue;
    const crumb = builder(match);
    if (crumb) crumbs.push(crumb);
  }
  return crumbs;
}

interface BreadcrumbsListProps {
  readonly crumbs: readonly Crumb[];
  readonly separator: ReactNode;
}

/**
 * Internal: shared `<nav><ol>` renderer. Not exported — both public
 * modes go through this so the DOM/ARIA shape is identical.
 *
 * The trailing crumb is rendered as plain text (`aria-current="page"`)
 * regardless of whether it has an `href`, matching common breadcrumb
 * a11y guidance: the user is *on* that page, so a self-link is noise.
 */
function BreadcrumbsList({crumbs, separator}: BreadcrumbsListProps) {
  if (crumbs.length === 0) return null;
  const lastIndex = crumbs.length - 1;
  return (
    <nav aria-label="Breadcrumb" className="breadcrumbs">
      <ol className="breadcrumbs-list">
        {crumbs.map((crumb, i) => {
          const isLast = i === lastIndex;
          // Stable key: combine position + label so two crumbs with the
          // same label (rare but possible) don't collide.
          const key = `${i}-${crumb.label}`;
          return (
            <Fragment key={key}>
              <li
                className="breadcrumbs-item"
                {...(isLast ? {'aria-current': 'page' as const} : {})}
              >
                {crumb.href && !isLast ? (
                  <Link to={crumb.href} className="breadcrumbs-link">
                    {crumb.label}
                  </Link>
                ) : (
                  <span className="breadcrumbs-label">{crumb.label}</span>
                )}
              </li>
              {isLast ? null : (
                <li
                  className="breadcrumbs-separator"
                  aria-hidden="true"
                  role="presentation"
                >
                  {separator}
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}

/**
 * Render breadcrumbs for a product page from `product.collections`.
 *
 * @example
 * ```tsx
 * <Breadcrumbs.FromCollections
 *   collections={product.collections.nodes}
 *   productTitle={product.title}
 *   navPriority={['mens', 'womens', 'sale']}
 * />
 * ```
 */
function FromCollections({
  collections,
  productTitle,
  navPriority,
  separator = DEFAULT_SEPARATOR,
}: BreadcrumbsFromCollectionsProps) {
  const crumbs = buildCollectionCrumbs(collections, productTitle, navPriority);
  return <BreadcrumbsList crumbs={crumbs} separator={separator} />;
}

/**
 * Render breadcrumbs from `useMatches()` and a per-route builder map.
 *
 * @example
 * ```tsx
 * const matches = useMatches();
 * <Breadcrumbs.FromMatches
 *   matches={matches}
 *   crumbBuilders={{
 *     'routes/_index': () => ({label: 'Home', href: '/'}),
 *     'routes/collections.$handle': (m) => {
 *       const data = m.data as {collection?: {title: string; handle: string}};
 *       return data.collection
 *         ? {label: data.collection.title, href: `/collections/${data.collection.handle}`}
 *         : null;
 *     },
 *   }}
 * />
 * ```
 */
function FromMatches({
  matches,
  crumbBuilders,
  separator = DEFAULT_SEPARATOR,
}: BreadcrumbsFromMatchesProps) {
  const crumbs = buildMatchCrumbs(matches, crumbBuilders);
  return <BreadcrumbsList crumbs={crumbs} separator={separator} />;
}

/**
 * Two-mode breadcrumb namespace.
 *
 * Use `<Breadcrumbs.FromCollections>` on product pages and
 * `<Breadcrumbs.FromMatches>` on collection / page routes. The two
 * share rendering — picking between them is purely about which data
 * source the page has at hand.
 */
export const Breadcrumbs = {
  FromCollections,
  FromMatches,
} as const;
