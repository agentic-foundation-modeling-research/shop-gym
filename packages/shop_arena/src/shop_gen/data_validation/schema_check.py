"""``validate_schema`` — Phase 3 schema check (spec §5.4).

First step of the data-validation sub-DAG. Re-validates every file
under ``<out_dir>/data/`` against the same closed pydantic mirrors
the synthesizer uses on output (:mod:`shop_gen.data_synth.schema`).
Pure I/O — no LLM, no network, no env reads.

The check is fast, deterministic, and in-process: spec §5.4 calls
out the verdict as "in-memory" because the next step
(:class:`shop_gen.data_validation.hosting_check.ValidateHostingStep`,
T4.2) is the one that boots ``shop-backend`` and writes the published
``data_validation.json``. ``validate_schema`` therefore declares no
output files; staleness is driven entirely by the recorded
fingerprint of its inputs (the six ``data/*.json`` files) and its
upstream :class:`shop_gen.data_synth.assemble.AssembleDataStep`.

Inputs read at run time:

* ``data/store.json`` — single :class:`Store` object.
* ``data/products.json`` — list of :class:`Product`.
* ``data/collections.json`` — list of :class:`Collection`.
* ``data/pages.json`` — list of :class:`Page`.
* ``data/policies.json`` — list of :class:`Policy`.
* ``data/navigation.json`` — :class:`Navigation` root object
  (``{menuHandle: NavigationItem[]}``).

Step contract (spec §5.7.1):

* ``id``: ``validate_schema``.
* ``phase``: ``data_validation``.
* ``inputs``: a :class:`~shop_gen.steps.base.StepInput` for the
  upstream ``assemble_data`` step + one
  :class:`~shop_gen.steps.base.FileInput` per ``data/*.json`` file.
* ``outputs``: ``[]`` — verdict is in-memory (raise on failure).
* ``depends_on``: ``[assemble_data]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, cast

from pydantic import ValidationError

from shop_gen.data_synth.schema import (
    Collection,
    Navigation,
    Page,
    Policy,
    Product,
    Store,
)
from shop_gen.steps.base import FileInput, InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_validation"
_STEP_ID: Final[str] = "validate_schema"
_STEP_VERSION: Final[int] = 1

_UPSTREAM_ASSEMBLE: Final[str] = "assemble_data"

_DATA_DIR: Final[Path] = Path("data")
_IN_STORE: Final[Path] = _DATA_DIR / "store.json"
_IN_PRODUCTS: Final[Path] = _DATA_DIR / "products.json"
_IN_COLLECTIONS: Final[Path] = _DATA_DIR / "collections.json"
_IN_PAGES: Final[Path] = _DATA_DIR / "pages.json"
_IN_POLICIES: Final[Path] = _DATA_DIR / "policies.json"
_IN_NAVIGATION: Final[Path] = _DATA_DIR / "navigation.json"

_IN_FILES: Final[tuple[Path, ...]] = (
    _IN_STORE,
    _IN_PRODUCTS,
    _IN_COLLECTIONS,
    _IN_PAGES,
    _IN_POLICIES,
    _IN_NAVIGATION,
)


class SchemaValidationError(ValueError):
    """Raised when a ``data/*.json`` file fails closed-schema validation.

    Carries the offending file path and the underlying parse / pydantic
    error so callers can surface the precise violation.

    Attributes:
        path: Run-relative path of the offending file
            (e.g. ``"data/products.json"``).
    """

    def __init__(self, *, path: Path, message: str) -> None:
        super().__init__(f"{_STEP_ID}: {path.as_posix()}: {message}")
        self.path: Path = path


def validate_data_dir(data_dir: Path) -> None:
    """Re-validate every published ``data/*.json`` under ``data_dir``.

    Pure validator — no scrub, no rewind, no on-disk side effects. Used
    by both :class:`ValidateSchemaStep` and the unit tests.

    Args:
        data_dir: Directory containing the six published files
            (typically ``<out_dir>/data/``).

    Raises:
        FileNotFoundError: A required file is missing under ``data_dir``.
        SchemaValidationError: A file is not valid JSON, has the wrong
            top-level shape (object vs array), or fails closed-schema
            validation against the matching pydantic mirror in
            :mod:`shop_gen.data_synth.schema`.
    """
    _validate_object(data_dir / _IN_STORE.name, model=Store)
    _validate_array(data_dir / _IN_PRODUCTS.name, model=Product)
    _validate_array(data_dir / _IN_COLLECTIONS.name, model=Collection)
    _validate_array(data_dir / _IN_PAGES.name, model=Page)
    _validate_array(data_dir / _IN_POLICIES.name, model=Policy)
    _validate_object(data_dir / _IN_NAVIGATION.name, model=Navigation)


class ValidateSchemaStep:
    """Phase 3 ``validate_schema`` step (spec §5.4).

    Reads every ``data/*.json`` file emitted by ``assemble_data`` and
    re-validates it against the closed pydantic mirrors in
    :mod:`shop_gen.data_synth.schema`. The verdict is in-memory: a
    successful run is silent, a failure raises
    :class:`SchemaValidationError` so the runner records the step
    ``FAILED`` and the user can re-run with
    ``--from assemble_data`` (spec §5.4).

    Attributes:
        id: Step id (``validate_schema``).
        phase: ``data_validation``.
        inputs: One :class:`StepInput` for ``assemble_data`` plus a
            :class:`FileInput` per ``data/*.json`` file.
        outputs: ``[]`` — verdict is in-memory.
        depends_on: ``[assemble_data]``.
        version: Bumped when the validation logic changes
            (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to the upstream ``assemble_data`` producer."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [
            StepInput(step_id=_UPSTREAM_ASSEMBLE),
            *(FileInput(path=p) for p in _IN_FILES),
        ]
        self.outputs: list[Path] = []
        self.depends_on: list[str] = [_UPSTREAM_ASSEMBLE]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Re-validate every ``data/*.json`` file under ``ctx.out_dir``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is ignored — the
                step is fully deterministic.

        Raises:
            FileNotFoundError: A required file is missing under
                ``<ctx.out_dir>/data/``.
            SchemaValidationError: A file fails closed-schema
                validation.
        """
        validate_data_dir(ctx.out_dir / _DATA_DIR)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _read_json(path: Path) -> Any:
    """Read ``path`` as JSON; raise :class:`SchemaValidationError` on parse failure."""
    if not path.exists():
        raise FileNotFoundError(f"{_STEP_ID}: required input not found at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(
            path=path,
            message=f"not valid JSON: {exc}",
        ) from exc


def _validate_object(path: Path, *, model: type[Store] | type[Navigation]) -> None:
    """Validate ``path`` against ``model``; require a top-level JSON object."""
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise SchemaValidationError(
            path=path,
            message=f"expected JSON object, got {type(raw).__name__}",
        )
    try:
        model.model_validate(raw)
    except ValidationError as exc:
        raise SchemaValidationError(
            path=path,
            message=f"failed {model.__name__} schema validation: {exc}",
        ) from exc


def _validate_array(
    path: Path,
    *,
    model: type[Product] | type[Collection] | type[Page] | type[Policy],
) -> None:
    """Validate ``path`` element-wise against ``model``; require a top-level JSON array."""
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise SchemaValidationError(
            path=path,
            message=f"expected JSON array, got {type(raw).__name__}",
        )
    items = cast("list[Any]", raw)
    for index, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise SchemaValidationError(
                path=path,
                message=f"entry {index} must be a JSON object, got {type(entry).__name__}",
            )
        try:
            model.model_validate(entry)
        except ValidationError as exc:
            raise SchemaValidationError(
                path=path,
                message=f"entry {index} failed {model.__name__} schema validation: {exc}",
            ) from exc


__all__ = [
    "SchemaValidationError",
    "ValidateSchemaStep",
    "validate_data_dir",
]
