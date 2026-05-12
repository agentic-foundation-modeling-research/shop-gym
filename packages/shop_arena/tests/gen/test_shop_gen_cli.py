"""Unit tests for :mod:`shop_arena.gen.cli`.

Covers the T1.5 requirements from
``docs/impl/shop_gen_implementation.md``:

* ``shop-gen --list-steps`` prints every phase, even when the registry
  is empty (M2-M6 placeholders).
* ``shop-gen --status --out-dir <empty>`` prints "no run yet".
* ``shop-gen --status --out-dir <populated>`` projects every persisted
  record in the printed table.
* The argument parser accepts every flag listed in spec §5.8 and routes
  them to :func:`shop_arena.gen.pipeline.run` /
  :func:`shop_arena.gen.pipeline.status` /
  :func:`shop_arena.gen.pipeline.list_steps`.
* ``--from`` and ``--only`` are mutually exclusive and thread to the
  runner's ``force_ids`` plumbing.
* ``--status`` and ``--list-steps`` are mutually exclusive.
* Catalog / runtime knobs propagate into the constructed
  :class:`ShopGenConfig`.
* Invalid invocations (missing seeds, missing ``--out-dir`` for
  ``--status``, mutually-exclusive collisions) exit non-zero.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shop_arena.gen import cli as cli_mod
from shop_arena.gen.cli import EXIT_CONFIG, EXIT_OK, EXIT_RUNTIME, EXIT_USAGE, main
from shop_arena.gen.config import (
    DEFAULT_IMAGE_BACKEND,
    DEFAULT_JUDGES,
    DEFAULT_MAX_ITERS,
    DEFAULT_RUNTIME,
    DEFAULT_VISUAL_RETRY_BUDGET,
    KNOWN_JUDGES,
    ShopGenConfig,
    default_model_for,
)
from shop_arena.gen.pipeline import PHASES
from shop_arena.gen.steps.base import StepStatus
from shop_arena.gen.steps.runner import CycleError
from shop_arena.gen.steps.state import StateFile, StepStateRecord, write_state

_EXPECTED_MAX_ITERS = 7
_EXPECTED_COLLECTIONS = 3
_EXPECTED_PRODUCTS_PER_COLLECTION = 4
_EXPECTED_IMAGES_PER_PRODUCT = 5
_EXPECTED_VISUAL_RETRY_BUDGET = 5
_EXPECTED_VISUAL_JUDGE_PASS_THRESHOLD = 6.5
_EXPECTED_VISUAL_JUDGE_MAX_CONCURRENCY = 8
_EXPECTED_FINAL_EVAL_VISUAL_TIMEOUT_S = 120.0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_seed(tmp_path: Path, name: str = "seed") -> Path:
    seed = tmp_path / name
    seed.mkdir()
    return seed


@pytest.fixture
def captured_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub :func:`shop_arena.gen.cli.run` and capture its arguments."""
    captured: dict[str, Any] = {}

    def fake_run(
        config: ShopGenConfig,
        *,
        force_ids: frozenset[str] = frozenset(),
        stop_at: str | None = None,
    ) -> None:
        captured["config"] = config
        captured["force_ids"] = force_ids
        captured["stop_at"] = stop_at

    monkeypatch.setattr(cli_mod, "run", fake_run)
    return captured


# --------------------------------------------------------------------------- #
# --list-steps
# --------------------------------------------------------------------------- #


