"""Axis A probes: deterministic Playwright assertions, one per rubric leaf.

The leaf modules implement the rubric in ``rubric/v1.yaml``:

* :mod:`shop_probe.probes.site_shell` — header / nav / footer shell.
* :mod:`shop_probe.probes.homepage` — homepage section types.
* :mod:`shop_probe.probes.collection` — collection listing surface.
* :mod:`shop_probe.probes.product` — product detail page surface.
* :mod:`shop_probe.probes.search` — search trigger + results page.
* :mod:`shop_probe.probes.cart` — cart page + line-item flow.
* :mod:`shop_probe.probes.i18n` — locale / currency / market switchers.
* :mod:`shop_probe.probes.floating` — cookie / newsletter / chat overlays.
* :mod:`shop_probe.probes.dynamics` — toast region, URL-state-sync, AJAX
  cart endpoints, debounced inputs, cart-count badge.
* :mod:`shop_probe.probes.a11y` — skip-link, ARIA roles, alt-text coverage.
* :mod:`shop_probe.probes.media` — lazy-load, srcset, lightbox, swatch-swap.

Each probe is an ``async def fn(page, ctx) -> ProbeOutcome`` matching
:data:`shop_probe.probes._runner.ProbeFn`. The runner orchestrates Playwright
isolation + evidence root + timeouts; leaf probes assert one capability and
return a :class:`shop_probe.probes._runner.ProbeOutcome`.
"""
