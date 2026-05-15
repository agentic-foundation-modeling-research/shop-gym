"""Unit + integration tests for :mod:`shop_arena.gen.data_validation.hosting_check`.

Covers the T4.2 requirements from
``docs/impl/shop_gen_implementation.md``:

* Step contract: id, phase, depends_on, declared output, pipeline
  registration surfaces ``validate_hosting`` in the data-validation
  phase listing.
* CLI discovery: monorepo walk-up + ``SHOP_BACKEND_CLI`` override.
* Subprocess lifecycle: ``run_hosting_checks`` boots ``shop-backend``,
  drives the spec §5.4 query suite end-to-end against the bundled
  fixture, writes ``data_validation.json``, and tears the subprocess
  down.
* Failure path: a dataset with empty ``collections.json`` reports
  per-check failures and raises :class:`HostingValidationError`
  without writing the verdict file.

These tests require the compiled ``packages/shop_backend/dist/cli.js``
(``pnpm --filter @shop-gym/shop-backend build``); they skip with a
clear message otherwise rather than silently passing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.data_validation import (
    HostingValidationError,
    ValidateHostingStep,
    find_shop_backend_cli,
    run_hosting_checks,
)
from shop_arena.gen.pipeline import list_steps
from shop_arena.gen.steps.base import FileInput, StepContext, StepInput

# --------------------------------------------------------------------------- #
# Fixture plumbing
# --------------------------------------------------------------------------- #

_DATA_FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "data_synth" / "fixtures" / "sandbox_shop_v0"
)
_BACKEND_FIXTURE_DIR = (
    Path(__file__).resolve().parents[5]
    / "packages"
    / "shop_backend"
    / "tests"
    / "fixtures"
    / "sandbox_shop_v0"
)
_FIXTURE_FILES: tuple[str, ...] = (
    "store.json",
    "products.json",
    "collections.json",
    "pages.json",
    "policies.json",
    "navigation.json",
)


def _materialise_data_dir(out_dir: Path) -> Path:
    """Copy the canonical JSON fixtures + a real ``images/`` tree into ``out_dir/data/``.

    Each product image src referenced by ``products.json`` is backed by
    a copy of the bundled 1x1 PNG so the §5.4 image GET check can load
    real bytes through ``shop-backend``'s static-image route.
    """
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in _FIXTURE_FILES:
        shutil.copy(_DATA_FIXTURE_DIR / name, data_dir / name)
    images_dir = data_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    pixel = _BACKEND_FIXTURE_DIR / "images" / "pixel.png"
    products = json.loads((data_dir / "products.json").read_text(encoding="utf-8"))
    for product in products:
        for image in product.get("images", []) or []:
            src = image.get("src")
            if isinstance(src, str):
                target = images_dir / src
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(pixel, target)
    return data_dir


def _backend_available() -> bool:
    """Return ``True`` when the compiled ``cli.js`` is on disk."""
    try:
        find_shop_backend_cli()
    except HostingValidationError:
        return False
    return True


_BACKEND_REASON = (
    "shop-backend dist/cli.js missing; run `pnpm --filter @shop-gym/shop-backend build`"
)


# --------------------------------------------------------------------------- #
# Step contract
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = ValidateHostingStep()

    assert step.id == "validate_hosting"
    assert step.phase == "data_validation"
    assert step.depends_on == ["validate_schema"]
    assert step.outputs == [Path("data_validation.json")]
    assert step.version >= 1


def test_step_inputs_cover_all_six_data_files() -> None:
    """Inputs must include the validate_schema ref + every ``data/*.json`` file."""
    step = ValidateHostingStep()

    step_inputs = [ref for ref in step.inputs if isinstance(ref, StepInput)]
    file_inputs = [ref for ref in step.inputs if isinstance(ref, FileInput)]
    assert [ref.step_id for ref in step_inputs] == ["validate_schema"]
    assert sorted(ref.path.name for ref in file_inputs) == sorted(_FIXTURE_FILES)


def test_step_registered_with_pipeline_appears_in_data_validation_phase() -> None:
    grouped = list_steps()

    assert "validate_hosting" in grouped["data_validation"]
    # validate_hosting follows validate_schema in the listing order.
    phase = grouped["data_validation"]
    assert phase.index("validate_hosting") > phase.index("validate_schema")


# --------------------------------------------------------------------------- #
# CLI discovery
# --------------------------------------------------------------------------- #


def test_find_shop_backend_cli_locates_dist(tmp_path: Path) -> None:
    """The walk-up locates ``packages/shop_backend/dist/cli.js`` when present."""
    if not _backend_available():
        pytest.skip(_BACKEND_REASON)
    del tmp_path
    cli = find_shop_backend_cli()
    assert cli.is_file()
    assert cli.parts[-3:] == ("shop_backend", "dist", "cli.js")


def test_find_shop_backend_cli_honours_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SHOP_BACKEND_CLI`` short-circuits the walk-up."""
    fake = tmp_path / "fake-cli.js"
    fake.write_text("// fake", encoding="utf-8")
    monkeypatch.setenv("SHOP_BACKEND_CLI", str(fake))

    assert find_shop_backend_cli() == fake.resolve()


def test_find_shop_backend_cli_rejects_missing_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid ``SHOP_BACKEND_CLI`` surfaces a clear error."""
    monkeypatch.setenv("SHOP_BACKEND_CLI", str(tmp_path / "nope.js"))

    with pytest.raises(HostingValidationError) as excinfo:
        find_shop_backend_cli()
    assert "SHOP_BACKEND_CLI" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Happy path — integration test against the real shop-backend
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _backend_available(), reason=_BACKEND_REASON)
def test_run_hosting_checks_passes_against_bundled_fixture(tmp_path: Path) -> None:
    """The §5.4 query suite passes end-to-end against the v0.1 fixture."""
    data_dir = _materialise_data_dir(tmp_path)

    verdict = run_hosting_checks(data_dir)

    assert verdict["ok"] is True
    assert verdict["store_name"] == "Mock Pet Foods"
    names = [c["name"] for c in verdict["checks"]]
    assert names == [
        "shop",
        "products",
        "collections",
        "collection_by_handle",
        "product_by_handle",
        "cart_lifecycle",
        "search",
        "image_get",
    ]
    for entry in verdict["checks"]:
        assert entry["ok"] is True, entry


@pytest.mark.skipif(not _backend_available(), reason=_BACKEND_REASON)
def test_validate_hosting_step_writes_data_validation_json(tmp_path: Path) -> None:
    """The step writes ``<out_dir>/data_validation.json`` with the verdict."""
    seed = tmp_path / "seed_a"
    seed.mkdir()
    out_dir = tmp_path / "out"
    _materialise_data_dir(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir)

    ValidateHostingStep().run(ctx)

    report_path = out_dir / "data_validation.json"
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["data_dir"] == str(out_dir / "data")
    assert all(c["ok"] for c in payload["checks"])


# --------------------------------------------------------------------------- #
# Failure path — empty collections.json
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _backend_available(), reason=_BACKEND_REASON)
def test_run_hosting_checks_fails_on_empty_collections(tmp_path: Path) -> None:
    """A dataset whose ``collections.json`` is ``[]`` fails the spec §5.4 suite."""
    data_dir = _materialise_data_dir(tmp_path)
    (data_dir / "collections.json").write_text("[]", encoding="utf-8")

    with pytest.raises(HostingValidationError) as excinfo:
        run_hosting_checks(data_dir)
    failed_names = {c["name"] for c in excinfo.value.checks if not c["ok"]}
    # ``collections`` (target>0 enforced) and ``collection_by_handle``
    # (no handle to query) both surface failures.
    assert "collections" in failed_names
    assert "collection_by_handle" in failed_names


@pytest.mark.skipif(not _backend_available(), reason=_BACKEND_REASON)
def test_validate_hosting_step_skips_writing_report_on_failure(tmp_path: Path) -> None:
    """A failing run leaves no stale ``data_validation.json`` behind."""
    seed = tmp_path / "seed_a"
    seed.mkdir()
    out_dir = tmp_path / "out"
    data_dir = _materialise_data_dir(out_dir)
    (data_dir / "collections.json").write_text("[]", encoding="utf-8")
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir)

    with pytest.raises(HostingValidationError):
        ValidateHostingStep().run(ctx)

    assert not (out_dir / "data_validation.json").exists()


# --------------------------------------------------------------------------- #
# Subprocess lifecycle — boot failure surfaces cleanly
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _backend_available(), reason=_BACKEND_REASON)
def test_run_hosting_checks_reports_boot_failure_when_data_dir_invalid(
    tmp_path: Path,
) -> None:
    """A missing ``data_dir`` fails fast with a :class:`HostingValidationError`."""
    bogus_data_dir = tmp_path / "does-not-exist"

    with pytest.raises((HostingValidationError, FileNotFoundError)):
        run_hosting_checks(bogus_data_dir, health_timeout_s=3.0)
