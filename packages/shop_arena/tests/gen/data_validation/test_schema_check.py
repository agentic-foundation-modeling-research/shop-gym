"""Unit tests for :mod:`shop_arena.gen.data_validation.schema_check`.

Covers the T4.1 requirements from
``docs/impl/shop_gen_implementation.md``:

* Happy path: a fully populated ``data/`` fixture (the existing
  ``sandbox_shop_v0`` round-trip fixture used by
  :mod:`shop_arena.gen.data_synth.schema` tests) passes
  :func:`validate_data_dir`.
* Corrupted-fixture path: each of the six published files surfaces a
  :class:`SchemaValidationError` carrying its run-relative path when
  the file is not valid JSON, has the wrong top-level shape, or fails
  closed-schema validation.
* Step contract: id, phase, depends_on, no declared outputs (verdict
  is in-memory per spec §5.4); pipeline registration surfaces
  ``validate_schema`` in the data-validation phase listing.
* Step run: drives :class:`ValidateSchemaStep` against a copy of the
  fixture inside ``ctx.out_dir/data/`` and asserts a clean run is
  silent.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.data_validation import (
    SchemaValidationError,
    ValidateSchemaStep,
    validate_data_dir,
)
from shop_arena.gen.pipeline import list_steps
from shop_arena.gen.steps.base import FileInput, StepContext, StepInput

_FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "data_synth" / "fixtures" / "sandbox_shop_v0"
)
_FIXTURE_FILES: tuple[str, ...] = (
    "store.json",
    "products.json",
    "collections.json",
    "pages.json",
    "policies.json",
    "navigation.json",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _materialise_data_dir(out_dir: Path) -> Path:
    """Copy the canonical fixture into ``out_dir/data/`` and return that path."""
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in _FIXTURE_FILES:
        shutil.copy(_FIXTURE_DIR / name, data_dir / name)
    return data_dir


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_validate_data_dir_accepts_valid_fixture(tmp_path: Path) -> None:
    """A clean ``data/`` fixture validates without raising."""
    data_dir = _materialise_data_dir(tmp_path)

    validate_data_dir(data_dir)


def test_validate_data_dir_silent_on_success(tmp_path: Path) -> None:
    """The validator is verdict-only — it returns ``None`` on success."""
    data_dir = _materialise_data_dir(tmp_path)

    assert validate_data_dir(data_dir) is None


# --------------------------------------------------------------------------- #
# Missing files
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("missing", _FIXTURE_FILES)
def test_validate_data_dir_raises_when_required_file_missing(
    tmp_path: Path,
    missing: str,
) -> None:
    """Each required ``data/*.json`` file is enforced (FileNotFoundError)."""
    data_dir = _materialise_data_dir(tmp_path)
    (data_dir / missing).unlink()

    with pytest.raises(FileNotFoundError):
        validate_data_dir(data_dir)


# --------------------------------------------------------------------------- #
# Corrupted JSON / wrong top-level shape
# --------------------------------------------------------------------------- #


def test_validate_data_dir_rejects_invalid_json(tmp_path: Path) -> None:
    """Non-JSON bytes surface :class:`SchemaValidationError` for the offending file."""
    data_dir = _materialise_data_dir(tmp_path)
    (data_dir / "store.json").write_text("not-json{", encoding="utf-8")

    with pytest.raises(SchemaValidationError) as excinfo:
        validate_data_dir(data_dir)
    assert excinfo.value.path == data_dir / "store.json"
    assert "not valid JSON" in str(excinfo.value)


def test_validate_data_dir_rejects_object_when_array_expected(tmp_path: Path) -> None:
    """``products.json`` must be a top-level JSON array."""
    data_dir = _materialise_data_dir(tmp_path)
    (data_dir / "products.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SchemaValidationError) as excinfo:
        validate_data_dir(data_dir)
    assert excinfo.value.path == data_dir / "products.json"
    assert "expected JSON array" in str(excinfo.value)


def test_validate_data_dir_rejects_array_when_object_expected(tmp_path: Path) -> None:
    """``store.json`` must be a top-level JSON object."""
    data_dir = _materialise_data_dir(tmp_path)
    (data_dir / "store.json").write_text("[]", encoding="utf-8")

    with pytest.raises(SchemaValidationError) as excinfo:
        validate_data_dir(data_dir)
    assert excinfo.value.path == data_dir / "store.json"
    assert "expected JSON object" in str(excinfo.value)


def test_validate_data_dir_rejects_non_object_array_entry(tmp_path: Path) -> None:
    """Each element of an array file must itself be a JSON object."""
    data_dir = _materialise_data_dir(tmp_path)
    (data_dir / "pages.json").write_text(
        json.dumps(["not-an-object"]),
        encoding="utf-8",
    )

    with pytest.raises(SchemaValidationError) as excinfo:
        validate_data_dir(data_dir)
    assert excinfo.value.path == data_dir / "pages.json"
    assert "entry 0 must be a JSON object" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Closed-schema rejections (pydantic)
# --------------------------------------------------------------------------- #


def test_validate_data_dir_rejects_unknown_top_level_field_on_store(
    tmp_path: Path,
) -> None:
    """``Store`` schema is closed (extra='forbid')."""
    data_dir = _materialise_data_dir(tmp_path)
    raw = cast("dict[str, Any]", json.loads((data_dir / "store.json").read_text()))
    raw["unknown_field"] = "boom"
    (data_dir / "store.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaValidationError) as excinfo:
        validate_data_dir(data_dir)
    assert excinfo.value.path == data_dir / "store.json"
    assert "Store" in str(excinfo.value)


def test_validate_data_dir_rejects_missing_required_field_on_product(
    tmp_path: Path,
) -> None:
    """A :class:`Product` missing a required field fails closed-schema validation."""
    data_dir = _materialise_data_dir(tmp_path)
    raw = cast("list[dict[str, Any]]", json.loads((data_dir / "products.json").read_text()))
    raw[0].pop("vendor")
    (data_dir / "products.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaValidationError) as excinfo:
        validate_data_dir(data_dir)
    assert excinfo.value.path == data_dir / "products.json"
    assert "entry 0" in str(excinfo.value)
    assert "Product" in str(excinfo.value)


def test_validate_data_dir_rejects_unknown_navigation_item_type(
    tmp_path: Path,
) -> None:
    """``NavigationItemType`` is a closed Literal — unknown values are rejected."""
    data_dir = _materialise_data_dir(tmp_path)
    raw = cast("dict[str, Any]", json.loads((data_dir / "navigation.json").read_text()))
    cast("list[dict[str, Any]]", raw["main-menu"])[0]["type"] = "UNKNOWN"
    (data_dir / "navigation.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SchemaValidationError) as excinfo:
        validate_data_dir(data_dir)
    assert excinfo.value.path == data_dir / "navigation.json"
    assert "Navigation" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Step contract
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = ValidateSchemaStep()

    assert step.id == "validate_schema"
    assert step.phase == "data_validation"
    assert step.depends_on == ["assemble_data"]
    # Verdict is in-memory (spec §5.4): no declared output files.
    assert step.outputs == []
    assert step.version >= 1


def test_step_inputs_cover_all_six_data_files() -> None:
    """Inputs must include the assemble_data step ref + every ``data/*.json`` file."""
    step = ValidateSchemaStep()

    step_inputs = [ref for ref in step.inputs if isinstance(ref, StepInput)]
    file_inputs = [ref for ref in step.inputs if isinstance(ref, FileInput)]
    assert [ref.step_id for ref in step_inputs] == ["assemble_data"]
    assert sorted(ref.path.name for ref in file_inputs) == sorted(_FIXTURE_FILES)


def test_step_registered_with_pipeline_appears_in_data_validation_phase() -> None:
    grouped = list_steps()

    assert "validate_schema" in grouped["data_validation"]


# --------------------------------------------------------------------------- #
# Step.run
# --------------------------------------------------------------------------- #


def test_step_run_validates_data_under_out_dir(tmp_path: Path) -> None:
    """``Step.run`` resolves ``data/`` under ``ctx.out_dir`` and validates it."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_data_dir(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir)

    ValidateSchemaStep().run(ctx)


def test_step_run_raises_on_corruption(tmp_path: Path) -> None:
    """``Step.run`` propagates :class:`SchemaValidationError` when ``data/`` is bad."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    data_dir = _materialise_data_dir(out_dir)
    (data_dir / "policies.json").write_text("{}", encoding="utf-8")
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir)

    with pytest.raises(SchemaValidationError) as excinfo:
        ValidateSchemaStep().run(ctx)
    assert excinfo.value.path == data_dir / "policies.json"
