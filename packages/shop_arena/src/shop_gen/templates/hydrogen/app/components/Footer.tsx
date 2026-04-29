/**
 * @fileoverview Backward-compatible footer wrapper.
 *
 * @deprecated Prefer `<FooterColumns>` (composed with a consumer-owned
 *   `<footer>` chrome) for new code. This module survives only so
 *   pre-T3.4 executor outputs that still pass the single-handle
 *   `footer: Promise<FooterQuery | null>` prop keep compiling against
 *   the new array-shaped loader contract from T3.2 (root.tsx) and the
 *   multi-column primitive from T3.3 (FooterColumns.tsx). Slated for
 *   removal in T5.2 once the cassette confirms no executor still
 *   consumes `<Footer>`. See
 *   `docs/specs/shop_arena/template_navigation_primitives.md` §N5.
 */

import {Suspense} from 'react';
import {Await} from 'react-router';
import type {FooterQuery, HeaderQuery} from 'storefrontapi.generated';

import {FooterColumns} from '~/components/FooterColumns';

interface FooterProps {
  /**
   * @deprecated Pass `footers` instead. Single-handle Promise kept so
   *   pre-migration executor output still compiles; the wrapper lifts
   *   it into a one-element array before forwarding to `<FooterColumns>`.
   */
  readonly footer?: Promise<FooterQuery | null>;
  /**
   * Array-shaped footer payload from `app/root.tsx`'s deferred loader
   * (one entry per handle in `env.PUBLIC_FOOTER_MENU_HANDLES`). When
   * supplied, takes precedence over the deprecated `footer` prop.
   */
  readonly footers?: Promise<Array<FooterQuery | null>>;
  readonly header: HeaderQuery;
  readonly publicStoreDomain: string;
}

/**
 * Renders the page footer.
 *
 * @deprecated New consumers should compose `<FooterColumns>` inside
 *   their own `<footer>` chrome; this wrapper exists for backward
 *   compatibility with executors that still pass the legacy single
 *   `footer` prop. The wrapper normalizes either prop shape into the
 *   array contract `<FooterColumns>` expects.
 */
export function Footer({
  footer,
  footers,
  header,
  publicStoreDomain,
}: FooterProps) {
  // Normalize the two accepted prop shapes into the array contract
  // `<FooterColumns>` consumes. `footers` wins when both are supplied
  // (matches the back-compat shim in `root.tsx`'s loader, where the
  // single `footer` is derived from `footers[0]` and is always less
  // information than the array).
  const resolved: Promise<Array<FooterQuery | null>> =
    footers ?? (footer ? footer.then((entry) => [entry]) : Promise.resolve([]));

  return (
    <Suspense>
      <Await resolve={resolved}>
        {(entries) => (
          <footer className="footer">
            <FooterColumns
              footers={entries}
              headerShop={header.shop}
              publicStoreDomain={publicStoreDomain}
            />
          </footer>
        )}
      </Await>
    </Suspense>
  );
}
