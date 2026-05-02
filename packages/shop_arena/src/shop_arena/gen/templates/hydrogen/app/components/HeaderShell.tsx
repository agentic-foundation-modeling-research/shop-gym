/**
 * @fileoverview Layout container for the site header.
 *
 * Defines the three slots every shop's header occupies — brand mark,
 * primary nav, and CTAs — as a presentational wrapper. Owns the
 * `.header` / `.header-left` / `.header-ctas` DOM shape so that
 * brand-to-nav spacing lives in one CSS rule (`.header-left { gap: ... }`)
 * instead of being re-derived per shop via `margin-left` on the nav
 * (the bug class behind `mock_hardware` Issue 1 and `shop-ui-fixes` #1).
 *
 * Structural only — no styling beyond the layout primitives. Visual
 * treatment of the slot contents is the consumer's responsibility per
 * `docs/specs/shop_arena/template_navigation_primitives.md` §N8.
 */

import type {ReactNode} from 'react';

/**
 * Props for {@link HeaderShell}.
 *
 * Each prop is a slot rendered into a fixed position in the header DOM:
 *
 * - `brand` — the leading content (typically a logo or shop-name link).
 * - `primary` — the primary navigation row, rendered immediately to the
 *   right of `brand` inside the same `.header-left` flex group so the
 *   brand→nav seam is governed by `gap` rather than `margin-left`.
 * - `ctas` — trailing actions (account, search, cart). Pushed to the
 *   far end of the row by `.header-ctas`'s `margin-left: auto`.
 *
 * The shell does not constrain the *content* of any slot — passing a
 * `<NavMenu>` and passing a custom mega-menu component are equally
 * valid; the shell only owns the surrounding flex structure.
 */
export interface HeaderShellProps {
  /** Leading slot — brand mark / shop-name link. */
  readonly brand: ReactNode;
  /** Primary navigation row, sharing the `.header-left` group with `brand`. */
  readonly primary: ReactNode;
  /** Trailing slot — header CTAs (account, search, cart). */
  readonly ctas: ReactNode;
}

/**
 * Presentational header layout: brand + primary nav on the left,
 * CTAs on the right.
 *
 * Renders the canonical
 * `<header class="header"><div class="header-left">…</div><div class="header-ctas">…</div></header>`
 * shape every shop in the program shares. The `.header-left` group
 * collapses today's brand→nav margin into a single `gap` declaration
 * on one CSS rule, eliminating the per-shop temptation to "fix"
 * spacing by adding `margin-left` to the desktop nav (Issue 1).
 *
 * @example
 * ```tsx
 * <HeaderShell
 *   brand={<NavLink to="/">{shop.name}</NavLink>}
 *   primary={
 *     <NavMenu
 *       menu={menu}
 *       viewport="desktop"
 *       primaryDomainUrl={shop.primaryDomain.url}
 *       publicStoreDomain={publicStoreDomain}
 *     />
 *   }
 *   ctas={<HeaderCtas isLoggedIn={isLoggedIn} cart={cart} />}
 * />
 * ```
 */
export function HeaderShell({brand, primary, ctas}: HeaderShellProps) {
  return (
    <header className="header">
      <div className="header-left">
        {brand}
        {primary}
      </div>
      <div className="header-ctas">{ctas}</div>
    </header>
  );
}
