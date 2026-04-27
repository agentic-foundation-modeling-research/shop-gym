"""Phase 4 build-harness-loop steps for the ``shop_gen`` pipeline.

Implements the env-setup + harness-driven build sub-DAG documented in
``docs/specs/shop_arena/shop_gen.md`` §5.5. v0.1 wires up incrementally
behind the impl plan T5.x tasks; today only the env-setup steps land:

* :mod:`shop_gen.build.env` — ``clone_template`` (T5.1) copies the
  vendored Hydrogen template into ``<out_dir>/hydrogen/``;
  ``write_env_file`` (T5.1) picks a free port and writes the
  resolved sidecar URL into ``hydrogen/.env``.

Later tasks (T5.2-T5.10) populate the sidecar lifecycle, the
verifier set, the prompt assets, and the harness-loop driver under
this same package.

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_gen.build.env import CloneTemplateStep, WriteEnvFileStep

__all__ = [
    "CloneTemplateStep",
    "WriteEnvFileStep",
]
