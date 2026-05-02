/**
 * @fileoverview Accordion mobile-nav drawer primitive.
 *
 * Renders the same Storefront `Menu` payload as {@link NavMenu} but in
 * an accordion shape suited to a vertical drawer: each parent collapses
 * to a `<summary>` row that expands its children inline, with a
 * single-open-section invariant so opening one parent automatically
 * closes any previously open sibling. Designed to mount inside the
 * existing `<Aside type="mobile">` chrome (no drawer chrome of its own
 * — that's the consumer's responsibility per the spec).
 *
 * Owns structure only — class names are passed in via `linkClassName`
 * and `triggerClassName`, and per-parent body content can be replaced
 * via the `renderChildren` render-prop. CSS, transitions, and
 * focus-trap behavior remain consumer-owned per
 * `docs/specs/shop_arena/template_navigation_primitives.md` §N4.
 *
 * Reuses {@link toLocalUrl} from {@link NavMenu} so internal/external
 * URL handling stays consistent across the desktop and mobile menus
 * (both render the same data; only the layout differs).
 */

import {useState} from 'react';
import type {MouseEvent, ReactNode} from 'react';
import {NavLink} from 'react-router';
import type {HeaderQuery} from 'storefrontapi.generated';

import {useAside} from '~/components/Aside';
import {toLocalUrl} from '~/components/NavMenu';

/**
 * Top-level `menu` shape returned by the Storefront `HEADER_QUERY` /
 * `FOOTER_QUERY`. Reused so consumers don't have to re-import the
 * generated type when wiring the primitive.
 */
type MenuData = HeaderQuery['menu'];

/** A non-null `Menu` payload — the unwrapped form of {@link MenuData}. */
type MenuShape = NonNullable<MenuData>;

/** A single item in {@link MenuShape.items}, including its children. */
type MenuItem = MenuShape['items'][number];

/**
 * Props for {@link MobileNavDrawer}.
 *
 * Mirrors {@link NavMenu}'s prop set minus `viewport` — the drawer
 * is unconditionally a mobile-context surface, so a `viewport`
 * discriminator would be noise. Wrappers that need to forward props
 * should derive them with `React.ComponentProps<typeof MobileNavDrawer>`
 * rather than importing this interface (which is intentionally not
 * exported, mirroring `NavMenu`'s public-surface contract).
 */
interface MobileNavDrawerProps {
  /** Storefront `menu` payload (may be `null` when the loader fails). */
  readonly menu: MenuData;
  /** Shop primary-domain URL — see {@link toLocalUrl}. */
  readonly primaryDomainUrl: string;
  /** Public storefront domain — see {@link toLocalUrl}. */
  readonly publicStoreDomain: string;
  /** Optional `className` applied to every rendered `<NavLink>`. */
  readonly linkClassName?: string;
  /** Optional `className` applied to every parent `<summary>`. */
  readonly triggerClassName?: string;
  /**
   * Per-parent override for the accordion body. Receives the parent
   * `item` and a `defaultRender` thunk that returns the primitive's
   * default `<ul>` of child `<NavLink>`s. Use this to slot featured
   * imagery or custom layouts without losing the default fallback.
   */
  readonly renderChildren?: (
    item: MenuItem,
    defaultRender: () => ReactNode,
  ) => ReactNode;
}

/**
 * Accordion drawer for mobile navigation.
 *
 * Renders one `<details>` per parent menu item and one `<NavLink>` per
 * leaf. Open-state is React-owned (single `useState<string | null>`
 * tracking the currently-open parent's id) so that opening one section
 * deterministically closes any previously open sibling — flipping
 * between parents never leaves two accordions expanded at once. The
 * native `<summary>` toggle is suppressed via `preventDefault` so
 * React owns the source of truth and the `open` attribute stays in
 * lockstep with state.
 *
 * Leaf clicks call `useAside().close()` to dismiss the surrounding
 * mobile drawer, eliminating the open-after-navigate bug class on
 * mobile (matches `<NavMenu>`'s leaf-click behavior on desktop).
 *
 * @example
 * ```tsx
 * <Aside type="mobile" heading="MENU">
 *   <MobileNavDrawer
 *     menu={header.menu}
 *     primaryDomainUrl={header.shop.primaryDomain.url}
 *     publicStoreDomain={publicStoreDomain}
 *     linkClassName="mobile-nav-link"
 *     triggerClassName="mobile-nav-trigger"
 *   />
 * </Aside>
 * ```
 */
export function MobileNavDrawer({
  menu,
  primaryDomainUrl,
  publicStoreDomain,
  linkClassName,
  triggerClassName,
  renderChildren,
}: MobileNavDrawerProps) {
  const {close} = useAside();
  const [openId, setOpenId] = useState<string | null>(null);
  const items: ReadonlyArray<MenuItem> = menu?.items ?? [];

  return (
    <ul className="mobile-nav-drawer" role="menu">
      {items.map((item) => {
        if (!item.url) return null;
        const hasChildren = (item.items?.length ?? 0) > 0;
        if (hasChildren) {
          const isOpen = openId === item.id;
          const handleSummaryClick = (event: MouseEvent<HTMLElement>) => {
            // Suppress the browser's native `<details>` toggle so React
            // owns the open-state. Without this the native toggle and
            // the React state-update race, leaving the `open` attribute
            // out of sync with `openId`.
            event.preventDefault();
            setOpenId(isOpen ? null : item.id);
          };
          const defaultRender = () => (
            <ul className="mobile-nav-drawer-children" role="menu">
              {(item.items ?? []).map((child) => {
                if (!child.url) return null;
                return (
                  <li
                    key={child.id}
                    role="none"
                    className="mobile-nav-drawer-item"
                  >
                    <NavLink
                      role="menuitem"
                      prefetch="intent"
                      to={toLocalUrl(
                        child.url,
                        primaryDomainUrl,
                        publicStoreDomain,
                      )}
                      className={linkClassName}
                      onClick={close}
                      end
                    >
                      {child.title}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          );
          return (
            <li
              key={item.id}
              className="mobile-nav-drawer-item mobile-nav-drawer-parent"
            >
              <details open={isOpen}>
                <summary
                  className={triggerClassName}
                  onClick={handleSummaryClick}
                >
                  {item.title}
                </summary>
                {renderChildren?.(item, defaultRender) ?? defaultRender()}
              </details>
            </li>
          );
        }
        return (
          <li key={item.id} role="none" className="mobile-nav-drawer-item">
            <NavLink
              role="menuitem"
              prefetch="intent"
              to={toLocalUrl(item.url, primaryDomainUrl, publicStoreDomain)}
              className={linkClassName}
              onClick={close}
              end
            >
              {item.title}
            </NavLink>
          </li>
        );
      })}
    </ul>
  );
}