def test_list_steps_prints_every_phase(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--list-steps"])
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    for phase in PHASES:
        assert phase in out


def test_list_steps_ignores_other_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    """``--list-steps`` is config-free and short-circuits before argument validation."""
    rc = main(["--list-steps", "--out-dir", "irrelevant"])
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "shop-gen pipeline steps" in out


# --------------------------------------------------------------------------- #
# --status
# --------------------------------------------------------------------------- #


def test_status_prints_no_run_for_empty_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_dir = tmp_path / "shop"
    out_dir.mkdir()

    rc = main(["--status", "--out-dir", str(out_dir)])
    out = capsys.readouterr().out
    assert rc == EXIT_OK
    assert "no run yet" in out


def test_status_prints_no_run_for_missing_out_dir(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_dir = tmp_path / "missing"
    rc = main(["--status", "--out-dir", str(out_dir)])
    assert rc == EXIT_OK
    assert "no run yet" in capsys.readouterr().out


def test_status_prints_table_when_state_recorded(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_dir = tmp_path / "shop"
    out_dir.mkdir()
    write_state(
        out_dir,
        StateFile(
            steps={
                "synth_identity": StepStateRecord(
                    id="synth_identity",
                    phase="data_synth",
                    status=StepStatus.FRESH,
                    fingerprint="abc123",
                    ts="2025-01-01T00:00:00Z",
                ),
            },
        ),
    )

    rc = main(["--status", "--out-dir", str(out_dir)])
    out = capsys.readouterr().out

    assert rc == EXIT_OK
    assert "synth_identity" in out
    assert "data_synth" in out
    assert "fresh" in out
    assert "abc123" in out
    assert "no run yet" not in out


def test_status_requires_out_dir(capsys: pytest.CaptureFixture[str]) -> None:
    """``--status`` without ``--out-dir`` is a usage error (argparse exits 2)."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--status"])
    assert excinfo.value.code == EXIT_USAGE
    err = capsys.readouterr().err
    assert "--out-dir" in err


# --------------------------------------------------------------------------- #
# default run dispatch
# --------------------------------------------------------------------------- #


def test_default_run_builds_config_with_defaults(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"

    rc = main([str(seed), "--out-dir", str(out_dir)])

    assert rc == EXIT_OK
    config = captured_run["config"]
    assert isinstance(config, ShopGenConfig)
    assert config.seeds == (seed,)
    assert config.out_dir == out_dir
    assert config.name is None
    assert config.runtime == DEFAULT_RUNTIME
    assert config.model == default_model_for("pi")
    assert config.max_iters == DEFAULT_MAX_ITERS
    assert config.image_backend == DEFAULT_IMAGE_BACKEND
    assert config.visual_retry_budget == DEFAULT_VISUAL_RETRY_BUDGET
    assert config.catalog.collections > 0
    assert captured_run["force_ids"] == frozenset()


def test_default_run_threads_scale_and_runtime_knobs(
    tmp_path: Path,
    captured_run: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    rc = main(
        [
            str(seed),
            "--out-dir",
            str(out_dir),
            "--name",
            "acme",
            "--runtime",
            "claude_code",
            "--model",
            "claude-3-5-sonnet",
            "--max-iters",
            str(_EXPECTED_MAX_ITERS),
            "--collections",
            str(_EXPECTED_COLLECTIONS),
            "--products-per-collection",
            str(_EXPECTED_PRODUCTS_PER_COLLECTION),
            "--images-per-product",
            str(_EXPECTED_IMAGES_PER_PRODUCT),
            "--image-backend",
            "openai",
        ],
    )

    assert rc == EXIT_OK
    config = captured_run["config"]
    assert config.name == "acme"
    assert config.runtime == "claude_code"
    assert config.model == "claude-3-5-sonnet"
    assert config.max_iters == _EXPECTED_MAX_ITERS
    assert config.catalog.collections == _EXPECTED_COLLECTIONS
    assert config.catalog.products_per_collection == _EXPECTED_PRODUCTS_PER_COLLECTION
    assert config.catalog.images_per_product == _EXPECTED_IMAGES_PER_PRODUCT
    assert config.image_backend == "openai"


def test_empty_model_flag_skips_runtime_default(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """``--model ''`` opts the run out of the application-level default."""
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--model", ""])
    assert rc == EXIT_OK
    assert captured_run["config"].model is None


def test_visual_retry_budget_flag_propagates_to_config(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Impl plan T2.4: ``--visual-retry-budget`` threads into ``ShopGenConfig``."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--visual-retry-budget",
            str(_EXPECTED_VISUAL_RETRY_BUDGET),
        ]
    )
    assert rc == EXIT_OK
    assert captured_run["config"].visual_retry_budget == _EXPECTED_VISUAL_RETRY_BUDGET


def test_visual_retry_budget_zero_disables_budget(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """``--visual-retry-budget 0`` is a valid disable per spec \u00a75.4."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--visual-retry-budget",
            "0",
        ]
    )
    assert rc == EXIT_OK
    assert captured_run["config"].visual_retry_budget == 0


def test_visual_retry_budget_negative_is_config_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Negative budgets fail pydantic's ``ge=0`` and exit ``EXIT_CONFIG``."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--visual-retry-budget",
            "-1",
        ]
    )
    assert rc == EXIT_CONFIG
    assert "invalid configuration" in capsys.readouterr().err


