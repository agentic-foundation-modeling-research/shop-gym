"""Phase 4 build-harness-loop steps for the ``shop_gen`` pipeline.

Implements the env-setup + harness-driven build sub-DAG documented in
``docs/specs/shop_arena/shop_gen.md`` §5.5. v0.1 wires up incrementally
behind the impl plan T5.x tasks; today the env-setup pair plus the
sidecar lifecycle land:

* :mod:`shop_gen.build.env` — ``clone_template`` (T5.1) copies the
  vendored Hydrogen template into ``<out_dir>/hydrogen/``;
  ``write_env_file`` (T5.1) picks a free port and writes the
  resolved sidecar URL into ``hydrogen/.env``.
* :mod:`shop_gen.build.sidecar` — ``start_sidecar`` (T5.2) boots
  ``shop-backend`` against ``<out_dir>/data/`` to verify the spawn
  sequence and writes ``runs/build/sidecar.json`` capturing the
  resolved port + argv. Exposes :func:`sidecar_lifecycle` — the
  context-manager helper the harness loop driver (T5.6) reuses to
  hold the long-lived sidecar that the build loop talks to.
* :mod:`shop_gen.build.prompts` — ``agents.md`` / ``planner.md`` /
  ``execute.md`` / ``consolidate_execute.md`` (T5.3) loaders. The
  T5.6 loop driver feeds the agents-md / planner / executor strings
  into :class:`harness.PlanExecLoopConfig` and swaps in the
  consolidate body when the harness selects the mandatory final
  task.

* :mod:`shop_gen.build.verifiers` — rule-based verifiers used by the
  T5.6 loop driver: ``tsc``/``build``/``routes_200``/``data_in_use``/
  ``nav_coverage``/``no_brand_leak`` (T5.4). LLM-based verifiers
  (``quality_judge``, ``cross_task_consistency``) land in T5.5.

Later tasks (T5.5-T5.10) populate the LLM verifiers and the
harness-loop driver under this same package.

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_gen.build.env import CloneTemplateStep, WriteEnvFileStep
from shop_gen.build.prompts import (
    VERIFIER_FEEDBACK_PLACEHOLDER,
    load_agents_md,
    load_consolidate_execute_prompt,
    load_execute_prompt,
    load_planner_prompt,
)
from shop_gen.build.sidecar import (
    SidecarHandle,
    SidecarLifecycleError,
    StartSidecarStep,
    sidecar_lifecycle,
)
from shop_gen.build.verifiers import (
    BuildVerifier,
    DataInUseVerifier,
    DevServerFactory,
    GraphQLOperationError,
    GraphQLOperationRef,
    NavCoverageVerifier,
    NoBrandLeakVerifier,
    Routes200Verifier,
    SchemaIntrospection,
    TscVerifier,
)

__all__ = [
    "VERIFIER_FEEDBACK_PLACEHOLDER",
    "BuildVerifier",
    "CloneTemplateStep",
    "DataInUseVerifier",
    "DevServerFactory",
    "GraphQLOperationError",
    "GraphQLOperationRef",
    "NavCoverageVerifier",
    "NoBrandLeakVerifier",
    "Routes200Verifier",
    "SchemaIntrospection",
    "SidecarHandle",
    "SidecarLifecycleError",
    "StartSidecarStep",
    "TscVerifier",
    "WriteEnvFileStep",
    "load_agents_md",
    "load_consolidate_execute_prompt",
    "load_execute_prompt",
    "load_planner_prompt",
    "sidecar_lifecycle",
]
