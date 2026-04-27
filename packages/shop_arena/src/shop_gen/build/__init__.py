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

Later tasks (T5.3-T5.10) populate the verifier set, the prompt
assets, and the harness-loop driver under this same package.

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_gen.build.env import CloneTemplateStep, WriteEnvFileStep
from shop_gen.build.sidecar import (
    SidecarHandle,
    SidecarLifecycleError,
    StartSidecarStep,
    sidecar_lifecycle,
)

__all__ = [
    "CloneTemplateStep",
    "SidecarHandle",
    "SidecarLifecycleError",
    "StartSidecarStep",
    "WriteEnvFileStep",
    "sidecar_lifecycle",
]
