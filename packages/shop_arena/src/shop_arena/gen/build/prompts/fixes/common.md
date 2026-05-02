# Common fixes — apply to every `gen_*` task

These rules supersede anything in `execute.md` §3 they contradict.
They document fixes from prior runs that did not show up under any
single task's brief.

## Keep utility classes in `app.css`, not per-route stylesheets

`app/styles/app.css` is loaded by `root.tsx` and applies to every page;
per-route stylesheets like `app/styles/home.css` are only imported by
the route that uses them (e.g. `_index.tsx`). Generic utility classes
— `.sr-only`, `.visually-hidden`, `.container`, `.button`, focus-ring
helpers — must live in `app.css` so they work on every page.

The trap: a `.visually-hidden` rule defined in `home.css` looks fine
on the homepage (where home.css is loaded) but silently breaks every
other page that uses `className="visually-hidden"` — the class has no
styling, so the screen-reader-only label renders as visible text. A
common offender is the PDP quantity stepper's `<span
className="visually-hidden">Quantity</span>`, which leaks into the
button row as a stray "Quantity" word. `tsc` and `build` will not
catch this — the className is a valid string, the page renders, the
text is just where it shouldn't be.

When you author or edit a per-route stylesheet, scan its rules for
anything generic (a name that does not start with the route's prefix,
e.g. anything not `.home-*` in `home.css`). If you find one, move it
to `app.css`. The template ships `.sr-only` and `.visually-hidden`
already aliased in `app.css`; keep them there.
