/**
 * @fileoverview Recursive menu renderer for header / footer navigation.
 *
 * Walks a Storefront `Menu` and renders a `<NavLink>` per leaf item; for
 * each parent (an item whose `items` array is non-empty) renders a
 * `<NavTrigger>` paired with a hover-intent driven popover containing
 * the children. Replaces the flat-only `HeaderMenu` that today ships
 * inline in `app/components/Header.tsx` and short-circuits any nested
 * `items` data the storefront returns.
 *
 * Owns structure only — class names are passed in via `linkClassName`
 * and `triggerClassName`, and per-parent popover *content* can be
 * replaced via the `renderChildren` render-prop. CSS, hover affordances,
 * and breakpoint behavior remain consumer-owned per the spec
 * (`docs/specs/shop_arena/template_navigation_primitives.md` §N1).
 */

import {useId} from 'react';
import type {ReactNode} from 'react';
import {NavLink} from 'react-router';
import type {HeaderQuery} from 'storefrontapi.generated';

import {NavTrigger} from '~/components/NavTrigger';
import {useHoverIntent} from '~/lib/use-hover-intent';

/**
 * Top-level `menu` shape returned by the Storefront `HEADER_QUERY` /
 * `FOOTER_QUERY`. Reused so consumers don't have to re-import the
 * generated type when wiring the primitive.
 */
type MenuData = HeaderQuery['menu'];

/**
 * A non-null `Menu` payload — the unwrapped form of {@link MenuData}.
 *
 * `MENU_FRAGMENT` produces one level of nesting (`ParentMenuItem` →
 * `ChildMenuItem`); this primitive renders that depth recursively.
 */
type MenuShape = NonNullable<MenuData>;

/**
 * A single item in {@link MenuShape.items}, including its nested
 * children when present.
 */
type MenuItem = MenuShape['items'][number];

/**
 * Strip the storefront's primary domain or the public store domain
 * from a menu-item URL, returning a route-relative path that
 * `<NavLink>` can match against `useMatches()`.
 *
 * Storefront menus are authored against the live shop's primary
 * domain; the same handles also resolve under the
 * `*.myshopify.com` mirror. Internal links must therefore be
 * normalized to a path before they are handed to the router so that
 * client-side navigation, prefetch, and active-state matching all
 * work. External links are returned unchanged.
 *
 * @param url - The raw `item.url` from the Storefront menu payload.
 * @param primaryDomainUrl - The shop's `primaryDomain.url`
 *   (e.g. `https://shop.example.com`).
 * @param publicStoreDomain - The shop's public storefront domain
 *   (e.g. `shop.example.com`), as exposed via env.
 * @returns A route-relative path for internal links, or the original
 *   URL for external ones.
 */
export function toLocalUrl(
  url: string,
  primaryDomainUrl: string,
  publicStoreDomain: string,
): string {
  const isInternal =
    url.includes('myshopify.com') ||
    url.includes(publicStoreDomain) ||
    url.includes(primaryDomainUrl);
  return isInternal ? new URL(url).pathname : url;
}

/**
 * Props for {@link NavMenu}.
 *
 * Intentionally unexported — per the public-surface contract the only
 * named exports from this module are `NavMenu` and `toLocalUrl`. Wrappers
 * that need to forward props should derive them with
 * `React.ComponentProps<typeof NavMenu>` instead of importing this
 * interface, which keeps the indirection one-directional and lets the
 * primitive evolve without breaking call sites.
 */
