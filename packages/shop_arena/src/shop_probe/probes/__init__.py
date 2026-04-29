"""Axis A probes: deterministic Playwright assertions, one per rubric leaf.

The leaf modules implement the rubrics in ``rubric/v1.yaml``,
``rubric/v1.1.yaml`` (auth / checkout slice), and ``rubric/v1.2.yaml``
(advanced behavioral tier):

* :mod:`shop_probe.probes.site_shell` — header / nav / footer shell.
* :mod:`shop_probe.probes.homepage` — homepage section types.
* :mod:`shop_probe.probes.collection` — collection listing surface; v1.2
  advanced behavioral probes (``sort_changes_order``,
  ``filters_apply_to_results``, ``pagination_advances``,
  ``filter_click_advances_url``).
* :mod:`shop_probe.probes.product` — product detail page surface; v1.2
  advanced behavioral probes (``variant_swap_updates_state``,
  ``qty_spinner_increments``).
* :mod:`shop_probe.probes.search` — search trigger + results page; v1.2
  advanced behavioral probe (``predictive_listbox_populates``).
* :mod:`shop_probe.probes.cart` — cart page + line-item flow.
* :mod:`shop_probe.probes.i18n` — locale / currency / market switchers.
* :mod:`shop_probe.probes.floating` — cookie / newsletter / chat overlays.
* :mod:`shop_probe.probes.dynamics` — toast region, URL-state-sync, AJAX
  cart endpoints, debounced inputs, cart-count badge; v1.2 advanced
  behavioral probe (``cart_count_badge_updates``).
* :mod:`shop_probe.probes.a11y` — skip-link, ARIA roles, alt-text coverage.
* :mod:`shop_probe.probes.media` — lazy-load, srcset, lightbox, swatch-swap.
* :mod:`shop_probe.probes.account` — auth surface (login / signup / account page);
  v1.1, gated behind ``--include-auth`` (T7.4).
* :mod:`shop_probe.probes.checkout` — checkout flow + page;
  v1.1, gated behind ``--include-auth`` (T7.4).

Each probe is an ``async def fn(page, ctx) -> ProbeOutcome`` matching
:data:`shop_probe.probes._runner.ProbeFn`. The runner orchestrates Playwright
isolation + evidence root + timeouts; leaf probes assert one capability and
return a :class:`shop_probe.probes._runner.ProbeOutcome`. v1.2 behavioral
probes return ``passed=None`` when the storefront does not expose the
surface required to drive the interaction; the runner excludes those from
coverage aggregation.
"""