def test_visual_judge_pass_threshold_flag_propagates_to_config(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Impl plan T3.6: ``--visual-judge-pass-threshold`` threads into ``ShopGenConfig``."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--visual-judge-pass-threshold",
            str(_EXPECTED_VISUAL_JUDGE_PASS_THRESHOLD),
        ]
    )
    assert rc == EXIT_OK
    assert (
        captured_run["config"].visual_judge_pass_threshold == _EXPECTED_VISUAL_JUDGE_PASS_THRESHOLD
    )


def test_visual_judge_pass_threshold_negative_is_config_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Impl plan T3.6: pydantic ``ge=0`` rejects negative thresholds."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--visual-judge-pass-threshold",
            "-1.0",
        ]
    )
    assert rc == EXIT_CONFIG
    assert "invalid configuration" in capsys.readouterr().err


def test_visual_judge_max_concurrency_flag_propagates_to_config(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Impl plan T3.6: ``--visual-judge-max-concurrency`` threads into ``ShopGenConfig``."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--visual-judge-max-concurrency",
            str(_EXPECTED_VISUAL_JUDGE_MAX_CONCURRENCY),
        ]
    )
    assert rc == EXIT_OK
    assert (
        captured_run["config"].visual_judge_max_concurrency
        == _EXPECTED_VISUAL_JUDGE_MAX_CONCURRENCY
    )


def test_visual_judge_max_concurrency_zero_is_config_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Impl plan T3.6: ``0`` worker count is rejected (must be strictly positive)."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--visual-judge-max-concurrency",
            "0",
        ]
    )
    assert rc == EXIT_CONFIG
    assert "invalid configuration" in capsys.readouterr().err


def test_final_eval_visual_timeout_flag_propagates_to_config(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Impl plan T5.4: ``--final-eval-visual-timeout`` threads into ``ShopGenConfig``."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--final-eval-visual-timeout",
            str(_EXPECTED_FINAL_EVAL_VISUAL_TIMEOUT_S),
        ]
    )
    assert rc == EXIT_OK
    assert (
        captured_run["config"].final_eval_visual_timeout_s
        == _EXPECTED_FINAL_EVAL_VISUAL_TIMEOUT_S
    )


def test_final_eval_visual_timeout_zero_is_config_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Impl plan T5.4: ``0`` timeout is rejected (must be strictly positive)."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--final-eval-visual-timeout",
            "0",
        ]
    )
    assert rc == EXIT_CONFIG
    assert "invalid configuration" in capsys.readouterr().err


