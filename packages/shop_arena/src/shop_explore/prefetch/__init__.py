"""Deterministic HTTP prefetch step for ``shop_explore``.

Implements §5.9 of the ShopExplore spec
(``docs/specs/shop_arena/shop_explore.md``): a small, fixed-URL HTTP
fetch that seeds the harness ``run_dir/artifact/prefetch/`` with enough
storefront context for the planner to reason about coverage.

No LLM. No browsing. No crawler. The agents do all further interaction
with the shop through the playwright skill.

Public surface (re-exported here so callers keep using
``shop_explore.prefetch.X``):

* :class:`PrefetchEntry` — per-URL outcome record.
* :class:`PrefetchResult` — summary written to ``prefetch.json``.
* :class:`ShopUnreachableError` — raised on bot-block / fatal index.
* :func:`run` — fetch a storefront into ``dest_dir``.
* :data:`DEFAULT_USER_AGENT`, :data:`DEFAULT_RATE_LIMIT_MS`,
  :data:`DEFAULT_TIMEOUT_SECONDS` — defaults for :func:`run`.

Submodules:

* :mod:`shop_explore.prefetch.models` — typed result records and the
  :class:`ShopUnreachableError` exception.
* :mod:`shop_explore.prefetch.runner` — the fetch plan, bot-block
  detection, and the :func:`run` entrypoint.
"""

from __future__ import annotations

from shop_explore.prefetch.models import (
    PrefetchEntry,
    PrefetchResult,
    ShopUnreachableError,
)
from shop_explore.prefetch.runner import (
    DEFAULT_RATE_LIMIT_MS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    run,
)

__all__ = [
    "DEFAULT_RATE_LIMIT_MS",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_USER_AGENT",
    "PrefetchEntry",
    "PrefetchResult",
    "ShopUnreachableError",
    "run",
]
