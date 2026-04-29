# Hydrogen Template — Navigation Primitives

## Overview

Third companion to
[`template_baseline_fixes.md`](template_baseline_fixes.md) and
[`template_data_binding_fixes.md`](template_data_binding_fixes.md).
Those two cover CSS/element defaults and string/data hardcoding.
This one covers a different gap: **the navigation structure
the template ships is too thin for what `gen_navigation` is
expected to produce, so every run reinvents the same patterns
and re-hits the same bugs.**

The cloned `Header.tsx` is a flat list of `<NavLink>` items. The
cloned `Footer.tsx` is the same shape. There is no mega-menu, no
sub-menu rendering at all (despite the data layer supporting it),
no announcement bar, no mobile drawer beyond a re-styled flat
list, no breadcrumb component, no header-layout container, and
no active-state semantics beyond `fontWeight: 'bold'`. The
planner prompt asks `gen_navigation` to "implement Header,
Footer, MegaMenu, mobile nav, and announcement bar" — meaning the
executor builds all of those from zero per shop, and discovers
the same hover dead-zone (`mock_hardware` Issue 3),
button-typography drift (Issue 2), and brand→nav seam (Issue 1)
each time.

The proposal: ship a small set of **structural primitives** the
executor can fill in with shop-specific data and styling, rather
than rebuild the structure itself.

## Terminology

- **Structural primitive** — a small, dependency-free component
  or hook that owns the *correct geometry / a11y / event
  semantics* of a nav surface, leaving brand styling and content
  to the consumer. Examples: a hover-intent dropdown wrapper, a
  recursive menu renderer, a mobile-drawer accordion.
- **`gen_navigation`** — the executor task that owns
  `app/components/{Header,Footer,MegaMenu,MobileNav,AnnouncementBar}.tsx`.
- **Menu data** — `data/navigation.json`, parsed via
  `data_synth.schema.Navigation` (a `dict[str, list[NavigationItem]]`
  keyed by menu handle, with each `NavigationItem` carrying a
  recursive `children` field).
- **Menu fragment** — `MENU_FRAGMENT` in `app/lib/fragments.ts`,
  which already fetches one level of nesting via
  `ParentMenuItem.items` → `ChildMenuItem`.

## Current Status

The template ships **strictly less navigation than the data layer
already supports and strictly less than the executor is asked to
produce**. Three concrete gaps:

### 1. Recursive menu rendering is missing

`HeaderMenu` in `Header.tsx:70` does:

```tsx
{(menu || FALLBACK_HEADER_MENU).items.map((item) => {
  if (!item.url) return null;
  // …flat <NavLink> for item only…
})}
```

`item.items` is never read. The GraphQL fragment fetches it, the
data model emits it, the schema's `NavigationItem` is fully
recursive — and the template throws it away. `data_synth` may
emit a five-level nav and the rendered storefront still shows a
flat row.

Consequence: every `gen_navigation` pass rewrites `HeaderMenu`
end-to-end to even make sub-items visible. That rewrite is where
the brand→nav seam (Issue 1), button typography drift (Issue 2),
and hover dead-zone (Issue 3) get introduced — because the
rewrite is unconstrained and each one re-derives a different
shape.

### 2. No primitive for "trigger that opens content"

