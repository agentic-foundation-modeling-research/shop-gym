# Navigation primitives

A small layer of presentational components and hooks shipped with the
hydrogen template so every `gen_navigation` pass *imports* a primitive
instead of *re-deriving* it. The catalog below lists every primitive,
its intended consumer, and its canonical use site.

> See [`docs/specs/shop_arena/template_navigation_primitives.md`][spec]
> for the design rationale (§"Why the primitive layer pays for itself"),
> and [`docs/impl/template_navigation_primitives_implementation.md`][impl]
> for the build-up history.

[spec]: ../../../../../../../../docs/specs/shop_arena/template_navigation_primitives.md
[impl]: ../../../../../../../../docs/impl/template_navigation_primitives_implementation.md

## Contract

Every primitive in this layer follows the same split:

- **Structure is template-owned.** The primitive owns the DOM shape,
  the ARIA wiring, and the behavioral invariants (single-open
  accordion, hover debounce, `aria-current="page"` on the trailing
  crumb, etc.).
- **Styling is consumer-owned.** Primitives ship class-name hooks
  (`.nav-menu`, `.breadcrumbs`, `.footer-column`, …) and zero CSS.
  Per-shop styling lives in `app/styles/app.css` (or wherever the
  consumer's design system terminates).
- **Data is loader-owned.** Primitives accept already-fetched
  Storefront payloads as props; they never call the API themselves.

Re-deriving a primitive's behavior in a consumer (a hand-rolled
`setTimeout`-based hover debounce, a local `font: inherit` reset on a
nav `<button>`, a two-`<details>`-open mobile drawer, a fabricated
mid-crumb that is not in `product.collections.nodes`) is a verifier
failure — see `navigation_primitive_usage` in
`packages/shop_arena/src/shop_gen/build/verifiers/navigation_primitive_usage.py`.

## Catalog

The eight primitives plus the active-state hook:

### `<NavTrigger>` — `app/components/NavTrigger.tsx`

`forwardRef`-ed `<button>` for nav-row triggers (dropdowns, mega
menus). Owns the `font: inherit` / `line-height: inherit` /
`color: inherit` / `background: transparent` / `border: 0` /
`padding: 0` / `cursor: pointer` reset inline so the typographic
baseline cannot drift, and owns the `aria-haspopup="menu"` /
`aria-expanded={open}` / `aria-controls={menuId}` triple so consumers
cannot accidentally override the popover-trigger ARIA contract.
Consumed by **`<NavMenu>`** internally; consumed directly when a
shop's mega-menu chrome is custom enough that `<NavMenu>`'s default
popover does not fit.

```tsx
import {NavTrigger} from '~/components/NavTrigger';
import {useHoverIntent} from '~/lib/use-hover-intent';

const {open, triggerProps} = useHoverIntent();
const menuId = useId();
<div {...triggerProps}>
  <NavTrigger open={open} menuId={menuId}>Shop</NavTrigger>
  {open ? <ul id={menuId}>…</ul> : null}
</div>
```

### `<NavMenu>` — `app/components/NavMenu.tsx`

Recursive desktop menu renderer. Walks a Storefront `menu` payload,
renders each leaf as a `<NavLink>` and each parent as a
`<NavTrigger>`-plus-`<ul>` popover wired through `useHoverIntent`.
Strips the shop's `primaryDomain.url` and `publicStoreDomain` off
absolute URLs via the exported `toLocalUrl` helper. Consumed by
**`gen_navigation`** in the desktop branch of `Header.tsx`.

```tsx
import {NavMenu} from '~/components/NavMenu';

<NavMenu
  menu={header.menu}
  viewport="desktop"
  primaryDomainUrl={header.shop.primaryDomain.url}
  publicStoreDomain={publicStoreDomain}
  linkClassName="header-menu-item"
  triggerClassName="header-menu-item"
/>
```

Also exports `toLocalUrl(url, primaryDomainUrl, publicStoreDomain)` —
the URL-stripping rule, hoisted as a pure function so sibling
primitives (`<MobileNavDrawer>`, `<FooterColumns>`) reuse it without
re-deriving.

