// gen_navigation — synthetic Footer component captured by the cassette.
//
// Adopts the M3 multi-handle footer primitive (`<FooterColumns>`) so the
// post-build artifact exercises the multi-menu contract from
// `docs/specs/shop_arena/template_navigation_primitives.md` §N5: the
// loader-side `footers: Array<FooterQuery | null>` array shape is what
// the consumer renders, with one `<nav>` per non-null menu.
import type {ReactElement} from "react";

import {FooterColumns} from "~/components/FooterColumns";

import type {FooterQuery, HeaderQuery} from "storefrontapi.generated";

interface FooterProps {
  readonly footers: ReadonlyArray<FooterQuery | null>;
  readonly headerShop: HeaderQuery["shop"];
  readonly publicStoreDomain: string;
}

export function Footer({footers, headerShop, publicStoreDomain}: FooterProps): ReactElement {
  return (
    <FooterColumns
      footers={footers}
      headerShop={headerShop}
      publicStoreDomain={publicStoreDomain}
    />
  );
}
