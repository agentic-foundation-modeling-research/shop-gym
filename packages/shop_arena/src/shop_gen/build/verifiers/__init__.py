"""Phase 4 build-loop verifiers (spec §5.5.3, impl plan T5.4).

Each verifier in this package implements the
:class:`harness.verifiers.Verifier` protocol and is wired into the
:class:`harness.PlanExecLoopConfig` ``verifiers`` list by the T5.6 loop
driver. The harness owns dispatch + telemetry; ``shop_gen`` owns every
verifier *implementation* and decides which task ids each verifier
applies to.

The v0.1 verifier set lives here:

* :class:`TscVerifier` — ``pnpm tsc --noEmit`` against the hydrogen
  tree. Applies to every ``gen_*`` task plus ``consolidate``.
* :class:`BuildVerifier` — ``pnpm build`` against the hydrogen tree.
  Same applicability as :class:`TscVerifier`.
* :class:`DataInUseVerifier` — diffs the agent's GraphQL queries
  against the live shop_backend schema (introspection-derived). Applies
  to every ``gen_*`` task.
* :class:`NavCoverageVerifier` — every collection handle in
  ``data/collections.json`` is reachable from the hydrogen nav.
  Applies to ``gen_navigation``.
* :class:`NoBrandLeakVerifier` — runs the §5.6 allowlist scanner over
  ``hydrogen/app/**/*.{tsx,ts,css,md}``. Applies to every ``gen_*``
  task.
* :class:`Routes200Verifier` — boots a transient dev server and
  asserts every route resolved by the §5.3 bucket axis returns HTTP
  2xx. Applies to every ``gen_*`` task.

LLM-based verifiers (``quality_judge``, ``cross_task_consistency``)
land alongside this set under T5.5.

The package is import-safe: no I/O, no env reads, and no side effects
at import time.
"""

from __future__ import annotations

from shop_gen.build.verifiers.build import BuildVerifier
from shop_gen.build.verifiers.cross_task_consistency import CrossTaskConsistencyVerifier
from shop_gen.build.verifiers.data_in_use import (
    DataInUseVerifier,
    GraphQLOperationError,
    GraphQLOperationRef,
    SchemaIntrospection,
)
from shop_gen.build.verifiers.nav_coverage import NavCoverageVerifier
from shop_gen.build.verifiers.no_brand_leak import NoBrandLeakVerifier
from shop_gen.build.verifiers.quality_judge import QualityJudgeVerifier
from shop_gen.build.verifiers.routes_200 import Routes200Verifier
from shop_gen.build.verifiers.tsc import TscVerifier
from shop_gen.build.verifiers.visual_judge import VisualJudgeVerifier

__all__ = [
    "BuildVerifier",
    "CrossTaskConsistencyVerifier",
    "DataInUseVerifier",
    "GraphQLOperationError",
    "GraphQLOperationRef",
    "NavCoverageVerifier",
    "NoBrandLeakVerifier",
    "QualityJudgeVerifier",
    "Routes200Verifier",
    "SchemaIntrospection",
    "TscVerifier",
    "VisualJudgeVerifier",
]