The dropdown / mega-menu pattern is the single most common
nav-shell feature on real storefronts (`shop_explore` already
captures it as `SiteShell.has_mega_menu`), and it has exactly
two stable bugs: hover-close dead zone when the menu is offset
from the trigger (`mock_hardware` Issue 3), and `<button>` vs
`<a>` baseline drift when the trigger sits inline with link
items (Issue 2 / shop-ui-fixes #8).

Both have been fixed per-artifact in `mock_hardware` and the fix
is mechanical and identical every time. The template ships
neither a `<NavTrigger>` button primitive nor a `useHoverIntent`
hook; the baseline spec proposes the hook (`P5`) but defers it
because it's hard to justify shipping a hook the executor
doesn't import. The right home for both is here, paired with a
`<NavMenu>` that *uses* them — at which point the hook earns its
keep because the renderer it ships with imports it.

### 3. Footer is single-handle and structureless

`root.tsx:130` queries one menu, handle `'footer'`. `Footer.tsx`
flattens it into a single `<nav class="footer-menu">`. Real
footers are columns of grouped links plus brand block plus
payment-method row plus copyright. The data schema already
supports this — `Navigation` is `dict[str, list[NavigationItem]]`
with open-ended keys, so `data_synth` can already emit
`footer-shop`, `footer-help`, `footer-legal` as three separate
menus. The template just doesn't consume them. Every
`gen_navigation` invents its own multi-handle convention
(`footer-col-1` / `col-2` / `col-3`, or `shop` / `help` /
`company`, etc.) and rewrites the loader to pull them.

### 4. Mobile drawer is desktop-nav-in-a-sidebar

`PageLayout.MobileMenuAside` mounts `<HeaderMenu viewport="mobile" />`.
The only thing the `viewport` prop changes is whether a `Home`
link is prepended. Result: a flat link list inside the drawer,
with no accordion for parent items, no per-section close, no
search-in-drawer affordance. Every executor rebuilds this.

### 5. Hardcoded chrome inside `HeaderCtas`

`HeaderCtas` hardcodes:

- the order `[MobileMenuToggle, Account, Search, Cart]`,
- the labels `Search`, `Sign in`/`Account`, `Cart <count>`,
- the absence of icons (everything is text).

All five generated shops in the codebase rewrite this region.
Some put icons-only at the right edge, some keep text labels,
some add a "Stores" finder, some drop the cart count. The
template's hardcoding is providing zero leverage — it ships an
opinion thin enough to be useless and rigid enough to be
overridden every time.

### 6. No breadcrumb primitive

`shop-ui-fixes #9` documents fabricated breadcrumbs across
multiple shops. Root cause is per-shop heuristics over
`product_type` strings or handle prefixes. The right answer
(per the same doc) is "use real Storefront API data" — i.e.
read `product.collections` and intersect with the nav
hierarchy. That's mechanical and shop-agnostic. The template
ships no breadcrumb component at all, so the executor either
invents one (and gets it wrong) or skips them.

### 7. No `<AnnouncementBar>` primitive

`SiteShell.has_announcement_bar` is a capability flag but there
is no `AnnouncementBar.tsx` to flip on. Each shop authors one
from scratch.

### 8. `activeLinkStyle` is one decision repeated everywhere

```ts
function activeLinkStyle({isActive, isPending}) {
  return {fontWeight: isActive ? 'bold' : undefined, ...};
}
```

Every nav surface (Header, Footer, MobileNav) re-imports this
identical function. Active-state styling for a sub-menu under an
active parent is undefined — `NavLink`'s `isActive` only
matches the exact link, so the parent of the current route never
highlights. Every shop's executor has to either accept that or
reinvent route-tree matching with `useMatches`.

## Desired Status

`gen_navigation` becomes a **fill-in** task rather than a
**rebuild** task. The executor:

- Imports a recursive `<NavMenu>` and passes it the menu data;
  it does not write a `.map(...).map(...)` loop.
- Imports `<NavTrigger>` for any dropdown / mega-menu trigger;
  it does not re-author button-typography overrides.
- Imports `useHoverIntent()` for hover-driven open/close; it
  does not invent a `setTimeout` debounce.
- Imports `<FooterColumns>` and wires it to whatever set of
  `footer-*` menu handles `data_synth` emitted; it does not
  rewrite the loader.
- Imports `<MobileNavDrawer>` with accordion behavior built in.
- Imports `<Breadcrumbs>` and feeds it `product.collections` or
  `useMatches()`-derived crumbs; it does not parse
  `product_type`.
- Imports `<AnnouncementBar>` and toggles via a capability flag.

The executor is still free to rewrite styling, swap the layout
container, add brand-specific surfaces (locale switcher, store
finder, sale ribbon), and reorder the CTA cluster. The
**structure** is donated by the template; the **identity** is
authored per shop.

This is the same trade-off the rest of the template already
makes for `Aside`, `SearchFormPredictive`, `SearchResultsPredictive`,
`CartLineItem`, `ProductForm` — each is a generic, dependency-free
primitive with the right semantics, and per-shop styling sits on
top. Navigation is the one surface where this layer is missing.

## Proposal

Eight new template files, all small, all in
`packages/shop_arena/src/shop_gen/templates/hydrogen/app/`. Each
has a clear "what it owns" boundary so the executor knows when
to use it and when to override.

### N1. `<NavMenu>` — recursive menu renderer

**File.** `app/components/NavMenu.tsx`.

**Contract.** Takes a `MenuFragmentType` and a `viewport` prop;
recursively renders `NavLink`s for leaves and a
`<NavWithChildren>` slot for parents. One level of nesting by
default (matches `MENU_FRAGMENT`'s current depth), opt-in to two
via prop. Accepts a `linkClassName` and `triggerClassName` so
shops can style without rewriting the structure. Internally
strips primaryDomain / publicStoreDomain from URLs (today
duplicated inline in `HeaderMenu`).

**What it doesn't own.** The container layout (flex direction,
gap, padding) — that's the consumer's CSS. The mega-menu *content*
— that's a render-prop the consumer passes per-parent.

### N2. `<NavTrigger>` — button-styled-as-link primitive

**File.** `app/components/NavTrigger.tsx`.

**Contract.** A `<button>` with `font: inherit; line-height: inherit; color: inherit; background: transparent; border: 0; padding: 0` baked in (the same fix as `template_baseline_fixes.md` P3, applied locally so it works even before P3 lands). Forwards refs. Owns ARIA: `aria-haspopup="menu"`, `aria-expanded={open}`, `aria-controls={menuId}`. Used by `<NavMenu>` for parent items and by the consumer for any nav-row button.

**Why it's separate from N1.** Some shops want a button trigger
on a leaf item (e.g. "Open store finder"). Decoupling the
trigger primitive from the menu renderer keeps both reusable.

### N3. `useHoverIntent` hook

**File.** `app/lib/use-hover-intent.ts`.

**Contract.** Documented in
`template_baseline_fixes.md` P5. Lives here instead of as a
standalone baseline because `<NavMenu>` is its primary
consumer — landing the hook on its own would have left it
unimported.

### N4. `<MobileNavDrawer>` — accordion drawer

**File.** `app/components/MobileNavDrawer.tsx`.

**Contract.** Mounts inside an existing `<Aside type="mobile">`
(reuses today's drawer chrome). Renders the same menu data as
`<NavMenu>` but in accordion form: each parent expands to show
children, only one section open at a time, focus traps on the
open accordion. Closes the drawer on link click via the
existing `useAside().close`.

### N5. `<FooterColumns>` — multi-handle footer

**Files.**
- `app/components/FooterColumns.tsx`
- `app/lib/fragments.ts` — extend `FOOTER_QUERY` to take
  `$footerMenuHandles: [String!]!` (array) instead of one handle,
  fan out via aliased queries.
- `app/root.tsx` — pull handle list from
  `env.PUBLIC_FOOTER_MENU_HANDLES` (CSV) or derive from a build
  step.

**Contract.** Renders one `<nav class="footer-column">` per menu
handle. Includes a `<FooterMeta>` slot for brand block /
payment-icons / copyright (consumer-authored). The single-menu
case (where `data_synth` emits exactly one `footer` handle) still
works — it's just a 1-column footer.

This is the most invasive of the eight because it touches the
GraphQL fragment and the env contract. Land it last (M3) —
M1/M2 are pure additions.

### N6. `<Breadcrumbs>` — real-data crumb renderer

**File.** `app/components/Breadcrumbs.tsx`.

**Contract.** Two render modes:
- `<Breadcrumbs.FromCollections>` — takes
  `product.collections` (already on the Storefront API spec),
  picks a primary by intersecting with a nav-priority list
  derived from the menu data, falls back to the first
  membership.
- `<Breadcrumbs.FromMatches>` — takes `useMatches()` and
  derives crumbs from route IDs (used on collection / page
  routes where there's no `product` to ground in).

Both share rendering: `nav[aria-label="Breadcrumb"] > ol > li`
with a separator slot. No `product_type` parsing, no
handle-prefix heuristics, no fabricated mid-crumbs. Per
shop-ui-fixes #9, every link is provably backed by real data.

### N7. `<AnnouncementBar>` primitive

**File.** `app/components/AnnouncementBar.tsx`.

**Contract.** Sticky bar above the header, dismissible via a
`localStorage` key so the dismissal survives reloads. Takes a
`messages: string[]` prop (rotates if length > 1) and an
`href?: string` for click-through. Visible by default; consumer
hides it by not mounting the component.

The `messages` content is per-shop and authored by the
executor. The component owns rotation, dismissal, ARIA
(`role="status"`), and the layout slot above the header.

### N8. `<HeaderShell>` — layout container

**File.** `app/components/HeaderShell.tsx`.

**Contract.** A presentational wrapper that defines the three
slots used by every shop:

```tsx
<HeaderShell
  brand={<Brand />}
  primary={<NavMenu menu={menu} viewport="desktop" />}
  ctas={<HeaderCtas .../>}
/>
```

Internally a flex row with `header-left` (brand + primary) and
`header-ctas` (CTAs), with the gap-only spacing from
`template_baseline_fixes.md` P1 already correct. No more
re-deriving the brand→nav seam (Issue 1).

Replaces today's `<Header>` body. The current `Header.tsx` keeps
its name and signature; its body becomes `<HeaderShell ...>`.

### Bonus: derived `activeLinkStyle` upgrade

While touching `Header.tsx`, replace the literal
`activeLinkStyle` with a `useNavActive()` hook that uses
`useMatches()` to detect parent-active state. Lets a sub-menu
parent highlight when any descendant is current. Tiny change,
but closes the "parent never highlights" gap in #8 above.

## Alternative

**A1. Don't ship primitives — ship a denser executor prompt.**
Add a "navigation patterns" appendix to `prompts/execute.md`
documenting the brand→nav-gap pattern, the button-typography
fix, the hover-intent debounce, the recursive renderer shape,
the footer-columns convention. Let each shop's `gen_navigation`
re-derive them from prose.

Rejected. Prompt-only enforcement is what produced the
recurring bugs in the first place. Every defect this spec
addresses has been documented in a prompt or a manual or a fix
report at least once and *still* recurs. Code is a stronger
contract than prose.

**A2. Ship a fully-styled navigation, not just primitives.**
Provide an opinionated default Header / Footer / MegaMenu with a
neutral design and have the executor restyle via tokens.

Rejected (for now). The visual identity *is* the executor's
job — coupling primitives to a specific look would either
constrain shops too much or get rewritten anyway. The split
"structure here, identity there" is the right boundary; A2 is
the eventual end-state once the primitive layer is stable
enough to absorb tokens.

**A3. Move the primitives into `@shopify/hydrogen` upstream.**
Some of these (recursive `<NavMenu>`, breadcrumbs from
collections) are arguably missing from real Hydrogen, not just
from the SandboxShop template. Upstreaming is fine but is a much
longer process and shouldn't gate this work. Land in the
template first; consider upstreaming later if the primitives
prove out.

## Milestones

**M1 — Trigger + recursion + hover-intent.** N1 + N2 + N3.
Three files. Pure additions; nothing in the template imports
them yet, so landing them is risk-free. The executor's
`gen_navigation` prompt is then updated (separate PR, in
`prompts/execute.md`) to consume them. Acceptance: re-running
`shop_gen` against `mock_hardware` produces a `Header.tsx`
that imports `<NavMenu>` and `<NavTrigger>` and does not
re-derive button-typography or hover-debounce code.

**M2 — Mobile drawer + announcement bar + breadcrumbs +
header shell.** N4 + N6 + N7 + N8. Four more files; still pure
additions. After this milestone, `gen_navigation` becomes a
"wire components together" task rather than a "build from
scratch" task. Acceptance: a fresh `mock_hardware` build
produces no inline accordion / announcement / breadcrumb logic
in `app/routes/*.tsx`.

**M3 — Multi-handle footer.** N5. Touches `FOOTER_QUERY` and
`root.tsx`'s env contract — invasive enough to deserve its own
milestone. Coordinate with `template_data_binding_fixes.md` C2
(menu handles via env) since they share the same env channel.

**M4 — `useNavActive` upgrade + `activeLinkStyle` cleanup.** Tiny
follow-up. Drop in once N1 is landing parent-active correctly.

**Acceptance.** A re-run of the existing build cassette for
`mock_hardware` produces a `Header.tsx` whose imports include
`NavMenu`, `NavTrigger`, `useHoverIntent`, `HeaderShell`, and
whose body is structurally a thin styling pass over those
primitives. The post-build polish diff against
`outputs/shops_fix/mock_hardware_issues_v1.md` covers no
navigation-rooted issues — Issues 1, 2, 3 are structurally
unreachable.

## Appendix

### A. Mapping — recurring defect → primitive that closes it

| Defect | Source | Primitive |
|---|---|---|
| Brand↔nav seam from compounding margins | `mock_hardware` #1 | N8 (`HeaderShell`) — single source of truth for the gap |
| `<button>` baseline drift in nav | `mock_hardware` #2; shop-ui-fixes #8 | N2 (`NavTrigger`) — typography reset baked in |
| Hover dead-zone on offset mega menu | `mock_hardware` #3 | N3 (`useHoverIntent`) consumed by N1 (`NavMenu`) |
| Flat menu hides recursive data | (latent — never rendered) | N1 (`NavMenu`) |
| Breadcrumb fabrication from `product_type` | shop-ui-fixes #9 | N6 (`Breadcrumbs.FromCollections`) |
| Footer is structureless single-column | (latent) | N5 (`FooterColumns`) |
| Announcement bar reinvented per shop | (latent) | N7 (`AnnouncementBar`) |
| Mobile drawer = desktop-nav-in-a-box | (latent) | N4 (`MobileNavDrawer`) |
| Parent-active never highlights | (latent) | M4 `useNavActive` |

### B. What this spec deliberately does *not* prescribe

- **Visual styling.** Token usage, color, hover affordance,
  spacing — all consumer-owned. Primitives ship neutral.
- **Specific menu-handle conventions** for footer columns. The
  template consumes whatever `env.PUBLIC_FOOTER_MENU_HANDLES`
  lists; `data_synth` decides what to emit.
- **Locale-aware nav** (region switcher, language picker). Out
  of scope until `template_data_binding_fixes.md` C1 lands a
  real localization shape.
- **Search-in-mobile-drawer**. Per-shop UX decision. The
  drawer just exposes a slot.

### C. Why the primitive layer pays for itself

Eight files, each ~50–150 lines. Total surface added to the
template is small and dependency-free. The leverage is on the
executor side: every `gen_navigation` pass today writes
~400–800 lines of new component code, much of it re-deriving the
same patterns. After M1+M2, `gen_navigation` is closer to
~150 lines (data wiring + per-shop styling), and the recurring
defects collapse from "prompt failures" to "import the right
primitive".

The same argument is why the template already ships `Aside`,
`SearchFormPredictive`, `CartLineItem`, etc. Navigation has
been the single surface left out of that pattern.

### D. Order-of-operations note

If all three template specs land, the recommended sequence is:

1. `template_baseline_fixes.md` P1–P4 (CSS / element defaults).
2. `template_data_binding_fixes.md` Tier A + B (Hydrogen-leak
   strings + fallback menus).
3. **This spec** M1 (trigger + recursion + hover-intent).
4. This spec M2 (drawer + announcement + breadcrumbs + shell).
5. `template_data_binding_fixes.md` Tier C (per-shop config,
   incl. menu-handle env).
6. This spec M3 (multi-handle footer — uses C2's env contract).
7. M4 + verifiers.

Each step preserves the previous step's invariants and
unlocks the next.
