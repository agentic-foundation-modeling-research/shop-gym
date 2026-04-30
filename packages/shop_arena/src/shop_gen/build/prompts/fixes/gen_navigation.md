# Fixes for `gen_navigation`

These rules supersede anything in `execute.md` §3 they contradict.

## Reuse the template's nav primitives

Build on the primitives the template already ships under
`app/components/` and `app/lib/` rather than re-deriving the same
logic inline:

- **`<NavMenu>`** (`app/components/NavMenu.tsx`) — recursive renderer
  for `HeaderQuery['menu']`. Owns parent → child nesting, hover-
  intent popovers, and primary-domain URL stripping. Pass it the
  loader's `header.menu`; the consumer owns CSS only.
- **`<NavTrigger>`** (`app/components/NavTrigger.tsx`) — the canonical
  `<button>` for opening a nav popover. Owns the ARIA contract
  (`aria-haspopup` / `aria-expanded` / `aria-controls`) and the
  button-typography reset (`font: inherit`, `color: inherit`,
  `background: transparent`, `border: 0`, `padding: 0`). Use it in
  place of styling a raw `<button>` per parent menu item.
- **`useHoverIntent`** (`app/lib/use-hover-intent.ts`) — hover-debounce
  hook. Returns `{open, triggerProps, contentProps, close}`; spread
  `triggerProps` onto the trigger element and `contentProps` onto the
  popover so dragging the cursor between them does not close the menu.
- **`<HeaderShell>`** (`app/components/HeaderShell.tsx`) — presentational
  header layout with three slots (`brand`, `primary`, `ctas`) and the
  canonical `.header` / `.header-left` / `.header-ctas` class names. Use
  it instead of hand-rolling the outer `<header>` element so brand → nav
  spacing stays in lockstep across shops.
- **`<MobileNavDrawer>`** (`app/components/MobileNavDrawer.tsx`) —
  accordion drawer for the mobile aside. Enforces the single-open
  invariant (opening one parent closes the prior) and closes the aside
  via `useAside().close` on link click. Mount it inside `<Aside
  type="mobile">`; do not re-derive `<details>` controlled state inline.
- **`<AnnouncementBar>`** (`app/components/AnnouncementBar.tsx`) —
  dismissible top bar with optional rotation across `messages` and
  `localStorage` persistence keyed by `storageKey`. SSR-safe by
  construction (the storage read lives in `useEffect`); reuse it
  instead of writing a new dismissible bar per shop.
- **`useNavActive`** (`app/lib/use-nav-active.ts`) — active-state
  hook returning `{isActive, isParentActive}`. Pass the predicates
  into `<NavMenu>`'s `linkClassName` / `triggerClassName` builders to
  highlight the current route and its ancestors without duplicating
  `useMatches()` plumbing in every consumer.
- **`<FooterColumns>`** (`app/components/FooterColumns.tsx`) — multi-
  column footer renderer. Takes the loader's `footers: Array<FooterQuery
  | null>` (one entry per handle in `env.PUBLIC_FOOTER_MENU_HANDLES`,
  CSV-parsed; defaults to a single `'footer'` menu when the var is
  unset) plus `headerShop` for primary-domain stripping, and emits one
  `<nav className="footer-column">` per non-null menu. Render it inside
  `<PageLayout>`'s `<Suspense>` / `<Await resolve={footers}>` block (see
  `app/components/PageLayout.tsx`) so the footer scales to whatever
  `footer-*` handles the data layer emits. Null entries are skipped silently
  so a partial outage on one handle still renders the surviving columns.

Re-deriving these — for example an inline `setTimeout`-based hover-
intent on a `<button>`, local `font: inherit` / `line-height:
inherit` resets on a nav trigger, a hand-rolled `<header>` wrapper
that re-implements `<HeaderShell>`'s slot contract, a custom
`<details>`-accordion mobile drawer that lets two sections stay open
at once, a per-shop announcement bar with its own dismissal-
persistence logic, or a hand-rolled multi-column `<footer>` that loops
over `env.PUBLIC_FOOTER_MENU_HANDLES` inline instead of rendering
`<FooterColumns>` against the loader's `footers` array — is a verifier
failure (the `navigation_primitive_usage` verifier flags both the
missing import and the re-derived anti-patterns). Compose the
primitives instead.

## Bind the mega menu (and mobile drawer panels) to `header.menu`, not to a static config

Each parent tab's flyout must render *that parent's own children* from
the Storefront menu payload — pass `<NavMenu>`'s `renderChildren` a
wrapper that calls `defaultRender()` (which renders `item.items`) or
read `item.items` directly inside the wrapper. **Do not** author a
module-level `MEGA_MENU_COLUMNS` / `NAV_LINKS` / similar constant that
lists every collection handle and render it for every parent. That
pattern satisfies `nav_coverage`'s textual scan (every handle appears
in source) while shipping the same flyout body for every tab, so
hovering "Cookware" and "Bakeware" show identical content. If a
sub-manual asks for a column count larger than any one parent's child
set, derive the columns from `item.items` (e.g. `chunk(item.items,
n)`) — never from a hard-coded list. The same rule applies to
`<MobileNavDrawer>`: each accordion's body is its parent's
`item.items`, not a shared global list.
