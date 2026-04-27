"""Phase 3 data-validation steps for the ``shop_gen`` pipeline.

Implements the post-synthesis validation sub-DAG documented in
``docs/specs/shop_arena/shop_gen.md`` §5.4. Each submodule owns one
step in the table:

* :mod:`shop_gen.data_validation.schema_check` —
  ``validate_schema`` step + the pure
  :func:`validate_data_dir` helper.

The package is import-safe: no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

from shop_gen.data_validation.schema_check import (
    SchemaValidationError,
    ValidateSchemaStep,
    validate_data_dir,
)

__all__ = [
    "SchemaValidationError",
    "ValidateSchemaStep",
    "validate_data_dir",
]
