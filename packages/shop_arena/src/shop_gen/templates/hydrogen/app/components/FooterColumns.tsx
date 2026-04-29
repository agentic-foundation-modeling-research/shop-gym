/**
 * @fileoverview Multi-column footer renderer.
 *
 * Consumes the array of per-handle `FooterQuery` payloads emitted by
 * `app/root.tsx`'s deferred loader (one entry per handle in
 * `env.PUBLIC_FOOTER_MENU_HANDLES`, fan-out queried via
 * `FOOTER_QUERY`) and renders one `<nav className="footer-column">`
 * per non-null menu. Replaces the single-`<nav className="footer-menu">`
 * shape that today ships in `app/components/Footer.tsx`.
 *
 * Owns structure only — class names (`footer-column`,
 * `footer-column-items`, `footer-column-item`) are render-side hooks
 * for consumer styling. CSS, layout, and breakpoint behavior remain
 * consumer-owned per the spec
 * (`docs/specs/shop_arena/template_navigation_primitives.md` §N5).
 */

import {NavLink} from 'react-router';
import type {FooterQuery, HeaderQuery} from 'storefrontapi.generated';

import {toLocalUrl} from '~/components/NavMenu';

interface FooterColumnsProps {
  /**
   * One Storefront `FooterQuery` payload per footer menu handle, in
   * the same order the loader receives them from
   * `env.PUBLIC_FOOTER_MENU_HANDLES`. Entries may be `null` when the
   * per-handle query failed (e.g. handle missing on the storefront);
   * those slots are skipped without aborting the rest of the footer.
   */
  readonly footers: ReadonlyArray<FooterQuery | null>;
  /**
   * The `header.shop` payload — used solely to read
   * `primaryDomain.url` for URL stripping via {@link toLocalUrl}.
   * Passed as a whole so consumers don't have to plumb the URL
   * separately (and so a future spec extension that needs more shop
   * fields doesn't break the prop signature).
   */
  readonly headerShop: HeaderQuery['shop'];
  /** Public storefront domain (`env.PUBLIC_STORE_DOMAIN`). */
  readonly publicStoreDomain: string;
}

/**
 * Renders one `<nav className="footer-column">` per non-null menu in
 * `footers`. Returns `null` when no column has data so the consumer's
 * footer wrapper can decide whether to render an empty container or
 * skip the surrounding chrome entirely.
 *
 * @example
 * ```tsx
 * <footer className="footer">
 *   <FooterColumns
 *     footers={footers}
 *     headerShop={header.shop}
 *     publicStoreDomain={publicStoreDomain}
 *   />
 * </footer>
 * ```
 */
export function FooterColumns({
  footers,
  headerShop,
  publicStoreDomain,
}: FooterColumnsProps) {
  const primaryDomainUrl = headerShop.primaryDomain?.url ?? '';
  const columns = footers.filter(
    (entry): entry is NonNullable<typeof entry> => entry?.menu != null,
  );
  if (columns.length === 0) return null;
  return (
    <>
      {columns.map((footer, idx) => {
        const menu = footer.menu;
        if (!menu) return null;
        return (
          <nav
            key={menu.id}
            className="footer-column"
            data-column-index={idx}
            role="navigation"
          >
            <ul className="footer-column-items">
              {menu.items.map((item) => {
                if (!item.url) return null;
                const url = toLocalUrl(
                  item.url,
                  primaryDomainUrl,
                  publicStoreDomain,
                );
                const isExternal = !url.startsWith('/');
                return (
                  <li key={item.id} className="footer-column-item">
                    {isExternal ? (
                      <a
                        href={url}
                        rel="noopener noreferrer"
                        target="_blank"
                      >
                        {item.title}
                      </a>
                    ) : (
                      <NavLink prefetch="intent" to={url} end>
                        {item.title}
                      </NavLink>
                    )}
                  </li>
                );
              })}
            </ul>
          </nav>
        );
      })}
    </>
  );
}
