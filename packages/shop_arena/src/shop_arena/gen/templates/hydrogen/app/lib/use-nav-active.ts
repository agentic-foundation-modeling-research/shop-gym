/**
 * @fileoverview Active-state helpers for nav links and parent menus.
 *
 * `<NavLink>` already toggles its own `isActive` flag against the current
 * URL, which is enough for *leaf* links. It is **not** enough for the
 * "parent of the current page" case — a top-level nav entry like
 * `/collections/men` should highlight when the user is on
 * `/collections/men/jackets`, but `<NavLink to="/collections/men">`
 * reports `isActive: false` there because the URLs are not equal.
 *
 * `useNavActive` closes that gap by reading `useMatches()` (which
 * returns the full route hierarchy from root to leaf) and exposing two
 * predicates a consumer can pass to a `className`/`style` builder.
 *
 * See `docs/specs/shop_arena/template_navigation_primitives.md`
 * §"Bonus: derived `activeLinkStyle` upgrade" for the bug class this
 * primitive eliminates.
 */

import {useMemo} from 'react';
import {useMatches, type UIMatch} from 'react-router';

/**
 * Predicates returned by {@link useNavActive}.
 *
 * Both predicates compare against `useMatches()` so they stay in sync
 * with `react-router`'s own route hierarchy.
 */
export interface NavActive {
  /**
   * Whether the *current* route's pathname equals `path` exactly
   * (modulo a trailing slash). Use for leaf nav links where the
   * highlight should disappear as soon as the user navigates into a
   * descendant.
   */
  readonly isActive: (path: string) => boolean;
  /**
   * Whether the current route is at — or descended from — any of
   * `paths`. Use for parent menu items whose dropdown contains the
   * current page (the parent stays highlighted while the user
   * browses inside it).
   */
  readonly isParentActive: (paths: readonly string[]) => boolean;
}

/**
 * Strip a single trailing slash so `/foo` and `/foo/` compare equal.
 *
 * The root path `/` is preserved as-is — collapsing it to an empty
 * string would make every other path "descend from root" by accident
 * via the `startsWith(path + '/')` rule, lighting up every parent
 * trigger on every page.
 */
function normalize(path: string): string {
  if (path.length > 1 && path.endsWith('/')) {
    return path.slice(0, -1);
  }
  return path;
}

/**
 * Whether `current` is `parent` itself or a sub-route below it.
 *
 * Equivalent to `current === parent || current.startsWith(parent + '/')`
 * after normalization. The trailing-slash guard prevents
 * `/collectionsX` from matching `/collections` as a descendant.
 */
function isAtOrUnder(current: string, parent: string): boolean {
  const c = normalize(current);
  const p = normalize(parent);
  if (c === p) return true;
  // Special-case `/` so every path "descends from root" without
  // requiring the caller to pass the empty string.
  if (p === '/') return c.startsWith('/');
  return c.startsWith(`${p}/`);
}

/**
 * Pull the leaf (deepest) match's pathname out of `useMatches()`.
 *
 * `useMatches()` returns root → leaf in order, so the last entry is
 * the page the user is currently looking at. Returns `null` when the
 * hook is called outside a router context or with an empty match list.
 */
function leafPathname(matches: readonly UIMatch[]): string | null {
  if (matches.length === 0) return null;
  const leaf = matches[matches.length - 1];
  return leaf ? leaf.pathname : null;
}

/**
 * Active-state predicates derived from `react-router`'s match list.
 *
 * The returned object is memoized against the current leaf pathname,
 * so passing the predicates to memoized children (e.g. a `<NavMenu>`
 * `linkClassName` builder) does not invalidate them on unrelated
 * re-renders.
 *
 * @returns An object exposing `isActive(path)` and
 *   `isParentActive(paths)`. Both return `false` when there is no
 *   active match (e.g. during the very first render of an error
 *   boundary above the router).
 *
 * @example
 * ```tsx
 * function PrimaryNav({menu}: {menu: HeaderQuery['menu']}) {
 *   const {isActive, isParentActive} = useNavActive();
 *   return (
 *     <NavMenu
 *       menu={menu}
 *       viewport="desktop"
 *       primaryDomainUrl={primaryDomainUrl}
 *       publicStoreDomain={publicStoreDomain}
 *       linkClassName={(href) => (isActive(href) ? 'is-active' : undefined)}
 *       triggerClassName={(item) =>
 *         isParentActive(item.items.map((i) => i.url ?? '')) ? 'is-active' : undefined
 *       }
 *     />
 *   );
 * }
 * ```
 */
export function useNavActive(): NavActive {
  const matches = useMatches();
  const leaf = leafPathname(matches);
  return useMemo<NavActive>(() => {
    if (leaf === null) {
      return {
        isActive: () => false,
        isParentActive: () => false,
      };
    }
    const normLeaf = normalize(leaf);
    return {
      isActive: (path: string) => normLeaf === normalize(path),
      isParentActive: (paths: readonly string[]) =>
        paths.some((p) => isAtOrUnder(normLeaf, p)),
    };
  }, [leaf]);
}
