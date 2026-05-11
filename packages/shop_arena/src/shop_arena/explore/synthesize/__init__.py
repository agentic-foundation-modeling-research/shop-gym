"""Post-loop synthesis for ``shop_arena.explore``.

Implements §5.10 of the ShopExplore spec
(``docs/specs/shop_arena/shop_arena.explore.md``): one deterministic Python
step that runs after the harness ``plan_exec_loop`` returns. Reads the
per-task fragments and prefetch evidence under ``run_dir/artifact/``,
writes the four published files of the Shop Manual (``manual.md``,
``capabilities.json``, ``stats.json``, ``manifest.json``).

Public surface (re-exported here so callers keep using
``shop_arena.explore.synthesize.X``):

* :func:`synthesize` — the post-loop entrypoint.
* :class:`SynthesisError` — raised on missing/invalid run_dir layout,
  when the merged capabilities fail schema validation, or when the
  manual-merge LLM call fails / returns an unusable response.
* :class:`SynthesisResult` — closed pydantic model returned by
  :func:`synthesize`.
* :class:`LLMClient` — minimal protocol the manual-merge call uses.
* :data:`MANUAL_MIN_CHARS` — minimum manual length below which the
  call is treated as failed (spec §5.10).

Submodules:

* :mod:`shop_arena.explore.synthesize.core` — the :func:`synthesize`
  entrypoint plus the :class:`SynthesisResult` / :class:`LLMClient` /
  :class:`SynthesisError` public surface.
* :mod:`shop_arena.explore.synthesize.manual` — single LLM call for
  ``manual.md``.
* :mod:`shop_arena.explore.synthesize.manifest` — ``manifest.json`` builder
  and the ``plan.md`` parsing helpers it depends on.
"""

from __future__ import annotations

from shop_arena.explore.synthesize.core import (
    LLMClient,
    SynthesisError,
    SynthesisResult,
    synthesize,
)
from shop_arena.explore.synthesize.manual import MANUAL_MIN_CHARS

__all__ = [
    "MANUAL_MIN_CHARS",
    "LLMClient",
    "SynthesisError",
    "SynthesisResult",
    "synthesize",
]