def test_default_run_rejects_pi_grammar_model_with_claude_code_runtime(
    tmp_path: Path,
    captured_run: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--runtime claude_code --model anthropic/...`` exits ``EXIT_CONFIG`` fast.

    The pydantic ``ValidationError`` raised by
    :func:`harness.runtimes.validate_model_grammar` is rendered as a CLI
    config error rather than a stack trace, and the pipeline never runs.
    """
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--runtime",
            "claude_code",
            "--model",
            "anthropic/claude-opus-4-7",
        ]
    )
    assert rc == EXIT_CONFIG
    assert "config" not in captured_run
    err = capsys.readouterr().err
    assert "provider-prefixed" in err


def test_default_run_accepts_multiple_seeds(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    seed_a = _make_seed(tmp_path, "a")
    seed_b = _make_seed(tmp_path, "b")
    rc = main([str(seed_a), str(seed_b), "--out-dir", str(tmp_path / "out")])
    assert rc == EXIT_OK
    assert captured_run["config"].seeds == (seed_a, seed_b)


def test_default_run_requires_at_least_one_seed(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == EXIT_USAGE
    assert "SEED" in capsys.readouterr().err


def test_default_run_surfaces_invalid_catalog_as_config_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Negative scale knobs trip pydantic's ``gt=0`` and exit ``EXIT_CONFIG``."""
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--collections", "0"])
    assert rc == EXIT_CONFIG
    assert "invalid configuration" in capsys.readouterr().err


def test_default_run_surfaces_invalid_max_iters(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--max-iters", "0"])
    assert rc == EXIT_CONFIG
    assert "invalid configuration" in capsys.readouterr().err


def test_default_run_rejects_unknown_image_backend(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Argparse rejects unknown choices itself (usage error)."""
    seed = _make_seed(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main([str(seed), "--out-dir", str(tmp_path / "out"), "--image-backend", "magic"])
    assert excinfo.value.code == EXIT_USAGE
    assert "magic" in capsys.readouterr().err


def test_image_flags_thread_into_config(
    tmp_path: Path,
    captured_run: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--image-model`` / ``--image-size`` / ``--image-concurrency`` all propagate."""
    seed = _make_seed(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--image-backend",
            "openai",
            "--image-model",
            "gpt-image-2",
            "--image-size",
            "1024x1536",
            "--image-concurrency",
            "8",
        ]
    )
    assert rc == EXIT_OK
    config = captured_run["config"]
    assert config.image_backend == "openai"
    assert config.image_model == "gpt-image-2"
    assert config.image_size == "1024x1536"
    assert config.image_concurrency == 8


def test_openai_backend_without_api_key_is_config_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--image-backend openai`` with no ``OPENAI_API_KEY`` exits ``EXIT_CONFIG``."""
    seed = _make_seed(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--image-backend",
            "openai",
        ]
    )
    assert rc == EXIT_CONFIG
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_image_size_rejects_unknown_value(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Argparse rejects unknown ``--image-size`` values (usage error)."""
    seed = _make_seed(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                str(seed),
                "--out-dir",
                str(tmp_path / "out"),
                "--image-size",
                "999x999",
            ]
        )
    assert excinfo.value.code == EXIT_USAGE
    assert "999x999" in capsys.readouterr().err


def test_image_concurrency_zero_is_config_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--image-concurrency 0`` fails pydantic's ``gt=0`` and exits ``EXIT_CONFIG``."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--image-concurrency",
            "0",
        ]
    )
    assert rc == EXIT_CONFIG
    assert "invalid configuration" in capsys.readouterr().err


def test_default_run_surfaces_multi_seed_without_name(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-seed default with no ``--name`` and no ``--out-dir`` is a config error."""
    seed_a = _make_seed(tmp_path, "a")
    seed_b = _make_seed(tmp_path, "b")

    # Ensure the real ``pipeline.run`` runs (it raises ValueError pre-step).
    monkeypatch.chdir(tmp_path)
    rc = main([str(seed_a), str(seed_b)])
    assert rc == EXIT_CONFIG
    assert "multi-seed" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# --from / --only plumbing
# --------------------------------------------------------------------------- #


def test_from_threads_force_ids(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--from", "synth_identity"])
    assert rc == EXIT_OK
    assert captured_run["force_ids"] == frozenset({"synth_identity"})


def test_only_threads_force_ids(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--only", "gen_homepage"])
    assert rc == EXIT_OK
    assert captured_run["force_ids"] == frozenset({"gen_homepage"})


def test_from_and_only_are_mutually_exclusive(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = _make_seed(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                str(seed),
                "--out-dir",
                str(tmp_path / "out"),
                "--from",
                "a",
                "--only",
                "b",
            ],
        )
    assert excinfo.value.code == EXIT_USAGE
    assert "not allowed" in capsys.readouterr().err.lower()


def test_to_threads_stop_at(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--to", "assemble_data"])
    assert rc == EXIT_OK
    assert captured_run["stop_at"] == "assemble_data"
    assert captured_run["force_ids"] == frozenset()


def test_to_defaults_to_none_when_omitted(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out")])
    assert rc == EXIT_OK
    assert captured_run["stop_at"] is None


def test_to_composes_with_from(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """``--to`` and ``--from`` are independent: the slice plus the force-stale set."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--from",
            "synth_collections",
            "--to",
            "assemble_data",
        ],
    )
    assert rc == EXIT_OK
    assert captured_run["force_ids"] == frozenset({"synth_collections"})
    assert captured_run["stop_at"] == "assemble_data"