To wrap each parent's popover in custom mega-menu chrome (eyebrow,
"Shop all" link, column headings) without losing per-parent content,
pass `renderChildren` and call `defaultRender()` inside it — the
default renders `item.items` (the parent's own children) into a
`<ul className="nav-menu-children">` that the consumer styles. The
parent context arrives as the `item` argument; never substitute a
module-level constant for `defaultRender()`, otherwise every tab
shows the same flyout body:

```tsx
<NavMenu
  menu={header.menu}
  viewport="desktop"
  primaryDomainUrl={header.shop.primaryDomain.url}
  publicStoreDomain={publicStoreDomain}
  renderChildren={(item, defaultRender) => (
    <div className="mega-menu" data-parent={item.id}>
      <span className="eyebrow">Shop</span>
      <NavLink to={toLocalUrl(item.url ?? '/', /* … */)}>
        Shop all {item.title} →
      </NavLink>
      {defaultRender()}
    </div>
  )}
/>
```

### `<HeaderShell>` — `app/components/HeaderShell.tsx`

Presentational layout for the page header. Three slots —
`brand`, `primary`, `ctas` — render into the canonical
`<header class="header"><div class="header-left">{brand}{primary}</div><div class="header-ctas">{ctas}</div></header>`
shape every shop in the program shares. The `.header-left` group
collapses today's per-shop brand→nav margin into a single `gap`
declaration (CSS for `.header-left` lives in `app/styles/app.css`),
eliminating the "fix spacing by adding `margin-left` to the desktop
nav" anti-pattern. Consumed by **`gen_navigation`** in `Header.tsx`.

```tsx
import {HeaderShell} from '~/components/HeaderShell';

<HeaderShell
  brand={<NavLink to="/">{shop.name}</NavLink>}
  primary={
    <NavMenu
      menu={menu}
      viewport="desktop"
      primaryDomainUrl={shop.primaryDomain.url}
      publicStoreDomain={publicStoreDomain}
    />
  }
  ctas={<HeaderCtas isLoggedIn={isLoggedIn} cart={cart} />}
/>
```

### `<MobileNavDrawer>` — `app/components/MobileNavDrawer.tsx`

Accordion drawer for mobile navigation. Renders one `<details>` per
parent menu item with React-controlled `open` state — opening any
parent unconditionally drops the prior id, so flipping between
parents never leaves two accordions expanded at once. Leaves render
as `<NavLink>` and dismiss the surrounding `<Aside type="mobile">` on
click via `useAside().close()`. Consumed by **`gen_navigation`**
inside the mobile `<Aside>` chrome.

```tsx
import {MobileNavDrawer} from '~/components/MobileNavDrawer';

<Aside type="mobile" heading="MENU">
  <MobileNavDrawer
    menu={header.menu}
    primaryDomainUrl={header.shop.primaryDomain.url}
    publicStoreDomain={publicStoreDomain}
    linkClassName="mobile-nav-link"
    triggerClassName="mobile-nav-trigger"
  />
</Aside>
```

### `<AnnouncementBar>` — `app/components/AnnouncementBar.tsx`

Dismissible, optionally-rotating announcement bar. SSR-safe by
construction — every `localStorage` / `setInterval` reference lives
inside a `useEffect` callback or an event handler so the
server-rendered HTML is byte-identical to the first client render.
Persists dismissal under `localStorage[storageKey]` (defaults to
`shop_announcement_dismissed`); rotates through `messages` every 5s
when more than one is supplied; renders `null` when dismissed or
empty. Consumed by **`gen_navigation`** above `<HeaderShell>` (or
wherever the shop's design positions a marketing bar).

```tsx
import {AnnouncementBar} from '~/components/AnnouncementBar';

<AnnouncementBar
  messages={['Free shipping over $50', 'New season specials']}
  href="/collections/new"
/>
```

### `<Breadcrumbs>` — `app/components/Breadcrumbs.tsx`

Dual-mode breadcrumb primitive. The wrapper exports two named
modes that share a `<nav aria-label="Breadcrumb"><ol>…</ol></nav>`
renderer, so the DOM/ARIA shape (including `aria-current="page"` on
the trailing crumb) is identical across both. Consumed by
**`gen_product`** (`<Breadcrumbs.FromCollections>` on the PDP) and
**`gen_collections`** / non-PDP routes (`<Breadcrumbs.FromMatches>`).

`Breadcrumbs.FromCollections` — picks the primary collection by
`collections.find(c => navPriority.includes(c.handle)) ?? collections[0]`
so the breadcrumb mirrors the user's likely entry path. Degrades to
`Home → product` when the product is in zero collections (no
fabricated mid-crumb).

```tsx
import {Breadcrumbs} from '~/components/Breadcrumbs';

<Breadcrumbs.FromCollections
  collections={product.collections.nodes}
  productTitle={product.title}
  navPriority={['mens', 'womens', 'sale']}
/>
```

`Breadcrumbs.FromMatches` — generic mode for layouts that compose
crumbs from `react-router`'s `useMatches()`. Routes without a builder
are silently skipped so a single call site can serve a layout
hosting heterogeneous child routes.

```tsx
import {useMatches} from 'react-router';
import {Breadcrumbs} from '~/components/Breadcrumbs';

const matches = useMatches();
<Breadcrumbs.FromMatches
  matches={matches}
  crumbBuilders={{
    'routes/collections.$handle': (m) => ({
      label: (m.data as {collection: {title: string}}).collection.title,
      href: `/collections/${(m.params as {handle: string}).handle}`,
    }),
  }}
/>
```

Also exports `buildCollectionCrumbs(collections, productTitle, navPriority)`
and `buildMatchCrumbs(matches, crumbBuilders)` — pure crumb-list
builders, so the picking rule is reusable without rendering.

### `<FooterColumns>` — `app/components/FooterColumns.tsx`

Multi-handle footer renderer. Takes a `Promise<Array<FooterQuery |
null>>` array (one entry per handle in
`env.PUBLIC_FOOTER_MENU_HANDLES`, defaulting to a single `'footer'`
menu) and renders one `<nav className="footer-column">` per non-null
entry. `null` entries (a single bad handle) are skipped silently so
the surviving columns still render — the page still 200s on partial
outage. Consumed by **`gen_navigation`** (rendered via `<PageLayout>`).

```tsx
import {Await, Suspense} from 'react';
import {FooterColumns} from '~/components/FooterColumns';

<Suspense>
  <Await resolve={footers}>
    {(resolved) => (
      <footer className="footer">
        <FooterColumns
          footers={resolved}
          headerShop={header.shop}
          publicStoreDomain={publicStoreDomain}
        />
      </footer>
    )}
  </Await>
</Suspense>
```

### `useHoverIntent` — `app/lib/use-hover-intent.ts`

Debounced hover-intent hook. Spread `triggerProps` onto the trigger
element and `contentProps` onto the popover content; entering either
opens the popover and cancels any pending close, leaving either
schedules a close on a `closeDelay`-ms timer (default
`DEFAULT_HOVER_CLOSE_DELAY_MS = 120`). The pending timer is cleared
on unmount. Use the imperative `close()` for click-driven dismissal
(e.g. when a link inside the popover is followed). Consumed
internally by `<NavMenu>`; consumed directly by custom mega-menu
chrome that needs the same behavioral contract.

```tsx
import {useHoverIntent} from '~/lib/use-hover-intent';

const {open, triggerProps, contentProps, close} = useHoverIntent();
const menuId = useId();
<div {...triggerProps}>
  <NavTrigger open={open} menuId={menuId}>Shop</NavTrigger>
  {open ? (
    <MegaMenu id={menuId} {...contentProps} onNavigate={close} />
  ) : null}
</div>
```

### `useNavActive` — `app/lib/use-nav-active.ts`

Active-state predicates derived from `react-router`'s match list.
Returns `{isActive, isParentActive}`:

- `isActive(path)` — true when the current leaf pathname equals
  `path` exactly (modulo a trailing slash). Use for leaf nav links
  whose highlight should disappear as soon as the user navigates
  into a descendant.
- `isParentActive(paths)` — true when the current leaf is at, or
  descended from, any of `paths`. Use for parent menu items whose
  dropdown contains the current page.

Memoized against the leaf pathname so passing the predicates to
memoized `<NavMenu>` builders does not invalidate them on unrelated
re-renders. Returns predicates that always yield `false` when there
is no active match (e.g. inside an error boundary mounted above the
router) rather than throwing. Consumed by **`gen_navigation`** when
the design wants programmatic active-state class names.

```tsx
import {useNavActive} from '~/lib/use-nav-active';

const {isActive, isParentActive} = useNavActive();
<NavMenu
  menu={menu}
  viewport="desktop"
  primaryDomainUrl={primaryDomainUrl}
  publicStoreDomain={publicStoreDomain}
  linkClassName={(href) => (isActive(href) ? 'is-active' : undefined)}
  triggerClassName={(item) =>
    isParentActive(item.items.map((i) => i.url ?? '')) ? 'is-active' : undefined
  }
/>
```

## Test surface

- `pnpm typecheck` (= `react-router typegen && tsc --noEmit`) gates
  every primitive's type contract.
- `packages/shop_arena/tests/shop_gen/test_template_smoke.py` asserts
  every primitive file exists and that its named export is wired
  correctly.
- The `navigation_primitive_usage` verifier
  (`packages/shop_arena/src/shop_gen/build/verifiers/navigation_primitive_usage.py`)
  enforces per-`gen_navigation`-run primitive adoption and flags the
  three known anti-patterns (re-derived hover-intent, re-derived
  button-typography reset, legacy `.header-menu-desktop { margin-left: 3rem }`
  CSS).