interface NavMenuProps {
  /** Storefront `menu` payload (may be `null` when the loader fails). */
  readonly menu: MenuData;
  /**
   * Layout context used by the consumer's CSS to vary spacing,
   * direction, and visibility. Forwarded as `data-viewport` on the
   * outer `<ul>`.
   */
  readonly viewport: 'desktop' | 'mobile';
  /** Shop primary-domain URL — see {@link toLocalUrl}. */
  readonly primaryDomainUrl: string;
  /** Public storefront domain — see {@link toLocalUrl}. */
  readonly publicStoreDomain: string;
  /** Optional `className` applied to every rendered `<NavLink>`. */
  readonly linkClassName?: string;
  /** Optional `className` applied to every parent `<NavTrigger>`. */
  readonly triggerClassName?: string;
  /**
   * Per-parent override for the popover body. Receives the parent
   * `item` and a `defaultRender` thunk that returns the primitive's
   * default `<ul>` of child `<NavLink>`s. Use this to slot a mega-menu
   * (featured products, imagery) without losing the default fallback.
   */
  readonly renderChildren?: (
    item: MenuItem,
    defaultRender: () => ReactNode,
  ) => ReactNode;
}

/**
 * Recursive menu renderer. See file-level docs for the contract.
 *
 * The component is structural: it owns the DOM shape and the
 * trigger/popover ARIA wiring (delegated to {@link NavTrigger} and
 * {@link useHoverIntent}), and nothing else. Consumers attach class
 * names, CSS, and per-parent overrides via props.
 *
 * @example
 * ```tsx
 * <NavMenu
 *   menu={header.menu}
 *   viewport="desktop"
 *   primaryDomainUrl={header.shop.primaryDomain.url}
 *   publicStoreDomain={publicStoreDomain}
 *   linkClassName="header-menu-item"
 *   triggerClassName="header-menu-item"
 * />
 * ```
 */
export function NavMenu({
  menu,
  viewport,
  primaryDomainUrl,
  publicStoreDomain,
  linkClassName,
  triggerClassName,
  renderChildren,
}: NavMenuProps) {
  const items: ReadonlyArray<MenuItem> = menu?.items ?? [];
  return (
    <ul className="nav-menu" data-viewport={viewport}>
      {items.map((item) => {
        if (!item.url) return null;
        const hasChildren = (item.items?.length ?? 0) > 0;
        if (hasChildren) {
          return (
            <NavWithChildren
              key={item.id}
              item={item}
              primaryDomainUrl={primaryDomainUrl}
              publicStoreDomain={publicStoreDomain}
              linkClassName={linkClassName}
              triggerClassName={triggerClassName}
              renderChildren={renderChildren}
            />
          );
        }
        return (
          <li key={item.id} className="nav-menu-item">
            <NavLink
              prefetch="intent"
              to={toLocalUrl(item.url, primaryDomainUrl, publicStoreDomain)}
              className={linkClassName}
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

interface NavWithChildrenProps {
  readonly item: MenuItem;
  readonly primaryDomainUrl: string;
  readonly publicStoreDomain: string;
  readonly linkClassName?: string;
  readonly triggerClassName?: string;
  readonly renderChildren?: NavMenuProps['renderChildren'];
}

/**
 * Internal: a single parent item rendered as a hover-intent popover.
 *
 * Not exported — the public surface is {@link NavMenu} and
 * {@link toLocalUrl}; consumers that want a bare trigger should use
 * {@link NavTrigger} directly.
 */
function NavWithChildren({
  item,
  primaryDomainUrl,
  publicStoreDomain,
  linkClassName,
  triggerClassName,
  renderChildren,
}: NavWithChildrenProps) {
  const {open, triggerProps, contentProps, close} = useHoverIntent();
  const menuId = useId();
  const children: ReadonlyArray<MenuItem['items'][number]> = item.items ?? [];

  const defaultRender = () => (
    <ul id={menuId} role="menu" className="nav-menu-children" {...contentProps}>
      {children.map((child) => {
        if (!child.url) return null;
        return (
          <li key={child.id} role="none" className="nav-menu-item">
            <NavLink
              role="menuitem"
              prefetch="intent"
              to={toLocalUrl(child.url, primaryDomainUrl, publicStoreDomain)}
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
    <li className="nav-menu-item nav-menu-parent" {...triggerProps}>
      <NavTrigger
        open={open}
        menuId={menuId}
        className={triggerClassName}
      >
        {item.title}
      </NavTrigger>
      {open ? renderChildren?.(item, defaultRender) ?? defaultRender() : null}
    </li>
  );
}