def test_to_surfaces_value_error_from_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown ``--to STEP`` raises ``ValueError`` in pipeline.run; surface as config error."""

    def fake_run(
        _config: ShopGenConfig,
        *,
        force_ids: frozenset[str] = frozenset(),
        stop_at: str | None = None,
    ) -> None:
        del force_ids
        raise ValueError(f"--to target {stop_at!r} is not registered for this run")

    monkeypatch.setattr(cli_mod, "run", fake_run)
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--to", "ghost"])
    assert rc == EXIT_CONFIG
    assert "ghost" in capsys.readouterr().err


def test_status_and_list_steps_are_mutually_exclusive(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--status", "--list-steps", "--out-dir", str(tmp_path)])
    assert excinfo.value.code == EXIT_USAGE
    assert "not allowed" in capsys.readouterr().err.lower()


# --------------------------------------------------------------------------- #
# Pipeline error surfacing
# --------------------------------------------------------------------------- #


def test_default_run_surfaces_runner_dag_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(
        _config: ShopGenConfig,
        *,
        force_ids: frozenset[str] = frozenset(),
        stop_at: str | None = None,
    ) -> None:
        del force_ids, stop_at
        raise CycleError("simulated cycle")

    monkeypatch.setattr(cli_mod, "run", boom)
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out")])
    assert rc != EXIT_OK
    assert "DAG error" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# T5.7 — append-redo for `--only gen_<task>` against a completed build dir
# --------------------------------------------------------------------------- #

_COMPLETED_BUILD_PLAN = """\
# Plan

## Tasks

- [x] gen_theme — ship the theme tokens [priority: 9]
- [x] gen_navigation — wire the header / footer [priority: 8]
- [x] gen_homepage — render the hero [priority: 7]
- [x] visual_fix — REQUIRED final task [priority: 1]
"""


def _seed_completed_build_plan(out_dir: Path) -> Path:
    """Lay out a completed-run ``plan.md`` snapshot under ``out_dir``."""
    plan_path = out_dir / "runs" / "build" / "plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(_COMPLETED_BUILD_PLAN, encoding="utf-8")
    return plan_path


def test_only_appends_redo_against_completed_build_task(
    tmp_path: Path,
    captured_run: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T5.7: ``--only gen_homepage`` against a completed build dir appends ``_redo_1``

    and forces ``run_build_harness_loop`` instead of the literal ``--only`` arg."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    plan_path = _seed_completed_build_plan(out_dir)
    original = plan_path.read_text(encoding="utf-8")

    rc = main([str(seed), "--out-dir", str(out_dir), "--only", "gen_homepage"])

    assert rc == EXIT_OK
    assert captured_run["force_ids"] == frozenset({"run_build_harness_loop"})
    after = plan_path.read_text(encoding="utf-8")
    assert "gen_homepage_redo_1" in after
    # T5.7 (a): the original [x] line is preserved verbatim.
    for line in original.splitlines():
        assert line in after.splitlines()
    err = capsys.readouterr().err
    assert "gen_homepage_redo_1" in err


def test_only_increments_redo_suffix_on_followup(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """T5.7 (c): a follow-up ``--only`` against the same task increments the suffix."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    plan_path = _seed_completed_build_plan(out_dir)

    rc1 = main([str(seed), "--out-dir", str(out_dir), "--only", "gen_homepage"])
    rc2 = main([str(seed), "--out-dir", str(out_dir), "--only", "gen_homepage"])

    assert rc1 == EXIT_OK
    assert rc2 == EXIT_OK
    after = plan_path.read_text(encoding="utf-8")
    assert "gen_homepage_redo_1" in after
    assert "gen_homepage_redo_2" in after
    # The most recent invocation is the one captured by the stub.
    assert captured_run["force_ids"] == frozenset({"run_build_harness_loop"})


