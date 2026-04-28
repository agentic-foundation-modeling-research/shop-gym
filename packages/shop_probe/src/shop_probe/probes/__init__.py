"""Axis A probes: deterministic Playwright assertions, one per rubric leaf.

The leaf modules — :mod:`shop_probe.probes.site_shell`,
:mod:`shop_probe.probes.collection`, :mod:`shop_probe.probes.product`, and
:mod:`shop_probe.probes.cart` — implement the 20 ``core``-level probes that
ship in ``rubric/v1.yaml`` for the M1 slice (spec §7 M1).

Each probe is an ``async def fn(page, ctx) -> ProbeOutcome`` matching
:data:`shop_probe.probes._runner.ProbeFn`. The runner orchestrates Playwright
isolation + evidence root + timeouts; leaf probes assert one capability and
return a :class:`shop_probe.probes._runner.ProbeOutcome`.
"""
