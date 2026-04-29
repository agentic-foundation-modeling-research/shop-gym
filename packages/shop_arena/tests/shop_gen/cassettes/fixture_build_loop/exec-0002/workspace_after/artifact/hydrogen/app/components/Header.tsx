// gen_navigation — synthetic Header component captured by the cassette.
//
// Adopts the M2 navigation primitives (`<HeaderShell>` + `<NavMenu>`) so
// the post-build artifact exercises the contract that
// `navigation_primitive_usage` enforces (per
// `docs/specs/shop_arena/template_navigation_primitives.md` §"Acceptance"):
// the header must import at least one of `<NavMenu>` or `<HeaderShell>`.
import type {ReactElement} from "react";

import {HeaderShell} from "~/components/HeaderShell";
import {NavMenu} from "~/components/NavMenu";

import type {HeaderQuery} from "storefrontapi.generated";

interface HeaderProps {
  readonly header: HeaderQuery;
  readonly publicStoreDomain: string;
}

export function Header({header, publicStoreDomain}: HeaderProps): ReactElement {
  const {shop, menu} = header;
  const primaryDomainUrl = shop.primaryDomain?.url ?? "";

  return (
    <HeaderShell
      brand={
        <a href="/" className="header-brand">
          {shop.name}
        </a>
      }
      primary={
        <NavMenu
          menu={menu}
          viewport="desktop"
          primaryDomainUrl={primaryDomainUrl}
          publicStoreDomain={publicStoreDomain}
        />
      }
      ctas={null}
    />
  );
}