def test_only_falls_through_when_target_is_pending(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Non-DONE tasks are still owned by the harness — ``--only`` falls through."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    plan_path = out_dir / "runs" / "build" / "plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        "## Tasks\n\n- [ ] gen_homepage — pending [priority: 7]\n",
        encoding="utf-8",
    )
    before = plan_path.read_text(encoding="utf-8")

    rc = main([str(seed), "--out-dir", str(out_dir), "--only", "gen_homepage"])

    assert rc == EXIT_OK
    # No redo append — file unchanged, regular ``force_ids`` plumbing kicks in.
    assert plan_path.read_text(encoding="utf-8") == before
    assert captured_run["force_ids"] == frozenset({"gen_homepage"})


def test_only_falls_through_when_no_build_plan_exists(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Without a build ``plan.md``, ``--only`` keeps the regular force-ids path."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    rc = main([str(seed), "--out-dir", str(out_dir), "--only", "synth_identity"])

    assert rc == EXIT_OK
    assert captured_run["force_ids"] == frozenset({"synth_identity"})


def test_only_surfaces_invalid_build_plan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A corrupted ``plan.md`` exits via :data:`EXIT_RUNTIME`."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    plan_path = out_dir / "runs" / "build" / "plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("# no tasks heading\n", encoding="utf-8")

    rc = main([str(seed), "--out-dir", str(out_dir), "--only", "gen_homepage"])

    assert rc == EXIT_RUNTIME
    assert "cannot parse" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# --judges plumbing (impl plan T3.4, spec §5.5 + §5.9)
# --------------------------------------------------------------------------- #


def test_judges_default_is_full_known_set(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Omitting ``--judges`` keeps the :data:`DEFAULT_JUDGES` default."""
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out")])
    assert rc == EXIT_OK
    assert captured_run["config"].judges == DEFAULT_JUDGES


def test_judges_comma_list_propagates_to_config(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Impl plan T3.4: ``--judges visual_judge,quality_judge`` selects exactly those two."""
    seed = _make_seed(tmp_path)
    rc = main(
        [
            str(seed),
            "--out-dir",
            str(tmp_path / "out"),
            "--judges",
            "visual_judge,quality_judge",
        ]
    )
    assert rc == EXIT_OK
    assert captured_run["config"].judges == frozenset({"visual_judge", "quality_judge"})


def test_judges_none_selects_empty_set(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Impl plan T3.4: ``--judges none`` disables every LLM judge."""
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--judges", "none"])
    assert rc == EXIT_OK
    assert captured_run["config"].judges == frozenset()


def test_judges_all_selects_full_default_set(
    tmp_path: Path,
    captured_run: dict[str, Any],
) -> None:
    """Impl plan T3.4: ``--judges all`` selects :data:`DEFAULT_JUDGES`."""
    seed = _make_seed(tmp_path)
    rc = main([str(seed), "--out-dir", str(tmp_path / "out"), "--judges", "all"])
    assert rc == EXIT_OK
    assert captured_run["config"].judges == DEFAULT_JUDGES
    assert captured_run["config"].judges == KNOWN_JUDGES


def test_judges_rejects_unknown_token(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Impl plan T3.4: unknown judge tokens exit ``EXIT_USAGE`` with the offending name."""
    seed = _make_seed(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main([str(seed), "--out-dir", str(tmp_path / "out"), "--judges", "bogus"])
    assert excinfo.value.code == EXIT_USAGE
    err = capsys.readouterr().err
    assert "bogus" in err


def test_judges_rejects_partial_unknown_token(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A comma list mixing known + unknown still rejects the unknown one."""
    seed = _make_seed(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                str(seed),
                "--out-dir",
                str(tmp_path / "out"),
                "--judges",
                "visual_judge,bogus",
            ]
        )
    assert excinfo.value.code == EXIT_USAGE
    err = capsys.readouterr().err
    assert "bogus" in err
